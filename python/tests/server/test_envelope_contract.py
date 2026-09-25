"""服务端契约守卫：200 信封里的 `{ok:false}` 必须有人在读。

本项目反复出现的一类缺陷（这一轮就修了 5 处：停止按钮、三个裁决面板、TUI 的
`✓ allowed`）是同一个形状：**写请求失败被当成成功**。HTTP 状态码不够用，
因为这些端点用 200 + `{ok:false}` 表达"送达了但没接受"——客户端只查 `res.ok`
就会把它渲染成"已生效"。

修一处不等于不会再长一处：这条测试把"哪些端点会回 200 假 ok"钉成一张清单。
新增这种端点而没登记，这里就红，而不是等界面把"没删掉 / 没批准 / 没停"报成已完成。

清单分两档，可信度不同，不许混：
- READS_ENVELOPE：已逐个核实"客户端确实读了 body.ok"（写得出是哪个函数）；
- BASELINE_NOT_YET_VERIFIED：端点确实用信封回拒绝，但客户端那半边还没逐个核实。
  这一档是**已知欠账**，不是安全状态；每核实一个就往上一档挪一个，清零是目标。
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
}

BASELINE_NOT_YET_VERIFIED: frozenset[str] = frozenset(
    {
        "/v1/diagnostics/experiments",
        "/v1/diagnostics/experiments/plan",
        "/v1/diagnostics/messages/{message_id}",
        "/v1/diagnostics/reports/{report_id}",
        "/v1/diagnostics/runs/{turn_id}/pin",
        "/v1/extensions/settings",
        "/v1/local-models",
        "/v1/mcp",
        "/v1/mcp/op",
        "/v1/memory/compact",
        "/v1/plugins",
        "/v1/plugins/install",
        "/v1/plugins/market",
        "/v1/plugins/remove",
        "/v1/plugins/update",
        "/v1/references/files",
        "/v1/skills",
    }
)


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
    """会回 200 假 ok 的端点，必须落在两档清单之一里。"""
    found = _envelope_endpoints()
    registered = set(READS_ENVELOPE) | set(BASELINE_NOT_YET_VERIFIED)
    unlisted = sorted(set(found) - registered)
    gone = sorted(registered - set(found))
    assert not unlisted, (
        "这些端点用 200 + {ok:false} 表达拒绝，但清单里没有它："
        f"{[(p, found[p]) for p in unlisted]}。请登记进 READS_ENVELOPE（客户端确实读 body.ok）"
        "或 BASELINE_NOT_YET_VERIFIED（已知欠账），别让它悄悄长成假成功。"
    )
    assert not gone, f"这些端点已不再回 200 假 ok，请从清单里删掉：{gone}"


def test_verified_reading_list_is_a_subset_of_baseline() -> None:
    """两档不能重叠：核实过的就不该再算欠账（否则计数会说谎）。"""
    assert not (set(READS_ENVELOPE) & set(BASELINE_NOT_YET_VERIFIED))


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
