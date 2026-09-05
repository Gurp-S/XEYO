"""T2 取消归一：中断正在执行的工具 -> 回喂 'aborted by user after Ns'（is_error=False）。"""

import time
from typing import Any


def responses(h: Any) -> list[dict[str, Any]]:
    return [
        {"tool_calls": [{"name": "Bash", "arguments": {
            "command": "python -c \"import time; time.sleep(30)\"",
            "description": "hold"}}]},
        {"content": "已中断。"},
    ]


def run(h: Any) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    sid = h.create_session()
    t, res = h.chat_async(sid, "跑一个长命令")
    deadline = time.time() + 25
    saw_tool = False
    while time.time() < deadline:
        if any(e.get("type") == "tool_call" for e in res.events):
            saw_tool = True
            break
        time.sleep(0.4)
    checks.append(("tool in-flight", saw_tool, f"types={res.event_types()}"))

    h.api("post", "/v1/interrupt", json_body={"session_id": sid},
          headers={"X-Session-Id": sid})
    t.join(timeout=40)

    blob = res.assistant + " ".join(str(e) for e in res.events)
    checks.append(("interrupt -> clean aborted stop", "aborted" in blob.lower()
                   or any(e.get("type") == "stopped" for e in res.events),
                   f"assistant={res.assistant[:40]!r}"))
    # 中断后会话可继续（下一轮正常完成，未崩溃）
    again = h.chat(sid, "继续")
    checks.append(("session continues after cancel",
                   bool(again.assistant) or len(again.events) > 0,
                   f"assistant={again.assistant[:30]!r}"))
    return checks
