"""T9 Goal：会话启动即绑定目标 + PATCH revision CAS。

绑定钩子（chat.py submit 非续跑分支）在首次提交时 create+bind。
CAS：PATCH 带过期 revision → 409 且 body 附当前 goal。
"""

from typing import Any

RESPONSES = [
    {"content": "好的，我会帮你完成这个目标。"},
]


def run(h: Any) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    sid = h.create_session()
    h.chat(sid, "帮我完成一个目标：撰写调研报告")

    goal = h.get_goal(sid)
    checks.append(("goal bound after submit",
                   bool(goal.get("goal_id")),
                   f"goal_id={goal.get('goal_id')!r} status={goal.get('status')!r}"))
    checks.append(("goal revision present",
                   int(goal.get("revision") or 0) >= 1,
                   f"revision={goal.get('revision')}"))
    checks.append(("goal text matches user",
                   str(goal.get("text") or "").startswith("帮我完成"),
                   f"text={goal.get('text')!r}"))

    st, body = h.patch_goal(sid, {"action": "confirm_complete", "revision": 999999})
    checks.append(("stale revision -> 409",
                   st == 409,
                   f"status={st} body={body}"))
    if isinstance(body, dict):
        checks.append(("409 body carries current goal",
                       bool(body.get("goal") or body.get("current")),
                       f"keys={list(body.keys())}"))
    return checks
