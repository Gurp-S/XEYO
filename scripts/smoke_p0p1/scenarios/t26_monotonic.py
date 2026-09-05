"""T26 权限单向性：工作区策略 bash=ask 把内置 allow 收成 ask，且用户 allow 不反向放宽。"""

from typing import Any


def responses(h: Any) -> list[dict[str, Any]]:
    echo = {"tool_calls": [{"name": "Bash", "arguments": {"command": "echo hi",
                                                          "description": "hi"}}]}
    return [dict(echo), {"content": "好的。"}, dict(echo), {"content": "好的。"}]


def run(h: Any) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    # 工作区策略：bash 一律 ask（把内置 allow 的 echo 收紧）
    (h.workspace / ".xeyo-policy.json").write_text('{"bash":"ask"}', encoding="utf-8")
    sid = h.create_session()

    first = h.chat(sid, "打个招呼")
    checks.append(("policy ask tightens builtin allow (echo asks)",
                   "permission_pending" in first.event_types(),
                   f"types={first.event_types()}"))

    # 用户此前已 allow（本次 remember=False，无 grant），再来一次应仍 ask（不反向放宽）
    second = h.chat(sid, "再打个招呼")
    checks.append(("monotonic: allow does not relax policy",
                   "permission_pending" in second.event_types(),
                   f"types={second.event_types()}"))
    return checks
