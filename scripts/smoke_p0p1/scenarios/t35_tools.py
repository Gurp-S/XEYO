"""T35 诚实度：引擎真正把启用的工具目录发给模型（catalog 即服务面），非只读文档。"""

from typing import Any

RESPONSES = [{"content": "好的。"}]


def run(h: Any) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    sid = h.create_session()
    h.chat(sid, "你好")
    # 主轮次请求带 tools；旁路（标题增强）不带 tools
    reqs = [r for r in h.mock_requests() if r.get("tools")]
    names: set[str] = set()
    for r in reqs:
        names |= {str(t) for t in r.get("tools") or []}
    checks.append(("tool catalog served to model", len(reqs) >= 1,
                   f"n_main_reqs={len(reqs)}"))
    checks.append(("catalog non-empty", len(names) > 0, f"n_tools={len(names)}"))
    for want in ("Bash", "Write", "Grep", "Read", "TodoWrite", "getTime"):
        checks.append((f"core tool present: {want}", want in names,
                       f"has={want in names} all={sorted(names)}"))
    return checks
