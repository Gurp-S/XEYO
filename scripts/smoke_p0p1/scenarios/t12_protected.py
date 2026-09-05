"""T12 受保护元数据：写 .xeyo/ 下路径必须 DENY，正常源码写放行。"""

from typing import Any


def responses(h: Any) -> list[dict[str, Any]]:
    ws = str(h.workspace).replace("\\", "/")
    return [
        {"tool_calls": [{"name": "Write",
                         "arguments": {"file_path": ws + "/.xeyo/settings.json",
                                       "content": "{}"}}]},
        {"tool_calls": [{"name": "Write",
                         "arguments": {"file_path": ws + "/src.txt",
                                       "content": "hello"}}]},
        {"content": "finish"},
    ]


def _tool_results(tr: Any) -> list[dict[str, Any]]:
    return [e for e in tr.events if e.get("type") == "tool_result"]


def run(h: Any) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    sid = h.create_session()
    (h.workspace / ".xeyo").mkdir(parents=True, exist_ok=True)

    tr = h.chat(sid, "写配置和源码")
    results = _tool_results(tr)
    checks.append(("two tool_results", len(results) >= 2,
                   f"n={len(results)} types={tr.event_types()}"))

    protected_output = ""
    normal_output = ""
    # 第一/第二结果的 is_error 判定
    errored = [e.get("is_error") for e in results]
    if len(results) >= 2:
        protected_output = str(results[0].get("output") or "")
        normal_output = str(results[1].get("output") or "")
        # 保护路径的写应判错（is_error True 或输出含拒绝/保护/只读文案）
        denied_marker = any(m in protected_output.lower()
                            for m in ("deny", "denied", "拒绝", "保护", "只读",
                                      "read-only", "protected", "forbidden"))
        checks.append(("protected write DENIED",
                       (errored[0] is True) or denied_marker,
                       f"is_error={errored[0]} out={protected_output[:80]!r}"))

    # 正常源码写放行（不判错）
    if len(results) >= 2:
        checks.append(("normal write allowed",
                       (errored[1] is not True),
                       f"is_error={errored[1]} out={normal_output[:60]!r}"))
    return checks
