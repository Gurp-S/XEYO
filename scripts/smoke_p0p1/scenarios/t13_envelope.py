"""T13 事件信封：同一 turn 的 tool_call/tool_result 成对且共享 envelope 身份。

断言 xeyo 帧携带 session_id/turn_id/event_id，tool_call 与 tool_result 的
tool_use_id 一致（开始/结束配对，T13 的 begin/end 语义）。
"""

from typing import Any


def responses(h: Any) -> list[dict[str, Any]]:
    return [
        {"tool_calls": [{"name": "Bash", "arguments": {"command": "Get-Date",
                                                       "description": "date"}}]},
        {"content": "已执行。"},
    ]


def run(h: Any) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    sid = h.create_session()
    tr = h.chat(sid, "看下时间")
    tcalls = [e for e in tr.events if e.get("type") == "tool_call"]
    tres = [e for e in tr.events if e.get("type") == "tool_result"]
    checks.append(("tool_call present", len(tcalls) >= 1,
                   f"n={len(tcalls)} types={tr.event_types()}"))
    checks.append(("tool_result present", len(tres) >= 1,
                   f"n={len(tres)}"))

    # 每个事件都带 envelope 身份
    id_ok = all(e.get("session_id") == sid and e.get("turn_id")
                and e.get("event_id") for e in tr.events
                if e.get("type") not in ("__http_error__", "__transport_error__"))
    checks.append(("envelope identity on frames", id_ok,
                   f"session_id={tr.events[0].get('session_id') if tr.events else None}"))

    # 开始/结束配对：tool_call 的 tool_use_id == 对应 tool_result 的 tool_use_id
    paired = False
    if tcalls and tres:
        call_id = tcalls[0].get("tool_use_id")
        res_ids = {r.get("tool_use_id") for r in tres}
        paired = bool(call_id) and (call_id in res_ids)
    checks.append(("begin/end paired by tool_use_id", paired,
                   f"call_id={tcalls[0].get('tool_use_id') if tcalls else None} "
                   f"res_ids={[r.get('tool_use_id') for r in tres]}"))
    return checks
