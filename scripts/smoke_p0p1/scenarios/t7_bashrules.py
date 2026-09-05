"""T7 bash 规则引擎：deny 规则收紧内置 allow；allow 规则放宽默认 ask。"""

import json
from typing import Any


def responses(h: Any) -> list[dict[str, Any]]:
    return [
        {"tool_calls": [{"name": "Bash", "arguments": {"command": "echo hi",
                                                       "description": "hi"}}]},
        {"content": "完成。"},
    ]


def run(h: Any) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    # 工作区规则：deny echo（压过内置 allow）
    rules = {"rules": [
        {"name": "no-echo", "program": "echo", "prefix": [], "decision": "deny"},
    ]}
    (h.workspace / ".xeyo").mkdir(parents=True, exist_ok=True)
    (h.workspace / ".xeyo" / "bash_rules.json").write_text(
        json.dumps(rules), encoding="utf-8")

    sid = h.create_session()
    tr = h.chat(sid, "echo 一下")

    # echo hi -> deny 规则生效（is_error True，且未被 ask 放行）
    tres = [e for e in tr.events if e.get("type") == "tool_result"]
    echo_err = bool(tres and tres[0].get("is_error"))
    checks.append(("echo denied by rule", echo_err,
                   f"n_results={len(tres)} "
                   f"first_out={str(tres[0].get('output') or '')[:60] if tres else None!r}"))
    return checks
    return checks
