"""One-call projection inspection; no cache survives mutable message updates."""


def inspect_projection(canonical, projected):
    memo = {}

    def inspect(message, text_needed):
        cached = memo.get(id(message))
        if cached is not None:
            return cached
        calls, results = set(), set()

        def visit(value):
            if isinstance(value, str):
                return value if text_needed else ""
            if isinstance(value, dict):
                kind = str(value.get("type") or "")
                if kind in ("tool_use", "tool_call"):
                    uid = str(value.get("id") or value.get("tool_use_id") or "")
                    if uid:
                        calls.add(uid)
                elif kind in ("tool_result", "tool_result_block"):
                    uid = str(value.get("tool_use_id") or value.get("tool_call_id") or "")
                    if uid:
                        results.add(uid)
                children = value.values()
            elif isinstance(value, list):
                children = value
            else:
                return ""
            if text_needed:
                return " ".join(visit(child) for child in children)
            for child in children:
                if isinstance(child, (dict, list)):
                    visit(child)
            return ""

        text = visit(message)
        memo[id(message)] = calls, results, text
        return calls, results, text

    projected_calls, projected_results, texts = set(), set(), []
    for message in projected:
        calls, results, text = inspect(message, True)
        projected_calls.update(calls)
        projected_results.update(results)
        texts.append(text)
    canonical_calls, canonical_results = set(), set()
    for message in canonical:
        calls, results, _ = inspect(message, False)
        canonical_calls.update(calls)
        canonical_results.update(results)
    return canonical_calls, canonical_results, projected_calls, projected_results, " ".join(texts)
