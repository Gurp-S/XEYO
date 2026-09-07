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
        content_hash = manifest.content_hash
        idx.upsert(
            rel,
            content_hash=content_hash,
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            source="turn_diff",
        )
        upserted += 1
    removed = 0
    for rel in diff.removed:
        prior_entry = prior.get(rel)
        idx.upsert(
            rel,
            content_hash=None,
            size=0,
            mtime_ns=0,
            source="turn_diff",
        )
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
