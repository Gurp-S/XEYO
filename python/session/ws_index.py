"""会话 → 工作区落盘索引：跨 session 共享记忆的归属映射。

transcript / session.md 都按 session_id 落盘，但磁盘上没有「这条会话属于
哪个 workspace」的记录 —— 导致跨会话搜索（memory.search.search_session_notes）
只能靠进程内 presence 表，服务重启后旧对话就找不到了。

本模块在 ``~/.xeyo/sessions/_workspace_index.jsonl`` 追加
``{"session_id", "workspace_id", "ts"}`` 行（append-only，同会话同工作区
幂等不重复写），读取时取每个会话最后一条记录。坏行跳过；任何 I/O 失败
都静默降级为「查不到」，绝不阻断会话启动。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

_logger = logging.getLogger(__name__)

# 进程内缓存：session_id → workspace_id（与磁盘最新行一致）。
_cache: dict[str, str] = {}
_loaded = False


def _sessions_dir() -> Path:
    """与 session.persistence.default_sessions_dir 一致（可用 XEYO_SESSIONS_DIR 覆盖）。"""
    override = os.environ.get("XEYO_SESSIONS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".xeyo" / "sessions"


def index_path() -> Path:
    """workspace 归属索引文件路径。"""
    return _sessions_dir() / "_workspace_index.jsonl"


def _read_all() -> dict[str, str]:
    """读全量索引 → {session_id: workspace_id}（后行覆盖前行）。"""
    path = index_path()
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            sid = str(row.get("session_id") or "").strip()
            wsid = str(row.get("workspace_id") or "").strip()
            if sid and wsid:
                out[sid] = wsid
    except OSError:
        return dict(_cache)
    return out


def _ensure_loaded() -> None:
    global _loaded
    if not _loaded:
        _cache.update(_read_all())
        _loaded = True


def _workspace_id(cwd: str) -> str:
    """memory.memdir.workspace_id 的懒加载包装（避免模块导入环）。"""
    from memory.memdir import workspace_id

    return workspace_id(cwd)


def record_session_workspace(session_id: str, cwd: str) -> None:
    """登记会话归属；同会话同工作区幂等不写盘。失败只记 debug。"""
    sid = (session_id or "").strip()
    if not sid:
        return
    try:
        wsid = _workspace_id(cwd or ".")
    except Exception:  # noqa: BLE001
        return
    _ensure_loaded()
    if _cache.get(sid) == wsid:
        return
    row = json.dumps(
        {"session_id": sid, "workspace_id": wsid, "ts": time.time()},
        ensure_ascii=False,
    )
    path = index_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(row + "\n")
    except OSError:
        _logger.debug("workspace index append failed", exc_info=True)
        return
    _cache[sid] = wsid


def sessions_for_workspace(cwd: str) -> list[str]:
    """返回归属该工作区的全部会话 id（索引序，旧 → 新）。"""
    try:
        wsid = _workspace_id(cwd or ".")
    except Exception:  # noqa: BLE001
        return []
    _ensure_loaded()
    return [sid for sid, w in _cache.items() if w == wsid]


def reset_for_tests() -> None:
    """测试用：清空进程内缓存（XEYO_SESSIONS_DIR 重定向后必须调用）。"""
    global _loaded
    _cache.clear()
    _loaded = False


__all__ = [
    "index_path",
    "record_session_workspace",
    "reset_for_tests",
    "sessions_for_workspace",
]
