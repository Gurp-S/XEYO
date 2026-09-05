"""Blob GC · 全局可达性垃圾回收（设计 §36 §9.1）。

SnapshotStore 目前只增不删：每次 ``record_file_mutation`` / checkpoint 冻结都会把
内容寻址 blob 写进 ``~/.xeyo/snapshots/{sha256}``，但从不回收。本模块给这块
加上**全局可达性**（跨会话引用计数等价判定）的回收：一个 blob 只要仍被任一
「存活的 rewind 记录」引用（``agent_file_index.jsonl`` / ``checkpoints.jsonl`` /
``operations.jsonl`` / ``rewind_events.jsonl`` / ``orphans/*`` 里的
``content_hash``/``before_hash``/``after_hash``），就**绝不删除**。

安全性质（对应设计 §9.1 的「跨会话不误删」）：
- reachable = 上述每个 JSONL 里出现的所有内容哈希（最保守口径）；
- 候选删除 = 快照目录 blob − reachable；
- 仅在 ``max_bytes`` 空间预算**超额**时才按 mtime 最旧优先删除，并受 ``dry_run`` 保护。

默认：
- ``XEYO_BLOB_GC_ENABLED``（默认 0）关；``XEYO_BLOB_GC_DRY_RUN``（默认 1）只报告不删；
- ``XEYO_BLOB_GC_MAX_BYTES`` 预算；``XEYO_BLOB_GC_KEEP_RECENT`` 保留位（为未来
  近 N 检查点/基线/锚点的增量保留策略预留，本轮可达性判定仍全量保守）。

命令行：``python -m rewind.blob_gc``（无参数即 dry-run 报告）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from session.persistence import default_sessions_dir


@dataclass
class BlobEntry:
    """快照目录里的一个 blob 文件。"""

    hash: str
    size: int
    mtime: float


@dataclass
class BlobGcResult:
    """一次 GC 的统计结果（dry-run 不删除）。"""

    snapshot_root: str
    sessions_root: str
    enabled: bool
    dry_run: bool
    total_blobs: int = 0
    total_bytes: int = 0
    reachable: int = 0
    deletable: int = 0
    deletable_bytes: int = 0
    deleted: int = 0
    deleted_bytes: int = 0
    budget_bytes: int | None = None
    over_budget: bool = False
    sessions_scanned: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_root": self.snapshot_root,
            "sessions_root": self.sessions_root,
            "enabled": self.enabled,
            "dry_run": self.dry_run,
            "total_blobs": self.total_blobs,
            "total_bytes": self.total_bytes,
            "reachable": self.reachable,
            "deletable": self.deletable,
            "deletable_bytes": self.deletable_bytes,
            "deleted": self.deleted,
            "deleted_bytes": self.deleted_bytes,
            "budget_bytes": self.budget_bytes,
            "over_budget": self.over_budget,
            "sessions_scanned": self.sessions_scanned,
            "errors": self.errors,
        }


# --------------------------------------------------------------------------- #
# 路径与配置
# --------------------------------------------------------------------------- #

def snapshot_root() -> Path:
    """sha 快照目录（与 SnapshotStore 默认一致，可被 XEYO_SNAPSHOTS_DIR 覆盖）。"""
    override = os.environ.get("XEYO_SNAPSHOTS_DIR", "").strip()
    return (Path(override).expanduser() if override else Path.home() / ".xeyo" / "snapshots")


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _int_env(name: str, default: int | None) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# --------------------------------------------------------------------------- #
# 持久化配置（设置项下发通道，设计 §36 §9.1）
# --------------------------------------------------------------------------- #

def rewind_gc_config_path() -> Path:
    """GC 配置持久化位置：默认 ``~/.xeyo/rewind_gc.json``，可用 ``XEYO_REWIND_GC_CONFIG`` 覆盖。"""
    override = os.environ.get("XEYO_REWIND_GC_CONFIG", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".xeyo" / "rewind_gc.json"


def read_rewind_gc_config() -> dict[str, int | None]:
    """读取持久化的 GC 配置（keep_recent / max_bytes），缺失或损坏返回空默认。"""
    path = rewind_gc_config_path()
    if not path.is_file():
        return {"keep_recent": None, "max_bytes": None}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"keep_recent": None, "max_bytes": None}
    if not isinstance(raw, dict):
        return {"keep_recent": None, "max_bytes": None}

    def _as_int(value: Any) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    return {
        "keep_recent": _as_int(raw.get("keep_recent")),
        "max_bytes": _as_int(raw.get("max_bytes")),
    }


def write_rewind_gc_config(
    *,
    keep_recent: int | None,
    max_bytes: int | None,
) -> dict[str, int | None]:
    """原子写入持久化配置，供控制端点 / 设置项调用；返回写后配置。"""
    path = rewind_gc_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"keep_recent": keep_recent, "max_bytes": max_bytes}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return read_rewind_gc_config()


# --------------------------------------------------------------------------- #
# JSONL 读取
# --------------------------------------------------------------------------- #

def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """尽量容错地读一个 JSONL：坏行跳过，返回 dict。"""
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    yield value
    except OSError:
        return


# --------------------------------------------------------------------------- #
# 可达性收集
# --------------------------------------------------------------------------- #

def _is_sha256(s: str) -> bool:
    return len(s) == 64 and all(ch in "0123456789abcdef" for ch in s.lower())


def _collect_hashes(obj: Any, out: set[str]) -> None:
    """递归收集 dict 里出现的 blob 哈希。

    明确键（``content_hash``/``before_hash``/``after_hash``）+ 兜底：任何形如 sha256 的
    字符串都视为可达。宁可过度保留（只少删），绝不漏判（防误删破坏恢复）。
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in ("content_hash", "before_hash", "after_hash") and isinstance(value, str):
                if value.strip():
                    out.add(value.strip())
            else:
                _collect_hashes(value, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_hashes(item, out)
    elif isinstance(obj, str) and _is_sha256(obj):
        out.add(obj)


def _collect_checkpoint_entries(row: dict[str, Any], out: set[str]) -> None:
    """提取 checkpoint 行 ``entries`` 里的内容哈希（``[[path, hash], ...]`` 或 ``{path: hash}``）。

    ``_collect_hashes`` 只识别 ``content_hash`` 似的键值，而 ``freeze_checkpoint`` 把 entries
    写成了 ``sorted(entries.items())`` 的 ``[path, hash]`` 对，因此必须显式抽取，否则检查点
    引用的 blob 会被误判为不可达（破坏恢复）。
    """
    entries = row.get("entries")
    if isinstance(entries, dict):
        for value in entries.values():
            if isinstance(value, str) and value.strip():
                out.add(value.strip())
    elif isinstance(entries, list):
        for pair in entries:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2 and isinstance(pair[1], str):
                if pair[1].strip():
                    out.add(pair[1].strip())


def retained_checkpoint_ids(session_dir: Path, keep_recent: int) -> set[str]:
    """某会话的「保留检查点」集合：最近 ``keep_recent`` 个 + 基线(最早) + 锚点(anchor=true)。

    用于保留性剪枝：只有这些检查点计为可达；其余检查点专属引用成为剪枝候选。
    - 基线 = 会话最早冻结的检查点（ts 最小）。
    - 锚点 = 行中带 ``"anchor": true``（前向兼容；现阶段无写入方）。
    """
    cps: dict[str, tuple[float, bool]] = {}  # cp_id -> (latest_ts, anchor)
    for row in _iter_jsonl(session_dir / "checkpoints.jsonl"):
        cid = str(row.get("checkpoint_id") or "")
        if not cid:
            continue
        ts = float(row.get("ts") or 0.0)
        anchor = bool(row.get("anchor") is True or row.get("metadata", {}).get("anchor") is True)
        prev = cps.get(cid)
        if prev is None or ts > prev[0]:
            cps[cid] = (ts, anchor or bool(prev and prev[1]))
    if not cps:
        return set()
    ordered = sorted(cps.items(), key=lambda kv: (kv[1][0], kv[0]))
    ids = {cid for cid, (_ts, anchor) in ordered if anchor}  # 锚点全部保留
    # 基线：最早一个
    ids.add(ordered[0][0])
    # 最近 N 个
    for cid, _ in ordered[-keep_recent:]:
        ids.add(cid)
    return ids


def retained_turn_ids(
    session_dir: Path,
    keep_recent: int,
) -> tuple[set[str], set[str]]:
    """某会话的「保留 turn / user 消息」集：最近 ``keep_recent`` 个 + 基线 + 锚点 turn。

    返回 ``(turn_id 集, user_message_id 集)``。turn 级剪枝据此老化 operations 与
    checkpoints：只有保留 turn 内的操作/检查点才计为可达。
    - 锚点 turn = 其 user 消息在 checkpoints.jsonl 里带 ``anchor: true`` 的 turn。
    - 无 turns.jsonl（旧会话/未写 turn）时返回空集，调用方回退到 checkpoint-id 保留。
    """
    turns: list[tuple[str, str, float]] = []  # (turn_id, user_message_id, started_at)
    for row in _iter_jsonl(session_dir / "turns.jsonl"):
        tid = str(row.get("turn_id") or "")
        if not tid:
            continue
        turns.append(
            (tid, str(row.get("user_message_id") or ""), float(row.get("started_at") or 0.0))
        )
    if not turns:
        return set(), set()
    anchor_msgs: set[str] = set()
    for row in _iter_jsonl(session_dir / "checkpoints.jsonl"):
        if row.get("anchor") is True or (isinstance(row.get("metadata"), dict) and row["metadata"].get("anchor") is True):
            mid = str(row.get("user_message_id") or "")
            if mid:
                anchor_msgs.add(mid)
    ordered = sorted(turns, key=lambda t: (t[2], t[0]))
    keep_ids: set[str] = set()
    keep_msgs: set[str] = set()
    # 基线：最早 turn
    base_id, base_mid, _ = ordered[0]
    keep_ids.add(base_id)
    keep_msgs.add(base_mid)
    # 最近 N 个 turn
    for tid, mid, _ in ordered[-keep_recent:]:
        keep_ids.add(tid)
        keep_msgs.add(mid)
    # 锚点 turn：其 user 消息被锚定
    for tid, mid, _ in ordered:
        if mid and mid in anchor_msgs:
            keep_ids.add(tid)
            keep_msgs.add(mid)
    return keep_ids, keep_msgs


def collect_reachable_blobs(
    sessions_root: Path | None = None,
    *,
    keep_recent: int | None = None,
) -> set[str]:
    """跨会话把「仍被任何 rewind 记录引用的 blob 哈希」收集成集合。

    - ``keep_recent`` 为空 → 最保守：任何 rewind 记录引用的都算可达。
    - ``keep_recent`` 给定 → 按「最近 N turn + 基线 + 锚点 turn」划分保留集：
      - operations 只计保留 turn 内（否则按 turn 老化）；
      - checkpoints 只计保留 user 消息（否则按 checkpoint-id 保留）；
      - ``agent_file_index`` / ``rewind_events`` / ``orphans`` 仍**全量**保留（安全兜底）。
    """
    root = sessions_root or default_sessions_dir()
    reachable: set[str] = set()
    orphan_dir_name = "orphans"
    if not root.is_dir():
        return reachable
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        # 撤销/恢复的安全底座：索引与事件全量保留
        for row in _iter_jsonl(child / "agent_file_index.jsonl"):
            _collect_hashes(row, reachable)
        for row in _iter_jsonl(child / "rewind_events.jsonl"):
            _collect_hashes(row, reachable)

        turn_ids: set[str] = set()
        user_msg_ids: set[str] = set()
        if keep_recent is not None and keep_recent > 0:
            turn_ids, user_msg_ids = retained_turn_ids(child, keep_recent)

        # operations：按 turn 老化（无 turn 信息则保守全量）。
        for row in _iter_jsonl(child / "operations.jsonl"):
            if keep_recent is not None and keep_recent > 0 and turn_ids:
                if str(row.get("turn_id") or "") not in turn_ids:
                    continue
            _collect_hashes(row, reachable)

        # checkpoints：按保留 user 消息；无 turn 信息回退 checkpoint-id 保留。
        if keep_recent is not None and keep_recent > 0 and user_msg_ids:
            for row in _iter_jsonl(child / "checkpoints.jsonl"):
                if str(row.get("user_message_id") or "") not in user_msg_ids:
                    continue
                _collect_checkpoint_entries(row, reachable)
                _collect_hashes(row, reachable)
        elif keep_recent is not None and keep_recent > 0:
            retained = retained_checkpoint_ids(child, keep_recent)
            for row in _iter_jsonl(child / "checkpoints.jsonl"):
                if retained and row.get("checkpoint_id") not in retained:
                    continue
                _collect_checkpoint_entries(row, reachable)
                _collect_hashes(row, reachable)
        else:
            for row in _iter_jsonl(child / "checkpoints.jsonl"):
                _collect_checkpoint_entries(row, reachable)
                _collect_hashes(row, reachable)

        orphan_dir = child / orphan_dir_name
        if orphan_dir.is_dir():
            for orphan in orphan_dir.iterdir():
                if not orphan.is_file() or orphan.suffix != ".jsonl":
                    continue
                for row in _iter_jsonl(orphan):
                    _collect_hashes(row, reachable)
    return reachable


# --------------------------------------------------------------------------- #
# blob 列表与删除
# --------------------------------------------------------------------------- #

def list_snapshot_blobs(snapshot_root_path: Path | None = None) -> list[BlobEntry]:
    """列出快照目录里的全部 blob（按 sha256 文件名）。"""
    root = snapshot_root_path or snapshot_root()
    entries: list[BlobEntry] = []
    if not root.is_dir():
        return entries
    for item in root.iterdir():
        if not item.is_file():
            continue
        name = item.name
        # 只认 64 位 sha256 文件名，忽略临时文件（.xxxx.tmp 等）。
        if len(name) != 64 or not all(ch in "0123456789abcdef" for ch in name.lower()):
            continue
        try:
            stat = item.stat()
        except OSError:
            continue
        entries.append(BlobEntry(hash=name, size=stat.st_size, mtime=stat.st_mtime))
    return entries


def _delete_blob(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        # 回收是尽力而为：删除失败不中断整轮 GC，也不影响其它 blob。
        pass


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #

def garbage_collect(
    sessions_root: Path | None = None,
    snapshot_root_path: Path | None = None,
    *,
    enabled: bool | None = None,
    dry_run: bool | None = None,
    max_bytes: int | None = None,
    keep_recent: int | None = None,
) -> BlobGcResult:
    """执行一次 blob GC。

    - ``enabled`` 缺省读 ``XEYO_BLOB_GC_ENABLED``；关闭则只返回报告、不删除。
    - ``dry_run`` 缺省读 ``XEYO_BLOB_GC_DRY_RUN``（默认 1）。
    - ``max_bytes`` 缺省读 ``XEYO_BLOB_GC_MAX_BYTES``；只有快照目录**总占用超过预算**
      时，才按 mtime 最旧优先删除**不可达** blob，直到回到预算内或删无可删。
    - ``keep_recent`` 缺省读 ``XEYO_BLOB_GC_KEEP_RECENT``；给定后检查点引用只计「保留检查点」
      （近 N + 基线 + 锚点），其余检查点专属引用成为剪枝候选（operations/index/orphans 仍全量保留）。
    """
    root = snapshot_root_path or snapshot_root()
    sroot = sessions_root or default_sessions_dir()
    en = _flag("XEYO_BLOB_GC_ENABLED", default=False) if enabled is None else bool(enabled)
    dr = _flag("XEYO_BLOB_GC_DRY_RUN", default=True) if dry_run is None else bool(dry_run)
    cfg = read_rewind_gc_config()
    default_budget = cfg.get("max_bytes")
    if default_budget is None:
        default_budget = _int_env("XEYO_BLOB_GC_MAX_BYTES", None)
    budget = max_bytes if max_bytes is not None else default_budget
    default_keep = cfg.get("keep_recent")
    if default_keep is None:
        default_keep = _int_env("XEYO_BLOB_GC_KEEP_RECENT", None)
    keep = keep_recent if keep_recent is not None else default_keep
    result = BlobGcResult(
        snapshot_root=str(root),
        sessions_root=str(sroot),
        enabled=en,
        dry_run=dr,
        budget_bytes=budget,
        reachable=0,
    )

    blobs = list_snapshot_blobs(root)
    result.total_blobs = len(blobs)
    result.total_bytes = sum(item.size for item in blobs)

    reachable = collect_reachable_blobs(sroot, keep_recent=keep)
    result.reachable = len(reachable)

    # 不可达 = 快照里存在、但没有任何 rewind 记录引用（如已删除/过期会话的残留）。
    deletable = [item for item in blobs if item.hash not in reachable]
    deletable.sort(key=lambda item: (item.mtime, item.hash))
    result.deletable = len(deletable)
    result.deletable_bytes = sum(item.size for item in deletable)

    result.over_budget = bool(budget is not None and result.total_bytes > budget)

    # 只有「真的启用」才可能删除；dry-run 永远只报告。
    if not en:
        return result
    # 只有**确实超出预算**才动手；否则即便有不可达 blob 也不清理（保守，防误删）。
    if budget is None or budget <= 0 or result.total_bytes <= budget:
        return result
    # dry_run=True：deletable/over_budget 已在 result 中（报告面），不计 deleted、
    # 绝不触盘（曾经漏判 dr 导致真删——test_dry_run_and_disabled_never_delete 钉死）。
    if dr:
        return result

    # 按 mtime 最旧优先删除不可达 blob，直到回到预算内（此处必为 apply 模式）。
    need_to_free = result.total_bytes - budget
    freed = 0
    freed_bytes = 0
    for item in deletable:
        if freed_bytes >= need_to_free:
            break
        _delete_blob(root / item.hash)
        freed += 1
        freed_bytes += item.size
    result.deleted = freed
    result.deleted_bytes = freed_bytes
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Blob GC · 全局可达性回收")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正删除（默认 dry-run 只报告）",
    )
    parser.add_argument("--max-bytes", type=int, default=None, help="空间预算（字节）")
    parser.add_argument("--sessions-dir", default=None, help="会话根目录覆盖")
    parser.add_argument("--snapshots-dir", default=None, help="快照根目录覆盖")
    args = parser.parse_args()

    result = garbage_collect(
        sessions_root=Path(args.sessions_dir) if args.sessions_dir else None,
        snapshot_root_path=Path(args.snapshots_dir) if args.snapshots_dir else None,
        dry_run=not args.apply,
        max_bytes=args.max_bytes,
    )
    import json as _json

    print(_json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

__all__ = [
    "BlobEntry",
    "BlobGcResult",
    "collect_reachable_blobs",
    "garbage_collect",
    "list_snapshot_blobs",
    "read_rewind_gc_config",
    "retained_checkpoint_ids",
    "retained_turn_ids",
    "rewind_gc_config_path",
    "snapshot_root",
    "write_rewind_gc_config",
]
