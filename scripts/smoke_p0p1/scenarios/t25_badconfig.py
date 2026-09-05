"""T25 坏配置 fail-closed：坏 .xeyo-policy.json -> 默认收紧为 ask（原本放行的 echo 也 ASK）。"""

import json
from typing import Any


def responses(h: Any) -> list[dict[str, Any]]:
    return [
        {"tool_calls": [{"name": "Bash", "arguments": {"command": "echo hi",
                                                       "description": "hi"}}]},
        {"content": "好的。"},
    ]


def run(h: Any) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    # 写坏策略：非法 JSON -> loader fail-closed 默认收紧（ask）
    (h.workspace / ".xeyo-policy.json").write_text("{ this is invalid json ", encoding="utf-8")
    sid = h.create_session()
    tr = h.chat(sid, "打个招呼")
    checks.append(("echo hi -> permission_pending (tightened to ask)",
                   "permission_pending" in tr.event_types(),
                   f"types={tr.event_types()}"))
    return checks
