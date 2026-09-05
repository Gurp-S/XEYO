"""smoke-test #6：运行时权限 preset 活值（RuntimePresetStore + policy 优先读）。"""

from __future__ import annotations

from permissions.policy import session_permission_profile
from permissions.runtime_preset import get_runtime_preset_store
from engine.workspace_context import WorkspaceContext, set_workspace_context


def test_runtime_preset_store_normalizes_and_rejects():
    store = get_runtime_preset_store()
    assert store.set("s1", "readonly") == "readonly"
    assert store.set("s1", "workspace-write") == "workspace-write"
    assert store.set("s1", "full") == "full"
    # 非法/未知回退 workspace-write？normalize 会回退默认，但 PERMISSION_PRESETS 校验拒绝
    assert store.set("s1", "bogus") is None
    assert store.set("s1", "") is None
    assert store.live("s1") == "full"
    store.clear("s1")
    assert store.live("s1") is None


def test_policy_prefers_runtime_preset_over_pin():
    store = get_runtime_preset_store()
    ctx = WorkspaceContext(session_id="s-pin", cwd="/tmp/x", permission_profile="workspace-write")
    set_workspace_context(ctx)
    try:
        # 无活值：沿用 pin
        assert session_permission_profile() == "workspace-write"
        # 显式切换 readonly → 活值优先
        store.set("s-pin", "readonly")
        assert session_permission_profile() == "readonly"
        store.set("s-pin", "full")
        assert session_permission_profile() == "full"
        # 清空活值：回退 pin
        store.clear("s-pin")
        assert session_permission_profile() == "workspace-write"
    finally:
        set_workspace_context(None)
