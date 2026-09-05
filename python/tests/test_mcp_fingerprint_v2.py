"""指纹 v2 测试组（P0b §15.1④ 独立测试组 —— 安全最集中单点）。

覆盖冻结规格六项：
①同工具异 args 同指纹；②异工具异指纹；③args 伪装字段不迁移（注入免疫）；
④grant 回环（存→evaluate 命中→ALLOW）；⑤deny 压过 grant；⑥版本隔离
（v1 旧指纹不命中 v2 查找）。另含 canonical_args 纯函数性质、挂起项
mcp_target 穿透（网关存取对称）。

运行：``py -3.11 -m pytest tests/test_mcp_fingerprint_v2.py -q``
"""

from __future__ import annotations

import asyncio
import os

import pytest

from engine.abort import AbortController
from extension.mcp_client import McpClientSpec, McpTool, mcp_tool_name
from msgtypes.message import ToolUse
from permissions.filesystem import PermissionDecision
from permissions.policy import evaluate_policy
from permissions.store import (
    canonical_args,
    grant_fingerprint,
    mcp_grant_fingerprint,
)
from tools.tool_registry import ToolRegistry

_REG = "mcp__fs__read_file__a1b2c3d4e5f6"
_REG_OTHER = "mcp__fs__write_file__b2c3d4e5f6a1"
_REG_OTHER_SERVER = "mcp__other__read_file__c3d4e5f6a1b2"


def _tool(*, policy="outbound_ask", server_id="fs", raw_name="read_file"):
    spec = McpClientSpec(id=server_id, command="x")
    raw = {"name": raw_name, "inputSchema": {"type": "object", "properties": {}}}
    return McpTool(
        None, spec, server_id=server_id, raw_name=raw_name,
        tool_name=mcp_tool_name(server_id, raw_name),
        raw_schema=raw, policy=policy,
    )


def _cwd(tmp_path):
    return os.path.abspath(str(tmp_path))


# --------------------------------------------------------------------------- #
# ① 同工具异 args 同指纹 ② 异工具异指纹
# --------------------------------------------------------------------------- #


def test_same_tool_diff_args_same_fingerprint():
    inputs = [
        {},
        {"path": "a.txt"},
        {"path": "a.txt", "mode": "r"},
        {"nested": {"z": [1, 2, {"k": "v"}]}, "b": True, "a": None},
        {"path": "a.txt", "server": "evil", "tool": "bomb"},
    ]
    fps = {grant_fingerprint(_REG, i) for i in inputs}
    assert len(fps) == 1
    assert fps != {""}


def test_diff_tools_diff_fingerprints():
    fps = {
        grant_fingerprint(_REG, {}),
        grant_fingerprint(_REG_OTHER, {}),
        grant_fingerprint(_REG_OTHER_SERVER, {}),
    }
    assert len(fps) == 3


# --------------------------------------------------------------------------- #
# ③ args 伪装字段不迁移（注入免疫）
# --------------------------------------------------------------------------- #


def test_args_spoofing_never_migrates():
    base = grant_fingerprint(_REG, {})
    spoofed = grant_fingerprint(
        _REG,
        {
            "mcp_target": _REG_OTHER,
            "server_id": "other",
            "raw_tool": "drop_table",
            "registered_name": _REG_OTHER,
            "args": {"tool_name": _REG_OTHER},
        },
    )
    assert spoofed == base


def test_gateway_identity_uses_resolved_target_not_input():
    # 网关路径：身份来自 mcp_target（解析后的注册名），input 里的伪装无效。
    via_target = grant_fingerprint("Mcp", {"server": "fs", "tool": "read_file"}, mcp_target=_REG)
    spoofed = grant_fingerprint("Mcp", {"server": "evil", "tool": "bomb"}, mcp_target=_REG)
    native = grant_fingerprint(_REG, {})
    assert via_target == native
    assert spoofed == native


# --------------------------------------------------------------------------- #
# ④ grant 回环（存 → evaluate → ALLOW）
# --------------------------------------------------------------------------- #


def test_grant_roundtrip_via_policy(tmp_path, monkeypatch):
    from permissions.store import default_grant_store

    monkeypatch.setenv(
        "XEYO_ENTERPRISE_POLICY", str(tmp_path / "absent-policy.json")
    )
    cwd = _cwd(tmp_path)
    tool = _tool()
    base = evaluate_policy(tool.name, {}, cwd=cwd, tool=tool)
    assert base.decision == PermissionDecision.ASK
    assert base.matched_rule == "mcp_outbound_ask"

    fp = grant_fingerprint(tool.name, {})
    assert fp.startswith("v2:")
    default_grant_store().add(tool_name=tool.name, fingerprint=fp, scope=cwd)
    d = evaluate_policy(tool.name, {"x": 1}, cwd=cwd, tool=tool)
    # ① 的直接推论：异 args 命中同一 grant。
    assert d.decision == PermissionDecision.ALLOW
    assert d.matched_rule == "grant_store"


# --------------------------------------------------------------------------- #
# ⑤ deny 压过 grant
# --------------------------------------------------------------------------- #


def test_deny_beats_grant(tmp_path, monkeypatch):
    from permissions.store import default_grant_store

    pol = tmp_path / "policy.json"
    monkeypatch.setenv("XEYO_ENTERPRISE_POLICY", str(pol))
    pol.write_text('{"mcp_tool_deny": ["fs/read_file"]}', encoding="utf-8")
    cwd = _cwd(tmp_path)
    tool = _tool()
    fp = grant_fingerprint(tool.name, {})
    default_grant_store().add(tool_name=tool.name, fingerprint=fp, scope=cwd)
    d = evaluate_policy(tool.name, {}, cwd=cwd, tool=tool)
    assert d.decision == PermissionDecision.DENY
    assert d.matched_rule == "mcp_enterprise_deny"
    # fail-safe 端到端：无 coordinator → DENY 结果。
    reg = ToolRegistry(cwd=cwd)
    reg.register(tool)
    res = asyncio.run(
        reg.run(ToolUse(id="t1", name=tool.name, input={}), AbortController())
    )
    assert res.is_error is True
    assert res.metadata.get("permission_reason") == "mcp_enterprise_deny"


# --------------------------------------------------------------------------- #
# ⑥ 版本隔离：v1 旧指纹不命中 v2 查找
# --------------------------------------------------------------------------- #


def test_version_isolation_v1_grant_does_not_match(tmp_path, monkeypatch):
    from permissions.store import default_grant_store

    monkeypatch.setenv(
        "XEYO_ENTERPRISE_POLICY", str(tmp_path / "absent-policy.json")
    )
    cwd = _cwd(tmp_path)
    tool = _tool()
    # v1 时代落库：裸 matched_rule（对所有 MCP 工具共用 —— v1 过放根源）。
    default_grant_store().add(
        tool_name=tool.name, fingerprint="mcp_outbound_ask", scope=cwd
    )
    d = evaluate_policy(tool.name, {}, cwd=cwd, tool=tool)
    # v2 查找算出的身份哈希 ≠ "mcp_outbound_ask" → 不命中 → 仍 ASK。
    assert d.decision == PermissionDecision.ASK


def test_v1_shared_rule_grant_cannot_allow_other_tool(tmp_path):
    # v1 缺陷回归钉：一个 MCP 工具的旧 grant 不再放行另一个 MCP 工具。
    from permissions.store import default_grant_store

    cwd = _cwd(tmp_path)
    tool_a = _tool(raw_name="read_file")
    store = default_grant_store()
    # 用 v1 语义手工造：同 matched_rule 指纹挂到工具 B 名下。
    store.add(tool_name=tool_a.name, fingerprint="mcp_outbound_ask", scope=cwd)
    tool_b = _tool(raw_name="write_file")
    assert evaluate_policy(tool_b.name, {}, cwd=cwd, tool=tool_b).decision == (
        PermissionDecision.ASK
    )


# --------------------------------------------------------------------------- #
# 指纹函数性质 + canonical_args
# --------------------------------------------------------------------------- #


def test_v2_fingerprint_format():
    fp = mcp_grant_fingerprint(_REG)
    assert fp.startswith("v2:")
    assert len(fp) == len("v2:") + 32
    assert int(fp[3:], 16) >= 0  # 32hex
    assert mcp_grant_fingerprint(_REG) == fp  # 确定性


@pytest.mark.parametrize(
    "bad", ["", "mcp", "mcp__", "mcp__ ", "Read", "mcpX__fs__a__b"]
)
def test_mcp_grant_fingerprint_invalid_identity(bad):
    assert mcp_grant_fingerprint(bad) == ""
    if bad.startswith("mcp__"):
        # 退化 mcp 名：v2 分支返回空串 = 身份不可用 → 不可落 grant（fail-safe）。
        assert grant_fingerprint(bad, {}, matched_rule="some_rule") == ""
    else:
        # 非 mcp 名走 v1（matched_rule），不误入 v2 分支。
        assert grant_fingerprint(bad, {}, matched_rule="some_rule") == "some_rule"


def test_mcp_target_empty_falls_back_to_name():
    # mcp_target 非法（空/非 mcp__）→ 回退 tool_name（原生路径语义）。
    assert grant_fingerprint(_REG, {}, mcp_target="") == grant_fingerprint(_REG, {})
    assert grant_fingerprint(_REG, {}, mcp_target="Bash") == grant_fingerprint(_REG, {})


def test_canonical_args_pure_properties():
    assert canonical_args(None) == ""
    assert canonical_args({}) == ""
    assert canonical_args({"b": 1, "a": 2}) == canonical_args({"a": 2, "b": 1})
    assert canonical_args({"k": "值"}) == '{"k":"\\u503c"}'
    assert canonical_args({"s": {1, 2}}) != ""  # 不可序列化叶子 default=str 稳定化
    # 键序无关且紧凑（无空白）。
    assert " " not in canonical_args({"a": 1, "b": [1, 2]})


def test_pending_item_carries_mcp_target():
    # 网关存取对称：挂起项携带解析后的目标注册名（control.py 落库用）。
    from permissions.store import PendingPermissionStore

    store = PendingPermissionStore(ttl_seconds=60)
    item = store.create(
        session_id="s",
        turn_id="t",
        tool_name="Mcp",
        tool_input={"server": "fs", "tool": "read_file", "args": {}},
        reason="needs_confirmation",
        prompt="Allow?",
        mcp_target=_REG,
    )
    assert item.mcp_target == _REG
    fp_save = grant_fingerprint(
        item.tool_name, item.tool_input, matched_rule=item.matched_rule,
        mcp_target=item.mcp_target,
    )
    assert fp_save == mcp_grant_fingerprint(_REG)
