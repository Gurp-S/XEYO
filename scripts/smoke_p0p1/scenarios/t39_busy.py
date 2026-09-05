"""T39 并发：turn 运行中 -> /compact（/v1/chat/completions 的 "/compact" 分支）应 409。

用长 sleep 占住 turn；等 tool_call 出现后并发 POST "/compact" -> session_busy 409；
随后 interrupt 结束 turn。
"""

import time
from typing import Any


def responses(h: Any) -> list[dict[str, Any]]:
    return [
        {"tool_calls": [{"name": "Bash", "arguments": {
            "command": "python -c \"import time; time.sleep(30)\"",
            "description": "hold turn"}}]},
        {"content": "done"},
    ]


def run(h: Any) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    sid = h.create_session()
    t, res = h.chat_async(sid, "占住一轮")

    # 等 tool_call 出现（tool 开始执行，turn 仍持锁）
    deadline = time.time() + 25
    saw_tool = False
    while time.time() < deadline:
        if any(e.get("type") == "tool_call" for e in res.events):
            saw_tool = True
            break
        time.sleep(0.4)
    checks.append(("turn in-flight (tool_call seen)", saw_tool,
                   f"types={res.event_types()}"))

    body = {"model": "mock", "messages": [{"role": "user", "content": "/compact"}],
            "provider": "local", "base_url": h.mock_server.base_url,
            "workspace": str(h.workspace)}
    st, j = h.api("post", "/v1/chat/completions", json_body=body,
                  headers={"X-Session-Id": sid, "X-Provider": "local",
                           "X-Base-Url": h.mock_server.base_url})
    checks.append(("compact during turn -> 409", st == 409,
                   f"status={st} body={j}"))

    # 结束 turn
    h.api("post", "/v1/interrupt", json_body={"session_id": sid},
          headers={"X-Session-Id": sid})
    t.join(timeout=40)
    return checks
