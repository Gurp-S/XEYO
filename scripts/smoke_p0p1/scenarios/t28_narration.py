"""T28 旁白保留：模型在工具调用前的文字（narration）留在 transcript。"""

from typing import Any


def responses(h: Any) -> list[dict[str, Any]]:
    return [
        {"content": "这是旁白：我先看下时间。",
         "tool_calls": [{"name": "Bash", "arguments": {"command": "Get-Date",
                                                       "description": "date"}}]},
        {"content": "完成。"},
    ]


def run(h: Any) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    sid = h.create_session()
    tr = h.chat(sid, "看下时间")
    checks.append(("tool executed", any(e.get("type") == "tool_result"
                                        for e in tr.events),
                   f"types={tr.event_types()}"))

    msgs = h.read_messages(sid)
    narration_api = any("旁白" in str(m.get("content")) for m in msgs
                        if m.get("role") == "assistant")
    # 投影（API 视图）按设计忽略旁白；原始 JSONL 应保留——扫会话目录
    raw_has = False
    for p in h.sessions_dir.rglob("*.jsonl"):
        try:
            if "旁白" in p.read_text("utf-8", errors="replace"):
                raw_has = True
                break
        except OSError:
            pass
    checks.append(("narration retained in raw JSONL", raw_has,
                   f"n_messages={len(msgs)} api_view={narration_api}"))
    return checks
