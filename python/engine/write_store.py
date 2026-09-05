"""每文件单写者写路径（write-through store）。

设计（docs/实施计划/29-普通多Agent协同落地实施计划书.md §2.1）：
- **每文件一把锁**：同文件串行 apply，不同文件可并行（submit 走 to_thread）。
- **content-hash 版本校验**：base vs 磁盘哈希，不一致 -> stale，不覆盖。
- **原子写**：temp + os.replace。
- **P0 单文件事务**；多文件走 _apply_multi 预检。
- **语法校验**：Python/JSON 增量（新文件引入错误才记 syntax_valid=false）。
"""

from __future__ import annotations

import ast
import asyncio
import difflib
import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable

from memory import journal

_journal_logger = logging.getLogger("xeyo.write_store.journal")


@dataclass
class EditOp:
    """一次写操作。P0 只支持单文件（每事务一个 op）。"""
    path: str
    new_content: str | None = None          # kind="write"：整文件内容
    old_string: str | None = None            # kind="edit"：被替换文本
    new_string: str | None = None            # kind="edit"：替换后文本
    replace_all: bool = False

    @property
    def kind(self) -> str:
        if self.new_content is not None:
            return "write"
        return "edit"


@dataclass
class ChangeIntent:
    """agent 提交的变更事务（不含锁；store 串行应用）。"""
    agent_id: str
    ops: list[EditOp]
    base_hashes: dict[str, str] = field(default_factory=dict)   # path -> sha256（读时）
    annotation: dict[str, Any] = field(default_factory=dict)
    #: 目标文件编码（Read 检测到的，如 utf-16-le）；缺省 utf-8。
    encoding: str = "utf-8"


@dataclass
class ApplyResult:
    """一次提交的结果（供调度器判断）。"""
    ok: bool
    version: str = ""                       # 新版本（rev_...，供审计）
    reason: str = "ok"                      # ok | stale | conflict | syntax_invalid
    detail: str = ""
    base_stale: bool = False
    syntax_valid: bool = True
    new_hashes: dict[str, str] = field(default_factory=dict)
    # T28：journal 记录失败时非空——文件已落盘但证据链缺口必须可观测。
    journal_warning: str = ""


def _content_hash(path: Path) -> str:
    """读盘算 sha256（不用 mtime，B8/C6）。

    哈希源是**归一化文本**（read_text_file：CRLF→LF、utf-16 解码）而非磁盘
    原始字节——base_hashes 由 `_content_hash_text(entry.content)` 产生，而
    entry.content 是 Read 归一化后的文本；若这里按原始字节哈希，Windows 上
    的 CRLF/UTF-16 文件永远对不上，子 agent 首次写入必报 stale。
    """
    try:
        from tools.fileio.text import read_text_file

        text, _endings, _enc = read_text_file(str(path))
    except (OSError, ValueError):
        return ""
    return _content_hash_text(text)


def _content_hash_text(content: str) -> str:
    """对内存中的文本算 sha256，作为 base_hashes。"""
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


def _syntax_error_count(suffix: str, text: str) -> int:
    """可解析语言的错误个数（0/1）；未知语言视为 0。"""
    suf = (suffix or "").lower()
    if suf == ".py":
        try:
            ast.parse(text or "")
            return 0
        except SyntaxError:
            return 1
    if suf == ".json":
        try:
            json.loads(text or "")
            return 0
        except json.JSONDecodeError:
            return 1
    return 0


def _syntax_ok(path: Path, new_content: str) -> bool:
    """增量语法门：仅当本次写入引入了新的解析错误时返回 False。"""
    suffix = path.suffix
    new_err = _syntax_error_count(suffix, new_content)
    if new_err == 0:
        return True
    try:
        old = path.read_text(encoding="utf-8")
    except OSError:
        old = ""
    old_err = _syntax_error_count(suffix, old)
    return new_err <= old_err


def _read_text_safe(path: Path) -> str:
    """写前读取归一化文本（CRLF→LF / utf-16 解码）；不存在或失败返回空串。"""
    try:
        from tools.fileio.text import read_text_file

        text, _endings, _enc = read_text_file(str(path))
        return text
    except Exception:  # noqa: BLE001
        return ""


#: 单条变更 diff 的最大行数（超限截断，避免 journal 膨胀；DiffPreview 以「…」渲染 note）。
_MAX_DIFF_LINES = 400


def _make_unified_diff(path: Path, before: str, after: str) -> str:
    """改前 vs 改后 → unified diff 快照（供「工作区变更」点开渲染，文件删除也可见）。"""
    before_lines = (before or "").splitlines()
    after_lines = (after or "").splitlines()
    if before_lines == after_lines:
        return ""
    try:
        label = str(path).replace("\\", "/")
        lines = list(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=f"a/{label}",
                tofile=f"b/{label}",
                lineterm="",
            )
        )
    except Exception:  # noqa: BLE001
        return ""
    if not lines:
        return ""
    if len(lines) > _MAX_DIFF_LINES:
        lines = lines[:_MAX_DIFF_LINES]
        lines.append("…（diff 过长，已截断）")
    return "\n".join(lines)


class WriteStore:
    """每文件一把线程锁。submit_sync 热路径；async submit 把 apply 挪出事件循环。"""

    def __init__(self, root: str | Path, *, shards: int = 64) -> None:
        self._root = Path(root).expanduser().resolve()
        self._shards = max(1, shards)
        # 分片锁：路径哈希映射到固定数量的锁。曾按"每文件一把锁"实现，
        # 锁表只增不减（长会话内存无界）；分片同样保证同文件串行。
        self._shard_locks: list[threading.Lock] = [
            threading.Lock() for _ in range(self._shards)
        ]

    def _lock_for(self, path: str) -> threading.Lock:
        return self._shard_locks[hash(path) % self._shards]

    def submit(self, intent: ChangeIntent) -> Awaitable[ApplyResult]:
        """异步提交：单文件事务，apply 在线程里跑，不同文件可并行。"""
        if len(intent.ops) != 1:
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            fut.set_result(ApplyResult(
                ok=False, reason="not_supported",
                detail="multi-file not allowed in P0",
            ))
            return fut
        return asyncio.to_thread(self.submit_sync, intent)

    async def close(self) -> None:
        """兼容旧接口：无后台 worker 需要停止。"""
        return None

    def _canon(self, path: str) -> Path:
        resolved = (
            (self._root / path).resolve()
            if not os.path.isabs(path)
            else Path(path).resolve()
        )
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise PermissionError(
                f"WriteStore path outside workspace root: {resolved}"
            ) from exc
        # 子 Agent 写 scope 二次硬门禁
        from permissions.write_scope import write_scope_deny_reason

        reason = write_scope_deny_reason(str(resolved), cwd=str(self._root))
        if reason:
            raise PermissionError(f"WriteStore {reason}: {resolved}")
        return resolved

    def submit_sync(self, intent: ChangeIntent) -> ApplyResult:
        """同步直写：content-hash + 每文件锁 + 原子写 + journal。"""
        if len(intent.ops) != 1:
            return ApplyResult(
                ok=False, reason="not_supported",
                detail="multi-file not allowed in P0",
            )
        try:
            path = self._canon(intent.ops[0].path)
        except PermissionError as exc:
            return ApplyResult(
                ok=False, reason="path_denied", detail=str(exc),
            )
        with self._lock_for(str(path)):
            return self._apply_core(intent, path)

    def _apply_core(self, intent: ChangeIntent, path: Path) -> ApplyResult:
        """同步核心：content-hash 校验 -> 计算内容 -> 语法增量 -> 原子写 -> journal。"""
        base = self._lookup_base_hash(intent, path)
        current = _content_hash(path)

        session_id = self._session_id_from_intent(intent)

        if base and current and base != current:
            wsid = self._workspace_id()
            rec = journal.ChangeRecord(
                seq=0,
                agent_id=intent.agent_id,
                path=str(path),
                action="stale_reject",
                file_hash_after=current,
                ts=round(__import__("time").time(), 3),
                brief="write rejected: base hash stale",
                syntax_valid=True,
                conflict_task=True,
                metadata={"session_id": session_id} if session_id else {},
            )
            journal.record_change(wsid, rec)
            try:
                from usage.multi_agent_metrics import record_write_stale

                record_write_stale(agent_id=intent.agent_id, path=str(path))
            except Exception:  # noqa: BLE001
                pass
            detail = ""
            try:
                from engine.session_presence import format_stale_owner_hint

                detail = format_stale_owner_hint(str(self._root), str(path))
            except Exception:  # noqa: BLE001
                detail = ""
            return ApplyResult(
                ok=False,
                reason="stale",
                base_stale=True,
                version=current,
                detail=detail,
            )

        # 已有文件但未提供 base（未 Read）→ 拒绝盲写，避免并发覆盖。
        if current and not base:
            return ApplyResult(
                ok=False,
                reason="missing_read",
                base_stale=True,
                version=current,
                detail="Read the file before writing when using WriteStore",
            )

        new_content = _compute_new_content(intent.ops[0], path)
        if new_content is None:
            return ApplyResult(ok=False, reason="conflict", detail="op cannot apply")

        syntax_ok = _syntax_ok(path, new_content)

        # 改前内容（写前抓取，用于生成 unified diff 快照；文件不存在/不可读则视为空）。
        before_content = _read_text_safe(path)
        change_diff = _make_unified_diff(path, before_content, new_content)

        self._atomic_write(path, new_content, encoding=intent.encoding)

        new_hash = _content_hash(path)
        rec = journal.ChangeRecord(
            seq=0,
            agent_id=intent.agent_id,
            path=str(path),
            action=intent.ops[0].kind,
            file_hash_after=new_hash,
            ts=round(__import__("time").time(), 3),
            brief=str(intent.annotation.get("goal", "")),
            syntax_valid=syntax_ok,
            conflict_task=(bool(base) and bool(current) and base != current),
            diff=change_diff,
            metadata={"session_id": session_id} if session_id else {},
        )
        # journal 只是审计：文件已成功落盘，记录失败不得让工具报错——
        # 否则调用方 read_state 不更新，下一轮反而误报 modified-since-read。
        # T28：但「假 ok」不可接受——显式记日志并把警示带回工具结果。
        journal_warning = ""
        try:
            journal.record_change(self._workspace_id(), rec)
        except Exception:  # noqa: BLE001
            _journal_logger.exception(
                "write_store journal record failed path=%s", path
            )
            journal_warning = (
                f"[journal] rewind 证据记录失败（{type(journal).__name__}）："
                "本次写操作已落盘但未进入可回溯日志，请检查磁盘/权限。"
            )
        self._note_presence_write(path, session_id)

        return ApplyResult(
            ok=True, version=new_hash, reason="ok",
            syntax_valid=syntax_ok, new_hashes={str(path): new_hash},
            journal_warning=journal_warning,
        )

    @staticmethod
    def _session_id_from_intent(intent: ChangeIntent) -> str:
        meta = intent.annotation or {}
        sid = str(meta.get("session_id") or "").strip()
        if sid:
            return sid
        try:
            from engine.workspace_context import get_workspace_context

            ctx = get_workspace_context()
            if ctx is not None and ctx.session_id:
                return str(ctx.session_id).strip()
        except Exception:  # noqa: BLE001
            pass
        return ""

    def _note_presence_write(self, path: Path, session_id: str) -> None:
        if not session_id:
            return
        try:
            from engine.session_presence import default_session_presence

            default_session_presence().note_write(
                str(self._root), session_id, str(path)
            )
        except Exception:  # noqa: BLE001
            pass

    async def _apply_multi(self, intent: ChangeIntent) -> ApplyResult:
        """多文件预检：先全部校验 base，任一冲突则整体拒绝。"""
        path_keys = {str(self._canon(op.path)) for op in intent.ops}
        conflicted = [
            p for p in path_keys
            if intent.base_hashes.get(p, "")
            and _content_hash(Path(p)) != intent.base_hashes[p]
        ]
        if conflicted:
            return ApplyResult(ok=False, reason="conflict", detail="multi-file precheck")
        results = []
        for op in intent.ops:
            results.append(self.submit_sync(ChangeIntent(
                agent_id=intent.agent_id, ops=[op], base_hashes=intent.base_hashes,
                annotation=intent.annotation,
            )))
        if all(r.ok for r in results):
            hashes = {k: v for r in results for k, v in r.new_hashes.items()}
            return ApplyResult(
                ok=True, version=", ".join(hashes.values()),
                syntax_valid=all(r.syntax_valid for r in results),
                new_hashes=hashes,
            )
        return ApplyResult(ok=False, reason="conflict", detail="multi-file partial")

    def _lookup_base_hash(self, intent: ChangeIntent, path: Path) -> str:
        """匹配 base_hashes 键（兼容相对/绝对/正反斜杠）。"""
        for k, v in (intent.base_hashes or {}).items():
            try:
                if self._canon(str(k)) == path:
                    return str(v or "")
            except Exception:  # noqa: BLE001
                continue
        return str(intent.base_hashes.get(str(path), "") or "")

    @staticmethod
    def _atomic_write(path: Path, content: str, encoding: str = "utf-8") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".xeyo.write.tmp")
        # 复用 write_text_file 的编码语义（utf-16-le 补 BOM），
        # 但绕过它的 line_endings 逻辑：换行形态由调用方在 content 里定稿，
        # 此处只做原子替换（tmp + os.replace），禁止平台翻译。
        write_encoding = encoding or "utf-8"
        if write_encoding == "utf-16-le":
            data = b"\xff\xfe" + content.encode("utf-16-le")
        else:
            data = content.encode(write_encoding, errors="replace")
        try:
            with open(tmp, "wb") as handle:
                handle.write(data)
            os.replace(tmp, path)
        except OSError:
            # 失败清理 tmp 残留（Windows 下目标被占用是常态，不留垃圾文件）。
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise

    def _workspace_id(self) -> str:
        try:
            from memory.memdir import workspace_id

            return workspace_id(str(self._root))
        except Exception:  # noqa: BLE001
            return self._root.name or "ws"


def _compute_new_content(op: EditOp, path: Path) -> str | None:
    """由 op 计算目标内容；应用不了返回 None（冲突）。"""
    if op.kind == "write":
        return op.new_content or ""
    # 与 Read 同源的归一化文本：模型的 old_string 来自 Read（CRLF→LF），
    # 若按原始字节读盘，CRLF 文件的 old_string 永远匹配不上 → 假 conflict。
    try:
        from tools.fileio.text import read_text_file

        content, _endings, _enc = read_text_file(str(path))
    except (OSError, ValueError):
        return None
    if op.replace_all:
        return content.replace(op.old_string or "", op.new_string or "")
    if (op.old_string or "") not in content:
        return None
    return content.replace(op.old_string or "", op.new_string or "", 1)
