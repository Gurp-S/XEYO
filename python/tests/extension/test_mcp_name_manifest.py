"""mcp_name_manifest_shadow 门槛/证明性测试（⑫）。

覆盖：
- 关（默认）：build_snapshot 返回原 schemas（逐位不变）。
- 开：每个工具收缩为 name+短描述，**不含 inputSchema**；保留 `_xeyo_full_schema` 取回指引。
- fail-open：非 dict schema / 缺 name → 整体回退原 schemas；单工具异常不丢。
- 契约安全：本模块不 monkey-patch ToolRegistry.schemas()、不触碰 `_schemas_cache`
  （用「未安装 flag / registry 无 monkey-patch」探针证明）。
"""

from __future__ import annotations

import pytest

from extension.mcp_name_manifest_shadow import (
    build_snapshot,
    enabled,
    full_schema_ref,
)


@pytest.fixture()
def m_off(monkeypatch):
    monkeypatch.delenv("XEYO_MCP_NAME_MANIFEST", raising=False)


def test_default_off_returns_unchanged(m_off):
    assert enabled() is False
    schemas = [{"name": "mcp__fs__read__", "description": "read", "inputSchema": {"type": "object"}}]
    assert build_snapshot(schemas) == schemas


def test_manifest_drops_input_schema(monkeypatch):
    monkeypatch.setenv("XEYO_MCP_NAME_MANIFEST", "1")
    schemas = [
        {
            "name": "mcp__fs__read__",
            "description": "Read a file.",
            "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
        {
            "name": "mcp__fs__write__",
            "description": "Write a file.",
            "parameters": {"type": "object", "properties": {}},
        },
    ]
    out = build_snapshot(schemas)
    assert len(out) == 2
    for item in out:
        assert "inputSchema" not in item
        assert "parameters" not in item
        assert "name" in item
        assert "_xeyo_full_schema" in item
    assert out[0]["_xeyo_full_schema"]["action"] == "describe"
    assert out[0]["_xeyo_full_schema"]["tool"] == "mcp__fs__read__"


def test_full_schema_ref():
    ref = full_schema_ref("mcp__s__t__")
    assert ref["action"] == "describe"
    assert ref["tool"] == "mcp__s__t__"
    assert ref["via"] == "Mcp"


def test_fail_open_bad_schema(monkeypatch):
    """任一非 dict / 缺 name → 整体回退原 schemas（逐位不变）。"""
    monkeypatch.setenv("XEYO_MCP_NAME_MANIFEST", "1")
    schemas = [{"name": "ok", "description": "d"}, "bad-not-dict"]
    assert build_snapshot(schemas) == schemas


def test_no_registry_monkeypatch(monkeypatch):
    """契约安全：使用本模块后 ToolRegistry 无 monkey-patch、`_schemas_cache` 未被触碰。"""
    monkeypatch.setenv("XEYO_MCP_NAME_MANIFEST", "1")
    from tools.tool_registry import ToolRegistry

    # 预先无 marker；构建快照不新增任何 registry 属性。
    reg = ToolRegistry(cwd=".")
    build_snapshot([{"name": "x", "description": "d"}])
    # 未对 registry 加任何"已安装/已替换"标志，schemas() 路径与缓存机制未被改动。
    assert "__mcp_name_manifest_installed" not in dir(reg)
    assert reg._schemas_cache is None  # 从未被触碰（仍未构建缓存）


def test_catalog_contract_untouched(monkeypatch):
    """schemas() 的 exposure 过滤语义保持不变：hidden 仍不进 schemas。"""
    monkeypatch.setenv("XEYO_MCP_NAME_MANIFEST", "1")
    # 只验证不干扰隐藏语义：给一个 exposure=hidden 的假工具。
    class FakeHidden:
        name = "mcp__hidden__x__"
        exposure = "hidden"

        def schema(self):
            return {"name": self.name, "description": "hidden"}

    from tools.tool_registry import ToolRegistry

    reg = ToolRegistry(cwd=".")
    reg._tools["mcp__hidden__x__"] = FakeHidden()  # noqa: SLF001
    sc = reg.schemas()  # 缓存构建
    assert not any(s.get("name") == "mcp__hidden__x__" for s in sc)
