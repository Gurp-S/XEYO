"""T6 重复调用治理：同一工具同参数连续 3 次 -> 下一次模型请求注入 Repeat guard。"""

from typing import Any


def responses(h: Any) -> list[dict[str, Any]]:
    cmd = {"command": "Get-Date", "description": "date"}
    return [
        {"tool_calls": [{"name": "Bash", "arguments": dict(cmd)}]},
        {"tool_calls": [{"name": "Bash", "arguments": dict(cmd)}]},
        {"tool_calls": [{"name": "Bash", "arguments": dict(cmd)}]},
        {"content": "完成。"},
    ]


def run(h: Any) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    sid = h.create_session()
    tr = h.chat(sid, "重复看几次时间")
    checks.append(("repeated calls executed", tr.event_types().count("tool_call") >= 3,
                   f"n_tool_call={tr.event_types().count('tool_call')}"))

    # 任一主轮次请求的消息里应出现 repeat guard 提醒
    saw_guard = False
    for r in h.mock_requests():
        blob = str(r.get("messages") or "")
        if "repeat guard" in blob.lower() or "重复" in blob:
            saw_guard = True
            break
    checks.append(("repeat guard injected", saw_guard,
                   f"n_requests={len(h.mock_requests())}"))
    return checks
