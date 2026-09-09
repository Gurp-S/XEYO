"""回溯 v3 热路径：AgentFileIndex + COW checkpoint。

替代「每轮全仓 ``git add -A``」的记录模型：

- :class:`AgentFileIndex` —— 会话内 ``path → 最新 blob`` 的 upsert 账本
  （``agent_file_index.jsonl``，latest-wins）。
- :func:`freeze_checkpoint` —— user 消息发送时对当前索引做 COW 快照
  （``checkpoints.jsonl``），``checkpoint_id`` 绑定该条 user 消息；恢复时
  只写快照中的路径。
- turn 起止双向差量 —— turn 开始记 lstat 基线（:func:`capture_turn_baseline`），
  turn 结束仅对变化路径读盘入库（:func:`sync_index_from_turn_diff`），
  Edit/Write 之外的变更（Bash 等）由此兜底。

热路径约束：零 ``git add -A``、零整树内容读取、零必经 preview。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rewind.snapshot import SnapshotStore
from session.persistence import default_sessions_dir, safe_session_filename

__all__ = [
    "AgentFileIndex",
    "FileCheckpoint",
    "TurnBaseline",
    "TurnFileDiff",
    "capture_turn_baseline",
    "diff_turn_changes",
    "freeze_checkpoint",
    "get_checkpoint_anchor",
    "load_checkpoint",
    "mark_checkpoint_anchor",
    "sync_index_from_ledger",
    "sync_index_from_turn_diff",
]

#: turn 差量扫描默认忽略的目录名（不进索引、不进恢复范围）。
DEFAULT_IGNORE_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".xy-shadow-git",
        ".xy-trash",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
        ".xeyo",
        ".xeyo_sessions",
        "dist",
        "build",
        "target",
    }
)

#: 基线/差量扫描的文件数上限，超过即放弃本 turn 差量（防御异常巨大的工作区）。
DEFAULT_TURN_SCAN_LIMIT = 50_000

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    key = str(path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


def _append_row(path: Path, payload: dict[str, Any]) -> None:
    """追加一行 JSONL 并 fsync（崩溃顺序合同要求）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    with _lock_for(path):
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with _lock_for(path):
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    return rows


@dataclass
class IndexEntry:
    """AgentFileIndex 一条 latest 记录；``content_hash is None`` 表示删除标记。"""

    path: str
    content_hash: str | None
    size: int
    mtime_ns: int
    source: str
    ts: float


class AgentFileIndex:
    """会话作用域的 agent 文件账本（append-only，读时 latest-wins 折叠）。"""

    def __init__(
        self,
        session_id: str,
        *,
        sessions_dir: Path | None = None,
    ) -> None:
        self.session_id = str(session_id or "").strip()
        if not self.session_id:
            raise ValueError("session_id is required")
        self.sessions_dir = sessions_dir or default_sessions_dir()

    @property
    def path(self) -> Path:
        return (
            self.sessions_dir
            / safe_session_filename(self.session_id)
            / "agent_file_index.jsonl"
        )

    def upsert(
        self,
        path: str,
        *,
        content_hash: str | None,
        size: int,
        mtime_ns: int,
        source: str,
    ) -> IndexEntry:
        row = {
            "path": _normalize_rel_path(path),
            "content_hash": content_hash,
            "size": int(size),
            "mtime_ns": int(mtime_ns),
            "source": source,
            "ts": time.time(),
        }
        _append_row(self.path, row)
        return IndexEntry(**row)

    def entries(self) -> dict[str, IndexEntry]:
        latest: dict[str, IndexEntry] = {}
        for row in _read_rows(self.path):
            try:
                entry = IndexEntry(
                    path=str(row.get("path") or ""),
                    content_hash=(
                        str(row["content_hash"]) if row.get("content_hash") else None
                    ),
                    size=int(row.get("size") or 0),
                    mtime_ns=int(row.get("mtime_ns") or 0),
                    source=str(row.get("source") or ""),
                    ts=float(row.get("ts") or 0.0),
                )
            except (TypeError, ValueError):
                continue
            if entry.path:
                latest[entry.path] = entry
        return latest


@dataclass
class FileCheckpoint:
    """某条 user 消息发出时、agent 作用域文件的 blob 图（COW）。"""

    checkpoint_id: str
    user_message_id: str
    ts: float
    entries: dict[str, str] = field(default_factory=dict)


def _checkpoints_path(session_id: str, sessions_dir: Path | None) -> Path:
    root = sessions_dir or default_sessions_dir()
    return root / safe_session_filename(session_id) / "checkpoints.jsonl"


def _normalize_rel_path(raw: str) -> str:
    # 不能用 lstrip("./")：那是按字符集剥离，会把根目录点文件
    # ".gitignore"/".env" 改写成 "gitignore"/"env"，restore/undo 落到错误路径。
    text = str(raw or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text.lstrip("/").strip()


def _hash_entries(session_id: str, user_message_id: str, entries: dict[str, str]) -> str:
    digest = hashlib.sha256()
    digest.update(f"{session_id}|{user_message_id}".encode("utf-8"))
    for path in sorted(entries):
        digest.update(f"{path}:{entries[path]}".encode("utf-8"))
    return f"cp3_{digest.hexdigest()[:32]}"


def freeze_checkpoint(
    session_id: str,
    user_message_id: str,
    *,
    snapshots: SnapshotStore,
    sessions_dir: Path | None = None,
    index: AgentFileIndex | None = None,
) -> FileCheckpoint:
    """发送时冻结 COW checkpoint；同 (session, user message, 图) 幂等。"""
    idx = index or AgentFileIndex(session_id, sessions_dir=sessions_dir)
    entries = {
        entry.path: entry.content_hash
        for entry in idx.entries().values()
        if entry.content_hash
    }
    checkpoint_id = _hash_entries(session_id, user_message_id, entries)
    path = _checkpoints_path(session_id, sessions_dir)
    for row in _read_rows(path):
        if row.get("checkpoint_id") == checkpoint_id:
            return FileCheckpoint(
                checkpoint_id=checkpoint_id,
                user_message_id=user_message_id,
                ts=float(row.get("ts") or 0.0),
                entries=entries,
            )
    _append_row(
        path,
        {
            "checkpoint_id": checkpoint_id,
            "user_message_id": user_message_id,
            "ts": time.time(),
            "entries": sorted(entries.items()),
        },
    )
    return FileCheckpoint(
        checkpoint_id=checkpoint_id,
        user_message_id=user_message_id,
        ts=time.time(),
        entries=entries,
    )


def find_checkpoint_for_message(
    session_id: str,
    user_message_id: str,
    *,
    sessions_dir: Path | None = None,
) -> FileCheckpoint | None:
    """按 user 消息查最近一次冻结的 checkpoint（弹窗 Restore 可用性判断）。"""
    uid = str(user_message_id or "").strip()
    if not uid:
        return None
    for row in reversed(_read_rows(_checkpoints_path(session_id, sessions_dir))):
        if str(row.get("user_message_id") or "") != uid:
            continue
        cp = load_checkpoint(session_id, str(row.get("checkpoint_id") or ""), sessions_dir=sessions_dir)
        if cp is not None:
            return cp
    return None


def load_checkpoint(
    session_id: str,
    checkpoint_id: str,
    *,
    sessions_dir: Path | None = None,
) -> FileCheckpoint | None:
    cp = str(checkpoint_id or "").strip()
    if not cp:
        return None
    for row in _read_rows(_checkpoints_path(session_id, sessions_dir)):
        if row.get("checkpoint_id") != cp:
            continue
        raw_entries = row.get("entries")
        entries: dict[str, str] = {}
        if isinstance(raw_entries, list):
            for item in raw_entries:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    entries[str(item[0])] = str(item[1])
                elif isinstance(item, dict):
                    entries[str(item.get("path"))] = str(item.get("content_hash") or "")
        return FileCheckpoint(
            checkpoint_id=cp,
            user_message_id=str(row.get("user_message_id") or ""),
            ts=float(row.get("ts") or 0.0),
            entries=entries,
        )
    return None


def mark_checkpoint_anchor(
    session_id: str,
    user_message_id: str,
    *,
    anchor: bool = True,
    sessions_dir: Path | None = None,
) -> str | None:
    """给某条 user 消息的 checkpoint 打/取消锚点（§9.1 锚点写入方）。

    通过追加一行 ``{...checkpoint, "anchor": True}`` 实现 latest-wins：blob_gc 读侧
    见 ``anchor is True`` 即保留该 checkpoint（以及与之关联的 turn/操作）。
    """
    uid = str(user_message_id or "").strip()
    if not uid:
        return None
    cp = find_checkpoint_for_message(session_id, uid, sessions_dir=sessions_dir)
    if cp is None:
        return None
    path = _checkpoints_path(session_id, sessions_dir)
    _append_row(
        path,
        {
            "checkpoint_id": cp.checkpoint_id,
            "user_message_id": uid,
            "ts": time.time(),
            "entries": sorted(cp.entries.items()),
            "anchor": bool(anchor),
        },
    )
    return cp.checkpoint_id


def get_checkpoint_anchor(
    session_id: str,
    user_message_id: str,
    *,
    sessions_dir: Path | None = None,
) -> bool:
    """某条 user 消息的 checkpoints 是否已标记为锚点（取消锚点入口用）。"""
    uid = str(user_message_id or "").strip()
    if not uid:
        return False
    for row in reversed(_read_rows(_checkpoints_path(session_id, sessions_dir))):
        if str(row.get("user_message_id") or "") != uid:
            continue
        return bool(row.get("anchor") is True or (isinstance(row.get("metadata"), dict) and row["metadata"].get("anchor") is True))
    return False


@dataclass
class TurnBaseline:
    """turn 开始时的工作区 lstat 签名（path → (size, mtime_ns)）。"""

    root: Path
    signatures: dict[str, tuple[int, int]] = field(default_factory=dict)
    truncated: bool = False


@dataclass
class TurnFileDiff:
    """turn 结束时相对基线的差量。"""

    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    truncated: bool = False


def _walk_signatures(
    workspace_root: Path | str,
    *,
    ignore_names: frozenset[str] | None,
    limit: int,
) -> tuple[dict[str, tuple[int, int]], bool]:
    root = Path(workspace_root)
    ignores = ignore_names or DEFAULT_IGNORE_NAMES
    signatures: dict[str, tuple[int, int]] = {}
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignores]
        for name in filenames:
            if name in ignores:
                continue
            full = Path(dirpath) / name
            try:
                stat = full.lstat()
            except OSError:
                continue
            if not stat.st_size and full.suffix in {".sock", ".pipe"}:
                continue
            rel = full.relative_to(root).as_posix()
            if len(signatures) >= limit:
                truncated = True
                return signatures, truncated
            signatures[rel] = (stat.st_size, stat.st_mtime_ns)
    return signatures, truncated


def capture_turn_baseline(
    workspace_root: Path | str,
    *,
    ignore_names: frozenset[str] | None = None,
    limit: int = DEFAULT_TURN_SCAN_LIMIT,
) -> TurnBaseline:
    """turn 开始调用：仅 lstat，不读内容。超限返回 ``truncated=True``（差量放弃）。"""
    signatures, truncated = _walk_signatures(
        workspace_root, ignore_names=ignore_names, limit=limit
    )
    return TurnBaseline(
        root=Path(workspace_root), signatures=signatures, truncated=truncated
    )


def diff_turn_changes(
    baseline: TurnBaseline,
    *,
    ignore_names: frozenset[str] | None = None,
    limit: int = DEFAULT_TURN_SCAN_LIMIT,
) -> TurnFileDiff:
    """turn 结束调用：与基线比对签名，仅返回变化/消失的路径。"""
    current, truncated = _walk_signatures(
        baseline.root, ignore_names=ignore_names, limit=limit
    )
    changed = [
        path
        for path, signature in current.items()
        if baseline.signatures.get(path) != signature
    ]
    removed = [path for path in baseline.signatures if path not in current]
    return TurnFileDiff(changed=changed, removed=removed, truncated=truncated)


def _apply_turn_diff(
    idx: AgentFileIndex,
    prior: dict[str, IndexEntry],
    diff: TurnFileDiff,
    *,
    snapshots: SnapshotStore,
    root: Path,
) -> dict[str, Any]:
    """把一次 turn 差量落到索引账本：changed 读盘入 blob + upsert，removed 记删除。

    旧 ``sync_index_from_turn_diff`` 与 v4 ``sync_index_from_ledger`` 共用本段，
    保证两条发现路径（全树 walk / git 增量）的落账语义完全一致。
    """
    upserted = 0
    failed: list[str] = []
    for rel in diff.changed:
        full = root / rel
        try:
            data = full.read_bytes()
            stat = full.lstat()
        except OSError:
            failed.append(rel)
            continue
        manifest = snapshots.put_bytes(data, source_path=rel)
        if manifest is None:
            # rewind 记录被禁用：差量放弃（不产生半状态索引）
            failed.append(rel)
            continue
        idx.upsert(
            rel,
            content_hash=manifest.content_hash,
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            source="turn_diff",
        )
        upserted += 1
    removed = 0
    for rel in diff.removed:
        prior_entry = prior.get(rel)
        idx.upsert(rel, content_hash=None, size=0, mtime_ns=0, source="turn_diff")
        if prior_entry is not None and prior_entry.content_hash:
            removed += 1
    before_missing = [
        rel for rel in diff.changed if rel not in prior or not prior[rel].content_hash
    ]
    return {
        "upserted": upserted,
        "removed": removed,
        "failed": failed,
        "before_missing": before_missing,
        "truncated": diff.truncated,
    }


def _signature_reference(prior: dict[str, IndexEntry]) -> dict[str, tuple[int, int]]:
    """索引账本 → 签名参考集（v4 对账用；账本即基线，无需 turn 起始全树扫描）。"""
    return {
        path: (entry.size, entry.mtime_ns)
        for path, entry in prior.items()
        if entry.content_hash
    }


def _git_status_changes(
    workspace_root: Path,
) -> tuple[set[str], set[str]] | None:
    """git 增量发现：workspace_root 本身是 git worktree 顶层时，用
    ``git status --porcelain -z`` 找出相对根的 changed/removed 路径。

    语义对齐 v3 全树 walk 的忽略范围：
    - status 只报「git 认识的」变化（tracked 修改/删除 + 未忽略的 untracked）；
    - 用户 .gitignore 掉、但 XEYO 账本已跟踪的路径不会出现在 status 里，
      由调用方对账本补 lstat（见 ``sync_index_from_ledger``）——不丢账本语义。
    任何失败（非 git 仓库 / git 缺失 / 子目录非顶层）返回 None → walk 兜底。
    """
    import subprocess

    root = Path(workspace_root)
    try:
        top = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
        )
        if top.returncode != 0:
            return None
        toplevel = Path(top.stdout.decode("utf-8", "surrogateescape").strip())
        if toplevel != root.resolve():
            # workspace_root 是仓库子目录：status 路径相对仓库根，无法直接映射 →
            # 不冒险，走 walk 兜底。
            return None
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v1",
                "-z",
                "--no-renames",
                "--untracked-files=all",
            ],
            capture_output=True,
        )
    except (OSError, ValueError):
        return None
    if proc.returncode != 0:
        return None
    changed: set[str] = set()
    removed: set[str] = set()
    raw = proc.stdout
    if not raw:
        return changed, removed
    for token in raw.split(b"\0"):
        if len(token) < 3 or token[2:3] != b" ":
            continue
        x = token[0:1]
        y = token[1:2]
        path = token[3:].decode("utf-8", "surrogateescape").replace("\\", "/")
        path = path.strip()
        if not path or path.startswith("../"):
            continue
        if x == b"D" or y == b"D":
            removed.add(path)
        elif token[:2] == b"??" or x in (b"A", b"M", b"T", b"U") or y in (b"A", b"M", b"T", b"U"):
            changed.add(path)
        # R/C 已被 --no-renames 拆成 D + A/??；其余 XY 状态不落账。
    return changed, removed


def sync_index_from_ledger(
    session_id: str,
    *,
    snapshots: SnapshotStore,
    workspace_root: Path | str,
    sessions_dir: Path | None = None,
    index: AgentFileIndex | None = None,
    turn_started_ns: int | None = None,
) -> dict[str, Any]:
    """v4 对账（2026-09-09 v4.2）：回合结束把「本轮真实变化」对进 AgentFileIndex。

    无需回合起始基线，但**只对账真实变化**——基准反证：把账本当基线直接整树
    比对，新会话空账本会把整棵既有工作区当「changed」全量读盘入 blob（6000
    文件 14s）。因此变更候选要过入账闸门才落账：

    - 已在账本（此前被 agent 管理/索引过，``reference`` 含其签名）→ 签名变化
      即同步（覆盖 agent/外部/Bash 的一切后续改动）；
    - 不在账本的新路径 → 仅当 ``turn_started_ns`` 窗口内被写入（mtime_ns >=
      turn_started_ns，None = 不设窗口全收，测试/旧调用用）才读盘入账。
      既有未动用户文件（mtime < turn 起点）永不入账——不炸首回合、不无限膨胀。

    变更发现双路径（都不需要回合起始全树扫描）：
    - git 工作区（workspace_root 即 worktree 顶层）：``git status --porcelain=v1
      -z --no-renames --untracked-files=all``，靠 git 的 index/stat cache；对账本
      补定向 lstat，覆盖被 user gitignore、status 不报的已跟踪路径（不丢语义）。
    - 非 git：单次全树签名 walk 与账本比对。
    walk 超限（truncated）时只同步现存路径变化，不做删除判定（防误墓碑）。

    返回 {"upserted","removed","failed","before_missing","truncated"}。
    """
    root = Path(workspace_root)
    idx = index or AgentFileIndex(session_id, sessions_dir=sessions_dir)
    prior = idx.entries()
    # reference = 账本中「活着」的受管路径签名（content_hash 非空）。
    reference = _signature_reference(prior)
    managed = set(reference)

    changed: set[str] = set()
    removed: set[str] = set()
    truncated = False

    def _new_in_window(rel: str, mtime_ns: int) -> None:
        """不在账本的新路径：回合窗口内被写入才入账（无窗口则全收）。"""
        if rel not in changed and (
            turn_started_ns is None or mtime_ns >= turn_started_ns
        ):
            changed.add(rel)

    git_result = _git_status_changes(root)
    if git_result is not None:
        gchanged, gremoved = git_result
        removed |= gremoved
        for rel in gchanged:
            if rel in managed:
                changed.add(rel)
                continue
            try:
                stat = (root / rel).lstat()
            except OSError:
                continue
            _new_in_window(rel, stat.st_mtime_ns)
        # 账本路径在 git 眼中「已知且未变」或被 user gitignore → status 不报；
        # 定向 lstat：变了进 changed、消失进 removed（语义与 walk 一致）。
        for rel in sorted(managed):
            if rel in changed or rel in removed:
                continue
            try:
                stat = (root / rel).lstat()
            except OSError:
                removed.add(rel)
                continue
            if not stat.st_size and Path(rel).suffix in {".sock", ".pipe"}:
                continue
            if (stat.st_size, stat.st_mtime_ns) != reference[rel]:
                changed.add(rel)
    else:
        current, truncated = _walk_signatures(
            root, ignore_names=None, limit=DEFAULT_TURN_SCAN_LIMIT
        )
        if not truncated:
            removed |= {rel for rel in managed if rel not in current}
        for rel, (size, mtime_ns) in current.items():
            if rel in managed:
                if reference[rel] != (size, mtime_ns):
                    changed.add(rel)
            else:
                _new_in_window(rel, mtime_ns)
    diff = TurnFileDiff(changed=sorted(changed), removed=sorted(removed), truncated=truncated)
    return _apply_turn_diff(idx, prior, diff, snapshots=snapshots, root=root)


def sync_index_from_turn_diff(
    session_id: str,
    baseline: TurnBaseline,
    *,
    snapshots: SnapshotStore,
    workspace_root: Path | str | None = None,
    sessions_dir: Path | None = None,
    index: AgentFileIndex | None = None,
) -> dict[str, Any]:
    """turn 结束调用：变化路径读盘入 blobs 并 upsert 索引；消失路径记删除标记。

    返回 ``{"upserted", "removed", "failed", "before_missing"}``。
    ``before_missing`` = turn 中首次被触及、索引中无 before blob 的路径
    （file tool 已通过 record_file_mutation 记录 before；此处的差量兜底
    无法为其补 before，恢复时该路径会被标记为不可完全回滚）。
    """
    root = Path(workspace_root) if workspace_root is not None else baseline.root
    idx = index or AgentFileIndex(session_id, sessions_dir=sessions_dir)
    prior = idx.entries()
    diff = diff_turn_changes(baseline)
    return _apply_turn_diff(idx, prior, diff, snapshots=snapshots, root=root)
