"""共享变更日志（journal）：append-only 变更记录 + 按路径索引 + 最近变更查询 + 垃圾回收。

用途：给"同一个 workspace 里的多个 agent"可见性（解决"瞎"），也作为 P1
测量（碰撞/语法错误率）与 P2 交接/新闻的数据源。

设计（见 docs/实施计划/29-普通多Agent协同落地实施计划书.md §2.2 / §6）：
- append-only、每行一条 JSON；跨进程刷新（interleave 顺序）可接受。
- 正确性命中"每文件"；另打一个**全局单调 seq** 供审计/追溯（C6）。
- 记录 `syntax_valid`（A5/B4/C3）与碰撞标记（C5）。

生产化（本骨架已补全，见 §锁 / §索引）：
- **锁**：进程内用每文件 ``threading.RLock`` 保护「分配 seq + 写行 + fsync」；
  跨进程默认依赖 ``O_APPEND`` 单次追加原子性。如需强互斥，传给
  ``record_change(..., workspace_lock=WorkspaceLock(...))`` 即可（可选 B）。
- **索引**：写 journal 行后同步追加一条**每路径**的倒排 marker
  （``{workspace_id}.index.jsonl``，append-only）。查询优先走索引（仅在
  索引 watermark 覆盖到 journal 尾时才用它），否则回退全量扫描 —— 索引
  永远是"可重建的缓存"，journal 是唯一事实源，绝不返回错结果。
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass
class ChangeRecord:
    """一条变更记录（每文件单写者写入后追加）。"""
    seq: int                    # 全局单调序号（journal 内部分配，供审计/追溯）
    agent_id: str
    path: str
    action: str                 # "edit" | "write"
    file_hash_after: str        # sha256:...（写入后内容哈希）
    ts: float
    brief: str = ""             # 短说明（可选）
    syntax_valid: bool = True   # 写后语法校验结果（A5/B4/C3）
    conflict_task: bool = False # 该次是否曾触发 StaleConflict（C5）
    diff: str = ""              # 本次变更的 unified diff（改前 vs 改后快照；旧记录为空）
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 进程内每文件锁（与 rewind/index.py 同构：append + fsync 崩溃顺序合同）
# ---------------------------------------------------------------------------
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
    """加锁追加一行 JSONL 并 fsync；崩溃后顺序一致、无半行。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    with _lock_for(path):
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


def _read_rows(path: Path) -> list[dict[str, Any]]:
    """加锁读全区行；坏行 / 非 dict 跳过。"""
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with _lock_for(path):
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
def _journal_root() -> Path:
    return Path.home() / ".xeyo" / "journal"


def _changes_path(workspace_id: str) -> Path:
    """变更日志文件路径。"""
    return _journal_root() / f"{workspace_id}.jsonl"


def _index_path(workspace_id: str) -> Path:
    """每路径倒排索引文件路径（append-only，派生缓存）。

    由 journal 路径派生（同目录、同名加 ``.index``）；这样测试 monkeypatch
    ``_changes_path`` 后索引也会落在同一临时目录，不污染用户 home。
    """
    changes = _changes_path(workspace_id)
    return changes.parent / f"{changes.stem}.index.jsonl"


# ---------------------------------------------------------------------------
# seq 分配
# ---------------------------------------------------------------------------
def _tail_seq(path: Path) -> int:
    """基于最近一条的 seq +1；空/坏文件则 1。"""
    if not path.is_file() or path.stat().st_size == 0:
        return 1
    with _lock_for(path):
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            last = None
            for line in handle:
                last = line
    if not last:
        return 1
    try:
        return int(json.loads(last).get("seq", 0)) + 1
    except (json.JSONDecodeError, TypeError, ValueError):
        return 1


# ---------------------------------------------------------------------------
# record_change：写 journal + 同步写索引（同锁内 append+fsync）
# ---------------------------------------------------------------------------
def record_change(
    workspace_id: str,
    rec: ChangeRecord,
    *,
    workspace_lock: Any | None = None,
) -> int:
    """追加一条变更记录，返回分配的全局 seq。

    - 默认：进程内每文件锁（保证同进程内 seq 单调、不重复）。
    - 传 ``workspace_lock``（如 ``engine.workspace_lock.WorkspaceLock`` 的
      ``hold`` 上下文管理器）时给整个 journal+index 写入套上**跨进程强互斥**
      （可选 B：写者在多进程竞争下得到绝对单调 seq）。
    """
    path = _changes_path(workspace_id)

    if workspace_lock is not None:
        with workspace_lock:  # type: ignore[attr-defined]
            return _record_change_locked(workspace_id, rec, path)

    # 跨进程依赖 O_APPEND 单次追加的原子性；同进程内仍加锁。
    with _lock_for(path):
        return _record_change_locked(workspace_id, rec, path)


def _record_change_locked(workspace_id: str, rec: ChangeRecord, path: Path) -> int:
    rec.seq = _tail_seq(path)
    row = _to_dict(rec)
    _append_row(path, row)
    _append_row(_index_path(workspace_id), _index_marker(row))
    return rec.seq


def _index_marker(row: dict[str, Any]) -> dict[str, Any]:
    """索引行 = journal 行的紧凑副本（保留全部字段以便脱离 journal 物化）。"""
    return dict(row)


# ---------------------------------------------------------------------------
# 索引读取 / 重建 / 新鲜度
# ---------------------------------------------------------------------------
def _index_watermark(rows: list[dict[str, Any]]) -> int:
    wm = 0
    for row in rows:
        try:
            wm = max(wm, int(row.get("seq") or 0))
        except (TypeError, ValueError):
            continue
    return wm


def _read_index(workspace_id: str) -> tuple[int, dict[str, list[dict[str, Any]]]]:
    """返回 (watermark, path -> [rows])；不存在则 watermark=0、空 map。"""
    rows = _read_rows(_index_path(workspace_id))
    watermark = _index_watermark(rows)
    by_path: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get("path") or "")
        if key:
            by_path.setdefault(key, []).append(row)
    return watermark, by_path


def _journal_fresh(workspace_id: str, journal: Path) -> bool:
    """索引是否覆盖到 journal 尾（watermark >= journal 最后 seq）。"""
    if not _index_path(workspace_id).is_file():
        return False
    watermark, _ = _read_index(workspace_id)
    if watermark <= 0:
        return False
    return watermark >= _tail_seq(journal)


def rebuild_index(workspace_id: str) -> int:
    """从 journal 全量重建索引（gc 后 / 索引损坏 / 降级恢复时调用）。

    返回重建的索引行数。journal 仍是唯一事实源；本函数只让索引回到新鲜状态。
    """
    journal = _changes_path(workspace_id)
    rows = _read_rows(journal)
    index = _index_path(workspace_id)
    # 重写（append-only 语义在重建时临时放宽，属运维/恢复操作）
    with _lock_for(index):
        index.parent.mkdir(parents=True, exist_ok=True)
        tmp = index.with_name(index.name + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(
                    json.dumps(_index_marker(row), ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, index)
    return len(rows)


# ---------------------------------------------------------------------------
# 路径前缀匹配（保留原名，供 tests / 兼容）
# ---------------------------------------------------------------------------
def _path_matches_prefix(
    path: str,
    prefix: str,
    *,
    workspace_root: str | None = None,
) -> bool:
    """相对/绝对路径统一后再做前缀匹配（避免 journal 绝对路径 vs scope 相对路径对不上）。"""
    pref = (prefix or "").replace("\\", "/").strip()
    if not pref:
        return True
    p = (path or "").replace("\\", "/").strip()
    if not p:
        return False
    pref_l = pref.lower()
    p_l = p.lower()
    if p_l.startswith(pref_l):
        return True
    if workspace_root:
        root = str(Path(workspace_root).expanduser().resolve()).replace("\\", "/").lower().rstrip("/")
        rel_pref = pref_l
        while rel_pref.startswith("./"):
            rel_pref = rel_pref[2:]
        if not pref_l.startswith(root):
            abs_pref = f"{root}/{rel_pref}".replace("//", "/")
            if p_l.startswith(abs_pref):
                return True
        if p_l.startswith(root + "/"):
            rel_path = p_l[len(root) + 1:]
            if rel_path.startswith(rel_pref):
                return True
    # 后缀兜底：…/src/foo.ts vs src/foo.ts
    return p_l.endswith("/" + pref_l.lstrip("./")) or p_l.endswith(pref_l)


# ---------------------------------------------------------------------------
# 查询：优先索引，新鲜度不足回退全量扫描（绝不给错结果）
# ---------------------------------------------------------------------------
def recent_changes(
    workspace_id: str,
    *,
    path_prefix: str | None = None,
    since_ts: float | None = None,
    agent_id: str | None = None,
    limit: int = 20,
    workspace_root: str | None = None,
) -> list[ChangeRecord]:
    """最近 N 条变更（按写入顺序）；可选按路径前缀 / since_ts / agent_id 过滤。

    索引新鲜时只遍历命中的路径；否则回退整文件扫描（正确、不变慢多少）。
    """
    path = _changes_path(workspace_id)
    if not path.is_file():
        return []

    if _journal_fresh(workspace_id, path):
        _, by_path = _read_index(workspace_id)
        want_agent = (agent_id or "").strip() or None
        out: list[ChangeRecord] = []
        for rec_path, rows in by_path.items():
            if path_prefix and not _path_matches_prefix(
                rec_path, path_prefix, workspace_root=workspace_root
            ):
                continue
            for row in rows:
                record = _record_from_index(row)
                if record is None:
                    continue
                if since_ts is not None and record.ts < since_ts:
                    continue
                if want_agent is not None and (record.agent_id or "") != want_agent:
                    continue
                out.append(record)
        # 索引行与 journal 行同序追加，天然按 seq 升序；取最近 limit 条
        out.sort(key=lambda r: r.seq)
        return out[-limit:]

    # 回退：全量扫描（原逻辑）
    want_agent = (agent_id or "").strip() or None
    out: list[ChangeRecord] = []
    with _lock_for(path):
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = _from_dict(json.loads(line))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                if since_ts is not None and rec.ts < since_ts:
                    continue
                if want_agent is not None and (rec.agent_id or "") != want_agent:
                    continue
                if path_prefix and not _path_matches_prefix(
                    rec.path, path_prefix, workspace_root=workspace_root
                ):
                    continue
                out.append(rec)
    return out[-limit:]


def _record_from_index(row: dict[str, Any]) -> ChangeRecord | None:
    try:
        return _from_dict(row)
    except (TypeError, ValueError, KeyError):
        return None


def format_changes_for_agent(records: Iterable[ChangeRecord]) -> str:
	"""把 recent_changes 格式化为子 agent 写前注入块（Patch 重试 / 防「瞎」）。"""
	rows = list(records)
	if not rows:
		return ""
	lines = [
		"## Recent workspace changes (read the latest file before editing)",
	]
	for rec in rows:
		stale = " [stale conflict]" if rec.conflict_task else ""
		brief = f" — {rec.brief}" if rec.brief else ""
		lines.append(
			f"- `{rec.path}` by {rec.agent_id or '?'} ({rec.action}){brief}{stale}"
		)
	return "\n".join(lines)


def gc(workspace_id: str, *, ttl_seconds: float = 7 * 24 * 3600) -> int:
    """清理超过 TTL 的日志；返回删除条数。P1 离线分析器运行前调用（B6/C9）。

    清理后同步重建索引，让索引与 journal 一致（append-only 语义在清理时临时放宽，
    属运维操作）。
    """
    path = _changes_path(workspace_id)
    if not path.is_file():
        return 0
    now = _now()
    keep: list[str] = []
    removed = 0
    with _lock_for(path):
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = _from_dict(json.loads(line))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                if (now - rec.ts) > ttl_seconds:
                    removed += 1
                else:
                    keep.append(line)
        # 重写为仅保留的条目（append-only 语义在清理时临时放宽，属运维操作）
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            for line in keep:
                handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    # 让索引与裁剪后的 journal 对齐
    try:
        rebuild_index(workspace_id)
    except OSError:
        pass
    return removed


def _now() -> float:
    import time
    return round(time.time(), 3)


def _to_dict(rec: ChangeRecord) -> dict[str, Any]:
    return {
        "seq": int(rec.seq),
        "agent_id": str(rec.agent_id),
        "path": str(rec.path),
        "action": str(rec.action),
        "file_hash_after": str(rec.file_hash_after),
        "ts": float(rec.ts),
        "brief": str(rec.brief),
        "syntax_valid": bool(rec.syntax_valid),
        "conflict_task": bool(rec.conflict_task),
        "diff": str(rec.diff),
        "metadata": rec.metadata,
    }


def _from_dict(raw: dict[str, Any]) -> ChangeRecord:
    return ChangeRecord(
        seq=int(raw.get("seq", 0)),
        agent_id=str(raw.get("agent_id") or ""),
        path=str(raw.get("path") or ""),
        action=str(raw.get("action") or "edit"),
        file_hash_after=str(raw.get("file_hash_after") or ""),
        ts=float(raw.get("ts", 0)),
        brief=str(raw.get("brief") or ""),
        syntax_valid=bool(raw.get("syntax_valid", True)),
        conflict_task=bool(raw.get("conflict_task", False)),
        diff=str(raw.get("diff") or ""),
        metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    )
