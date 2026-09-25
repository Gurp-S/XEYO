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

分类那次的实测口径（数字会随清单变化；保证它不说谎的是下面两条测试，不是这句话）：
扫到 25 个信封端点 = 20 个已核实客户端读 body.ok + 5 个在任何 UI/CLI 里都没有调用点，欠账 0。
"""

from __future__ import annotations

import re
from pathlib import Path

ROUTERS = Path(__file__).resolve().parents[2] / "server" / "routers"

# 信封式拒绝：`{"ok": False}` 或 `{"ok": <变量>}`。常量 `{"ok": True}` 不算——
# 那意味着这端点从不拒绝，失败一律走 HTTP 错误码，客户端看状态码就够。
_ENVELOPE = re.compile(r'return \{[^{}]*"ok":\s*(?!True\b)[A-Za-z_]')
_ENVELOPE_LINE = re.compile(r'return \{[^{}]*"ok":\s*(?!True\b)([A-Za-z_]\w*)')

READS_ENVELOPE: dict[str, str] = {
    "/v1/interrupt": "gui api.ts::interruptChat + tui sse.ts::interruptSession",
    "/v1/permission/resolve": "gui permissions.ts::resolvePermission + tui sse.ts::resolvePermission",
    "/v1/ask/resolve": "gui permissions.ts::resolveAsk",
    "/v1/plan/{turn_id}/approve": "gui permissions.ts::resolvePlan",
    "/v1/permissions/grants/{grant_id}": "gui permissions.ts::revokePermissionGrant",
    "/v1/diagnostics/pins/{pin_id}": "gui diagnostics.ts::deleteDiagPin",
    "/v1/settings/memory": "gui api.bashPolicy/memorySwitches 系列：读 body.ok + 必需字段",
    "/v1/settings/memory/snapshot": "同上（同一客户端家族）",
    # 以下七个是本轮核实并顺手把"缺 ok 也算成功"改成"缺 ok = 读不出"的：
    "/v1/plugins": "gui plugins.ts::fetchPlugins（ok === true）",
    "/v1/extensions/settings": "gui plugins.ts::fetchExtensionSettings（ok === true）",
    "/v1/skills": "gui skills.ts::fetchSkills（ok === true）",
    "/v1/references/files": "gui references.ts::fetchFileReferences（ok !== true 即读不出）",
    "/v1/mcp/op": "gui mcp.ts::mcpOp（body.ok === true）",
    "/v1/memory/compact": "gui memory.ts 透传服务端 ok/compact_cursor/reason",
    "/v1/local-models": "gui localModels.ts::setLocalModelSettings（b.ok === true + 必需字段）",
    "/v1/mcp": "gui mcp.ts::fetchMcpStatus（透传 body.ok；缺字段为 undefined ⇒ 调用方按失败处理）",
    "/v1/diagnostics/experiments": "gui diagnostics.ts::rawJson 的 envelopeFailure + ExperimentsView 按 r.ok 分支",
    "/v1/diagnostics/experiments/plan": "同上（plan/cancel 走同一个 rawJson）",
    "/v1/diagnostics/messages/{message_id}": "gui diagnostics.ts::fetchDiagMessage（ok: b(o.ok)，b 是 === true）",
    "/v1/diagnostics/runs/{turn_id}/pin": "gui diagnostics.ts::pinRun（同上）",
}

# 没有任何 UI/CLI 调用点的信封端点：本轮用 grep 在 gui/src、tui/src、python/cli 三处核实过。
# 有人补上客户端时，必须把它从这一档挪进 READS_ENVELOPE（并真的读 body.ok）。
NO_UI_CLIENT: dict[str, str] = {
    "/v1/plugins/install": "仅服务端/人工调用；gui 里只有 GET /v1/plugins",
    "/v1/plugins/update": "同上",
    "/v1/plugins/remove": "同上",
    "/v1/plugins/market": "同上",
    "/v1/diagnostics/reports/{report_id}": "报告由服务端落盘，gui/tui/cli 无调用点",
}

BASELINE_NOT_YET_VERIFIED: frozenset[str] = frozenset()


def _envelope_endpoints() -> dict[str, str]:
    """按 @router 装饰器切块扫描。

    必须整块扫，不能逐行：`return {` 换行的写法（control.py 的 permission resolve）
    逐行正则看不见，那正是最需要被守住的那个端点。
    """
    found: dict[str, str] = {}
    blocks = re.compile(r'@router\.(?:get|post|put|delete|patch)\("([^"]+)"')
    for path in sorted(ROUTERS.glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        marks = [(m.start(), m.group(1)) for m in blocks.finditer(text)]
        for i, (start, route) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
            hit = _ENVELOPE_LINE.search(text[start:end])
            if hit:
                found.setdefault(route, f"{path.name}:{hit.group(1)}")
    return found


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


def test_envelope_regex_actually_catches_the_shape() -> None:
    """哨兵：正则必须抓得到那种写法，也必须放过常量 True。

    哪天 return 被拆成多行或换了引号而正则失配，两条清单断言会一起"绿"成零违规。
    """
    dynamic = '@router.post("/v1/x")\ndef x(b) -> dict:\n\tok = store.resolve(b.id)\n\treturn {"ok": ok, "id": b.id}\n'
    # /v1/permission/resolve 真实就是这种形状：`return {` 换行、"ok" 单独一行。
    multiline = '@router.post("/v1/w")\ndef w(b) -> dict:\n\tres = store.resolve(b.id)\n\treturn {\n\t\t"ok": res,\n\t}\n'
    literal_false = '@router.post("/v1/y")\ndef y() -> dict:\n\treturn {"ok": False, "error": "bad"}\n'
    always_true = '@router.post("/v1/z")\ndef z() -> dict:\n\treturn {"ok": True}\n'
    assert _ENVELOPE.search(dynamic) and _ENVELOPE_LINE.search(dynamic)
    assert _ENVELOPE.search(multiline), "多行 return 也必须抓到：漏了它，最危险的端点会悄悄不出现在清单里"
    assert _ENVELOPE_LINE.search(multiline).group(1) == "res"
    assert _ENVELOPE.search(literal_false)
    assert not _ENVELOPE.search(always_true), "常量 True 的端点不该算信封拒绝"
    assert not _ENVELOPE_LINE.findall("x = {'ok': ok}")  # 非 return 语句不抓
