"""服务端契约守卫：200 信封里的 `{ok:false}` 必须有人在读。

本项目反复出现的一类缺陷（这一轮就修了 5 处：停止按钮、三个裁决面板、TUI 的
`✓ allowed`）是同一个形状：**写请求失败被当成成功**。HTTP 状态码不够用，
因为这些端点用 200 + `{ok:false}` 表达"送达了但没接受"——客户端只查 `res.ok`
就会把它渲染成"已生效"。

修一处不等于不会再长一处：这条测试把"哪些端点会回 200 假 ok"钉成一张清单。
新增这种端点而没登记，这里就红，而不是等界面把"没删掉 / 没批准 / 没停"报成已完成。

清单分三档，可信度不同，不许混：
- READS_ENVELOPE：已逐个核实"客户端确实读 body.ok"，并点名是哪个函数；
- NO_UI_CLIENT：gui/tui/cli 里没有任何调用点（只有服务端互调或人工 curl）。
  登记它不是为了放过它，而是因为**一旦有人补上客户端**，就必须从这一档挪走并核实读法；
- BASELINE_NOT_YET_VERIFIED：有客户端但读法还没逐个核实。这一档是**已知欠账**，
  不是安全状态；清零是目标。本轮全部门端点已分类完毕，所以它是空的——
  新增端点时必须选其中一档，不能不登记。

扫描同时覆盖路由内的返回值和显式委托给独立函数的返回值。
数量随源码变化；下面的集合比较保证端点既不能漏登记，也不能留过期登记。
"""

from __future__ import annotations

from pathlib import Path

from scripts.envelope_contract_scan import envelope_endpoints

SOURCE_ROOT = Path(__file__).resolve().parents[2]
ROUTERS = SOURCE_ROOT / "server" / "routers"

READS_ENVELOPE: dict[str, str] = {
    "/v1/interrupt": "gui api.ts::interruptChat + tui sse.ts::interruptSession",
    "/v1/permission/resolve": "gui permissions.ts::resolvePermission + tui sse.ts::resolvePermission",
    "/v1/ask/resolve": "gui permissions.ts::resolveAsk",
    "/v1/plan/{turn_id}/approve": "gui permissions.ts::resolvePlan",
    "/v1/permissions/grants/{grant_id}": "gui permissions.ts::revokePermissionGrant",
    "/v1/diagnostics/pins/{pin_id}": "gui diagnostics.ts::deleteDiagPin",
    "/v1/settings/memory": "gui api.bashPolicy/memorySwitches 系列：读 body.ok + 必需字段",
    "/v1/settings/memory/snapshot": "同上（同一客户端家族）",
    # 以下客户端已把"缺 ok 也算成功"改成"缺 ok = 读不出"：
    "/v1/plugins": "gui plugins.ts::fetchPlugins（ok === true）",
    "/v1/extensions/settings": "gui plugins.ts::fetchExtensionSettings（ok === true）",
    "/v1/skills": "gui skills.ts::fetchSkills（ok === true）",
    "/v1/references/files": "gui references.ts::fetchFileReferences（ok !== true 即读不出）",
    "/v1/mcp/op": "gui mcp.ts::mcpOp（body.ok === true）",
    "/v1/mcp": "gui mcp.ts::fetchMcpStatus（透传 body.ok；缺字段为 undefined ⇒ 调用方按失败处理）",
    "/v1/diagnostics/experiments": "gui diagnostics.ts::rawJson 的 envelopeFailure + ExperimentsView 按 r.ok 分支",
    "/v1/diagnostics/experiments/plan": "同上（plan/cancel 走同一个 rawJson）",
    "/v1/diagnostics/messages/{message_id}": "gui diagnostics.ts::fetchDiagMessage（ok: b(o.ok)，b 是 === true）",
    "/v1/diagnostics/runs/{turn_id}/pin": "gui diagnostics.ts::pinRun（同上）",
}

# 没有任何 UI/CLI 调用点的信封端点：本轮用 grep 在 gui/src、tui/src、python/cli 三处核实过。
# 有人补上客户端时，必须把它从这一档挪进 READS_ENVELOPE（并真的读 body.ok）。
NO_UI_CLIENT: dict[str, str] = {
    "/v1/memory/compact": "GUI/TUI/CLI 已无此 HTTP 调用点；GUI /compact 走 /v1/slash。保留 HTTP 信封契约登记。",
    "/v1/plugins/install": "仅服务端/人工调用；gui 里只有 GET /v1/plugins",
    "/v1/plugins/update": "同上",
    "/v1/plugins/remove": "同上",
    "/v1/plugins/market": "同上",
    "/v1/diagnostics/reports/{report_id}": "报告由服务端落盘，gui/tui/cli 无调用点",
}

BASELINE_NOT_YET_VERIFIED: frozenset[str] = frozenset()


def _envelope_endpoints() -> dict[str, str]:
    return envelope_endpoints(ROUTERS, SOURCE_ROOT)


def test_every_envelope_endpoint_is_registered() -> None:
    """会回 200 假 ok 的端点，必须落在三档清单之一里。"""
    found = _envelope_endpoints()
    registered = set(READS_ENVELOPE) | set(NO_UI_CLIENT) | set(BASELINE_NOT_YET_VERIFIED)
    unlisted = sorted(set(found) - registered)
    gone = sorted(registered - set(found))
    assert not unlisted, (
        "这些端点用 200 + {ok:false} 表达拒绝，但清单里没有它："
        f"{[(p, found[p]) for p in unlisted]}。请登记进 READS_ENVELOPE（客户端确实读 body.ok）"
        "或 BASELINE_NOT_YET_VERIFIED（已知欠账）；没有调用点的进 NO_UI_CLIENT。别让它悄悄长成假成功。"
    )
    assert not gone, f"这些端点已不再回 200 假 ok，请从清单里删掉：{gone}"


def test_envelope_tiers_do_not_overlap() -> None:
    """三档不能重叠：一个端点不能同时是"已核实"、"没有客户端"和"欠账"。

    重叠会让计数说谎——同一端点既被算安全又被算待办；而"没有客户端"也不该
    变成逃避核实的去处：一旦有人补上客户端，它必须被挪进已核实档。
    """
    reads, no_client, debt = set(READS_ENVELOPE), set(NO_UI_CLIENT), set(BASELINE_NOT_YET_VERIFIED)
    assert not (reads & debt), f"既算已核实又算欠账：{sorted(reads & debt)}"
    assert not (reads & no_client), f"既算已核实又声称没有客户端：{sorted(reads & no_client)}"
    assert not (no_client & debt), f"既说没有客户端又挂着欠账：{sorted(no_client & debt)}"


def test_extracting_response_to_helper_preserves_inventory(tmp_path: Path) -> None:
    """重构返回值的位置不能让契约消失；只保留成功返回时则必须从发现结果消失。"""
    routers = tmp_path / "routers"
    routers.mkdir()
    route = routers / "example.py"
    route.write_text('@router.post("/x")\nasync def x():\n    return {"ok": False}\n', encoding="utf-8")
    assert set(envelope_endpoints(routers, tmp_path)) == {"/x"}
    helper = tmp_path / "helper.py"
    helper.write_text('async def result():\n    return {"ok": False}\n', encoding="utf-8")
    route.write_text('@router.post("/x")\nasync def x():\n    from helper import result\n    return await result()\n', encoding="utf-8")
    assert set(envelope_endpoints(routers, tmp_path)) == {"/x"}
    helper.write_text('async def result():\n    return {"ok": True}\n', encoding="utf-8")
    assert envelope_endpoints(routers, tmp_path) == {}
