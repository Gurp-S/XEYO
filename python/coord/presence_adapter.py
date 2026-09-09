"""FileBackedPresence：session_presence 的文件后端（coord 阶段 0）。

与 ``engine.session_presence.SessionPresenceRegistry`` 方法签名一一对应；
状态操作复用同一 :class:`PresenceState`（逻辑单份），存储分布：

- presence 状态 / 锁：per workspace root（``<ws>/.xeyo/coord/``）；
- session_id -> root 索引：全局（``~/.xeyo/coord/``）——跨 workspace 反查
  drop / queue_notice / take_notices 这类无 cwd 调用。

降级铁律：任何 coord IO/锁失败只记 debug，本进程操作照常语义完成（尽力持久化），
异常绝不外泄到 write_store / policy 等调用方。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from coord.file_store import CoordFileStore, root_hash
from coord.locking import FileGuard
from engine.session_presence import (
    PresenceState,
    SessionPresenceEntry,
    _norm_root,
    _short_id,
)

_log = logging.getLogger("xeyo.coord.presence")


def _coord_home() -> Path:
    """全局 coord 目录（索引所在）：XEYO_HOME 显式覆盖 > memory.instruction.xeyo_home > ~/.xeyo。"""
    env = os.environ.get("XEYO_HOME", "").strip()
    if env:
        return Path(env)
    try:
        from memory.instruction import xeyo_home

        return Path(xeyo_home())
    except Exception:  # noqa: BLE001
        return Path.home() / ".xeyo"


class FileBackedPresence:
    """session_presence 的跨进程文件后端。"""

    def __init__(self) -> None:
        # 全局 store：仅承载 sid -> root 索引（跨 workspace 反查）。
        self._global = CoordFileStore(_coord_home())

    # -- 内部 ---------------------------------------------------------------

    def _store_for(self, root: str | Path) -> CoordFileStore:
        """per-workspace 状态仓（presence 状态 / scope / tasks / locks）。"""
        return CoordFileStore(root)

    def _h(self, root: str | Path) -> str:
        return root_hash(root)

    def knows_session(self, session_id: str) -> bool:
        try:
            return self._global.root_of_session(session_id) is not None
        except Exception:  # noqa: BLE001
            return False

    def _mutate(self, root: str, session_id: str, mutate) -> None:
        """写路径：per-root 锁 → load → 变更 → 全局索引登记 → save。失败降级。"""
        h = self._h(root)
        try:
            store = self._store_for(root)
            with FileGuard(store.coord_dir / "locks" / f"presence-{h}.lock") as ok:
                raw = store.load_presence(root) or {}
                state = PresenceState.from_dict(raw)
                mutate(state)
                if ok:
                    self._global.note_session_root(session_id, root)
                    store.save_presence(root, state.to_dict())
        except Exception:  # noqa: BLE001
            _log.debug("presence mutate failed (root=%s)", h, exc_info=True)

    def _take(self, root: str, session_id: str) -> list[str]:
        """drain 专用：锁内 load → take → save。

        take_notices 是消费语义，清空结果必须落盘，否则通知永不消失；
        锁未到手时不 save（通知留在文件等下次取，宁迟不丢），返回空。
        """
        h = self._h(root)
        try:
            store = self._store_for(root)
            taken: list[str] = []
            with FileGuard(store.coord_dir / "locks" / f"presence-{h}.lock") as ok:
                raw = store.load_presence(root) or {}
                state = PresenceState.from_dict(raw)
                taken = state.take_notices(session_id) or []
                if not ok:
                    taken = []
                else:
                    store.save_presence(root, state.to_dict())
            return taken
        except Exception:  # noqa: BLE001
            _log.debug("presence take failed (root=%s)", h, exc_info=True)
            return []

    def _read(self, root: str, read):
        """读路径：load → 只读操作。失败返回安全空值。"""
        h = self._h(root)
        try:
            store = self._store_for(root)
            raw = store.load_presence(root) or {}
            state = PresenceState.from_dict(raw)
            return read(state)
        except Exception:  # noqa: BLE001
            _log.debug("presence read failed (root=%s)", h, exc_info=True)
            return None

    # -- 带 cwd 方法 --------------------------------------------------------

    def touch_busy(self, cwd: str, session_id: str, *, busy: bool, title: str = "") -> None:
        root = _norm_root(cwd)

        def op(st: PresenceState) -> None:
            st.touch_busy(cwd, session_id, busy=busy, title=title)

        self._mutate(root, session_id, op)

    def note_write(self, cwd: str, session_id: str, path: str, *, title: str = "") -> None:
        root = _norm_root(cwd)

        def op(st: PresenceState) -> None:
            st.note_write(cwd, session_id, path, title=title)

        self._mutate(root, session_id, op)

    def note_git(self, cwd: str, session_id: str, op: str | None, *, title: str = "") -> None:
        root = _norm_root(cwd)

        def op(st: PresenceState) -> None:
            st.note_git(cwd, session_id, op, title=title)

        self._mutate(root, session_id, op)

    def note_tool(self, cwd: str, session_id: str, tool_name: str, *, title: str = "") -> None:
        root = _norm_root(cwd)

        def op(st: PresenceState) -> None:
            st.note_tool(cwd, session_id, tool_name, title=title)

        self._mutate(root, session_id, op)

    def note_todos(self, cwd: str, session_id: str, todos: list[str], *, title: str = "") -> None:
        root = _norm_root(cwd)

        def op(st: PresenceState) -> None:
            st.note_todos(cwd, session_id, todos, title=title)

        self._mutate(root, session_id, op)

    def set_title(self, cwd: str, session_id: str, title: str) -> None:
        root = _norm_root(cwd)

        def op(st: PresenceState) -> None:
            st.set_title(cwd, session_id, title)

        self._mutate(root, session_id, op)

    def clear_owned(self, cwd: str, session_id: str, paths: list[str] | None = None) -> None:
        root = _norm_root(cwd)

        def op(st: PresenceState) -> None:
            st.clear_owned(cwd, session_id, paths)

        self._mutate(root, session_id, op)

    def peers(self, cwd: str, self_id: str) -> list[SessionPresenceEntry]:
        root = _norm_root(cwd)
        out = self._read(root, lambda st: st.peers(cwd, self_id))
        return out or []

    def self_entry(self, cwd: str, session_id: str) -> SessionPresenceEntry | None:
        root = _norm_root(cwd)
        return self._read(root, lambda st: st.self_entry(cwd, session_id))

    def owner_of(self, cwd: str, path: str, *, exclude_session: str = "") -> SessionPresenceEntry | None:
        root = _norm_root(cwd)
        return self._read(
            root, lambda st: st.owner_of(cwd, path, exclude_session=exclude_session)
        )

    def peer_conflict_files(
        self, cwd: str, self_id: str, paths: list[str]
    ) -> dict[str, tuple[str, float]]:
        root = _norm_root(cwd)
        out = self._read(root, lambda st: st.peer_conflict_files(cwd, self_id, paths))
        return out or {}

    def peer_git_conflict(
        self, cwd: str, self_id: str, command: str
    ) -> tuple[str, list[str]] | None:
        root = _norm_root(cwd)
        return self._read(root, lambda st: st.peer_git_conflict(cwd, self_id, command))

    def to_peer_dicts(self, cwd: str, self_id: str = "") -> list[dict[str, Any]]:
        root = _norm_root(cwd)
        out = self._read(root, lambda st: st.to_peer_dicts(cwd, self_id))
        return out or []

    # -- 无 cwd 方法：全局索引反查 ------------------------------------------

    def _root_of(self, session_id: str) -> str | None:
        try:
            return self._global.root_of_session(session_id)
        except Exception:  # noqa: BLE001
            return None

    def drop(self, session_id: str) -> None:
        try:
            root = self._root_of(session_id)
            if root:
                self._store_for(root).remove_session_from_presence(root, session_id)
            self._global.remove_session_root(session_id)
        except Exception:  # noqa: BLE001
            _log.debug("presence drop failed", exc_info=True)

    def queue_notice(self, session_id: str, text: str) -> None:
        root = self._root_of(session_id)
        if root is None:
            return

        def op(st: PresenceState) -> None:
            st.queue_notice(session_id, text)

        self._mutate(root, session_id, op)

    def take_notices(self, session_id: str) -> list[str]:
        root = self._root_of(session_id)
        if root is None:
            return []
        return self._take(root, session_id)

    def display_title(self, session_id: str) -> str:
        root = self._root_of(session_id)
        if root is None:
            return _short_id(session_id)
        out = self._read(root, lambda st: st.display_title(session_id))
        return out if isinstance(out, str) else _short_id(session_id)


__all__ = ["FileBackedPresence"]
