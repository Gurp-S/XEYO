"""P0b 最小控制路径：``/v1/extensions/settings`` GET/POST + ``/mcp`` 启停/勾选。

- GET：合并视图（home+workspace），loopback 门禁（LAN 拒绝）；
- POST：主开关 / mcp server / skill 启停 → 原子写 + reconcile 活页块（幂等）；
- ``/mcp enable|disable|tool``：push 写盘 + 即时生效语义；
- ``set_mcp_tool_enabled``：mcp.json 声明文件回写（含全量缺省枚举）。

运行：``py -3.11 -m pytest tests/test_extensions_api.py -q``
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from extension.reconcile import consume_reconcile_blocks, reset_reconcile_state
from server.app import app

_LAN = ("203.0.113.7", 55555)


@pytest.fixture(autouse=True)
def _clean_reconcile():
    reset_reconcile_state()
    yield
    reset_reconcile_state()


def test_settings_rejected_from_lan() -> None:
    with TestClient(app, client=_LAN) as c:
        assert c.get("/v1/extensions/settings").status_code == 403
        r = c.post("/v1/extensions/settings", json={})
        assert r.status_code == 403


def test_settings_get_merged_view(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    (ws / ".xeyo").mkdir(parents=True)
    (ws / ".xeyo" / "settings.json").write_text(
        json.dumps({"enabled_extensions": True, "mcp_servers": {"fs": {"enabled": True}}}),
        encoding="utf-8",
    )
    with TestClient(app) as c:
        r = c.get(f"/v1/extensions/settings?workspace={ws}")
        assert r.status_code == 200, r.text
        body = r.json()
    assert body["ok"] is True
    assert body["enabled_extensions"] is True
    assert body["mcp_servers"]["fs"]["enabled"] is True


def test_settings_post_toggles_and_idempotent(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    (ws / ".xeyo").mkdir(parents=True)
    (ws / ".xeyo" / "settings.json").write_text(
        json.dumps({"enabled_extensions": True, "mcp_servers": {"fs": {"enabled": True}}}),
        encoding="utf-8",
    )
    with TestClient(app) as c:
        r = c.post(
            f"/v1/extensions/settings?workspace={ws}",
            json={"mcp_servers": {"fs": {"enabled": False}}, "skills": {"deploy": {"enabled": False}}},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["mcp_servers"]["fs"]["enabled"] is False
        assert body["applied"]["mcp_servers"] == [{"id": "fs", "enabled": False}]
        # 首次变化：恰两块（工具面 + 技能目录）。
        blocks = consume_reconcile_blocks()
        assert len(blocks) == 2
        assert any("# 工具面变更" in b for b in blocks)
        assert any("# 技能目录变更" in b for b in blocks)
        # 同值重复 POST → 幂等（不再发布活页块）。
        r2 = c.post(
            f"/v1/extensions/settings?workspace={ws}",
            json={"mcp_servers": {"fs": {"enabled": False}}},
        )
        assert r2.status_code == 200
    assert consume_reconcile_blocks() == []
    # 落盘校验。
    data = json.loads((ws / ".xeyo" / "settings.json").read_text(encoding="utf-8"))
    assert data["mcp_servers"]["fs"]["enabled"] is False
    assert data["skills"]["deploy"]["enabled"] is False


def test_settings_post_master_switch(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    (ws / ".xeyo").mkdir(parents=True)
    (ws / ".xeyo" / "settings.json").write_text(
        json.dumps({"enabled_extensions": True}), encoding="utf-8"
    )
    with TestClient(app) as c:
        r = c.post(
            f"/v1/extensions/settings?workspace={ws}",
            json={"enabled_extensions": False},
        )
        assert r.status_code == 200
        assert r.json()["enabled_extensions"] is False
    blocks = consume_reconcile_blocks()
    assert len(blocks) == 1 and "主开关" in blocks[0]


def test_set_mcp_tool_enabled_writes_declaration(tmp_path: Path) -> None:
    """单工具勾选写回 mcp.json（enabled_tools 缺省 → 从运行 client 枚举全量）。"""
    ws = tmp_path / "ws"
    (ws / ".xeyo").mkdir(parents=True)
    (ws / ".xeyo" / "settings.json").write_text(
        json.dumps({"enabled_extensions": True, "mcp_servers": {"fs": {"enabled": True}}}),
        encoding="utf-8",
    )
    home = tmp_path / "home"
    home.mkdir()
    import os

    os.environ["XEYO_HOME"] = str(home)
    mp = home / "mcp.json"
    mp.write_text(
        json.dumps({"servers": {"fs": {"command": "node", "args": []}}}), encoding="utf-8"
    )
    # server 未运行 → 全量枚举失败 → 明确报错（不静默写坏白名单）。
    from extension.config import ConfigError
    from extension.mcp_manager import set_mcp_tool_enabled

    with pytest.raises(ConfigError):
        set_mcp_tool_enabled(str(ws), "fs", "read_file", False)
    # 运行中的 client → 枚举全量 → 勾掉 write_file。
    # 注意：set_mcp_tool_enabled 走 get_mcp_manager 单例 → 注入单例。
    class FakeClient:
        def tool_schemas(self):
            return {
                "a": {"name": "read_file", "inputSchema": {}},
                "b": {"name": "write_file", "inputSchema": {}},
            }

    from extension import mcp_manager as mm

    singleton = mm.get_mcp_manager(str(ws))
    entry = mm._ServerRuntime(
        identity="x", client=FakeClient(), runtime=None, spec=None, started=True
    )
    singleton._servers["fs"] = entry
    msg = set_mcp_tool_enabled(str(ws), "fs", "write_file", False)
    assert "取消勾选" in msg
    data = json.loads(mp.read_text(encoding="utf-8"))
    assert data["servers"]["fs"]["enabled_tools"] == ["read_file"]
    # 勾回。
    msg = set_mcp_tool_enabled(str(ws), "fs", "write_file", True)
    assert "已勾选" in msg
    data = json.loads(mp.read_text(encoding="utf-8"))
    assert sorted(data["servers"]["fs"]["enabled_tools"]) == ["read_file", "write_file"]


def test_slash_mcp_enable_disable(tmp_path: Path) -> None:
    from slash.dispatch import DispatchContext, dispatch

    ws = tmp_path / "ws"
    (ws / ".xeyo").mkdir(parents=True)
    (ws / ".xeyo" / "settings.json").write_text(
        json.dumps({"enabled_extensions": True, "mcp_servers": {"fs": {"enabled": True}}}),
        encoding="utf-8",
    )
    ctx = DispatchContext(session_id="s1", workspace=str(ws))
    res = dispatch("/mcp", "disable fs", ctx=ctx)
    assert res.handled and res.result["ok"] is True
    data = json.loads((ws / ".xeyo" / "settings.json").read_text(encoding="utf-8"))
    assert data["mcp_servers"]["fs"]["enabled"] is False
    consume_reconcile_blocks()
    res = dispatch("/mcp", "enable fs", ctx=ctx)
    assert res.handled and "启用" in res.message
    # 用法错误。
    res = dispatch("/mcp", "disable", ctx=ctx)
    assert res.handled and res.result["ok"] is False
    res = dispatch("/mcp", "tool fs", ctx=ctx)
    assert res.handled and res.result["ok"] is False
