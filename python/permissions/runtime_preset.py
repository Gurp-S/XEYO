"""运行时权限 preset 活状态源（RuntimePresetStore）。

smoke-test #6：会话权限 preset（readonly / workspace-write / full）原先在会话
创建时被 SessionPool pin（T10），之后请求不得改写 —— 导致"权限变更只影响新
会话"。本 store 提供**会话内显式切换**：GUI 通过
``POST /v1/sessions/{sid}/runtime-preset`` 写入活值，
``permissions.policy.session_permission_profile`` 在准入判定时优先读它（优先级：
store 活值 > WorkspaceContext.permission_profile > ""），因此后续轮次/调用按新
preset 判定；首建 pin 仍作为默认值，只有用户显式切换才覆盖。

T10 语义保持不变：未显式切换的会话沿用 pin；显式切换是用户动作，不违反
"请求体不得改写"（与 RuntimeModeStore 同类设计）。
"""

from __future__ import annotations

import threading

from permissions.presets import PERMISSION_PRESETS


class RuntimePresetStore:
    """线程安全的 per-session 活权限 preset。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requested: dict[str, str] = {}

    def set(self, session_id: str, preset: object) -> str | None:
        """写入活 preset；非法返回 None（不写入）。

        注意：presets.normalize_preset 会把未知值回退为默认（workspace-write），
        这里必须用原始名校验 —— 用户打字错误不能静默变成"工作区写"。
        """
        raw = str(preset or "").strip().lower().replace("_", "-")
        if raw not in PERMISSION_PRESETS:
            return None
        with self._lock:
            self._requested[session_id] = raw
        return raw

    def live(self, session_id: str) -> str | None:
        """当前活 preset（未显式切换返回 None）。"""
        return self._requested.get(session_id)

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._requested.pop(session_id, None)


#: 模块级单例（懒加载由 get_runtime_preset_store 返回）。
_store: RuntimePresetStore | None = None
_store_lock = threading.Lock()


def get_runtime_preset_store() -> RuntimePresetStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = RuntimePresetStore()
    return _store
