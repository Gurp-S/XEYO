"""T4 崩溃恢复：turn 进行中强杀引擎 -> 重启 -> resume 同一会话仍可续聊。

用长 sleep 占住 turn，等 tool_call 出现后 kill -9 引擎；重启后同 sid 再发消息，
由 hydrate 合成未闭合 tool_use，会话继续。
"""

import time
from typing import Any


def responses(h: Any) -> list[dict[str, Any]]:
    return [
        {"tool_calls": [{"name": "Bash", "arguments": {
            "command": "python -c \"import time; time.sleep(30)\"",
            "description": "hold"}}]},
        {"content": "恢复完成。"},
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
    checks.append(("turn in-flight before crash", saw_tool,
                   f"types={res.event_types()}"))

    h.kill_engine()

    # 重启同一引擎（同 XEYO_HOME / workspace -> 会话持久化），复用已运行的 mock
    h.up()
    checks.append(("engine restarted", bool(h.base_url), f"url={h.base_url}"))

    tr = h.chat(sid, "继续")
    checks.append(("resume turn completes", bool(tr.assistant) or len(tr.events) > 0,
                   f"assistant={tr.assistant[:40]!r} types={tr.event_types()}"))

    # transcript 不再有未闭合 tool_use（hydrate 合成兜底）
    msgs = h.read_messages(sid)
    tool_use_msgs = [m for m in msgs if str(m.get("role")) == "assistant"
                     and m.get("tool_calls")]
    checks.append(("no dangling tool_use after resume",
                   len(tool_use_msgs) == 0,
                   f"n_dangling={len(tool_use_msgs)} n_messages={len(msgs)}"))
    return checks
