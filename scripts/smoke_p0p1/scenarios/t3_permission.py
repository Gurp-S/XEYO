"""T3/T10 审批协议：写类命令触发 ASK -> resolve(remember) -> 同类第二次不再 ASK。

走 Bash git 写子命令（不在只读白名单 => ask）。断言 SSE 事件：
permission_pending -> permission_resolved，且 grant 记住后第二次同命令无 pending。
同时验证 /v1/permissions/grants 可见、可撤销。
"""

from typing import Any


def responses(h: Any) -> list[dict[str, Any]]:
    return [
        {"tool_calls": [{"name": "Bash", "arguments": {"command": "git push", "description": "push"}}]},
        {"content": "已推送。"},
    ]


def _has(tr: Any, t: str) -> bool:
    return t in tr.event_types()


def run(h: Any) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    sid = h.create_session()

    first = h.chat(sid, "帮我 git push 一下", remember_permission=True)
    checks.append(("first call -> permission_pending", _has(first, "permission_pending"),
                   f"types={first.event_types()}"))
    checks.append(("first call -> permission_resolved", _has(first, "permission_resolved"),
                   "resolved event emitted after auto-approve"))
    checks.append(("first call -> tool_executed", _has(first, "tool_result"),
                   f"types={first.event_types()}"))

    # grant 被记住
    st, j = h.api("get", "/v1/permissions/grants")
    grants = (j or {}).get("grants") or [] if isinstance(j, dict) else []
    checks.append(("grant remembered", len(grants) >= 1,
                   f"grants={[{g.get('tool_name') for g in grants}]}"))

    second = h.chat(sid, "再 push 一次")
    checks.append(("second call -> no ask (grant)", not _has(second, "permission_pending"),
                   f"types={second.event_types()}"))

    if grants:
        gid = grants[0].get("grant_id")
        if gid:
            _, rev = h.api("delete", f"/v1/permissions/grants/{gid}")
            checks.append(("grant revocable", bool((rev or {}).get("ok")),
                           f"revoke={rev}"))
    return checks
