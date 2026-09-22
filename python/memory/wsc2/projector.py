"""V2 最小投影渲染（Phase 1 只用它的尺寸做对比，不接管 model input）。

段落顺序就是语义分组顺序——这里刻意不管缓存：缓存是 Transport 的事（§十三）。
"""

from __future__ import annotations

from .state import ACTIVE, Fact, WorkingState

_MAX_LITERAL = 320


def _clip(s: str) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= _MAX_LITERAL else s[:_MAX_LITERAL] + "…"


def token_len(text: str) -> int:
    """与生产同一把尺；拿不到就退回字符/4 并在报告里标口径。"""
    try:  # pragma: no cover - 取决于导入可用性
        from memory import token as _t

        for n in ("token_len", "count_tokens", "estimate_tokens", "tokens"):
            fn = getattr(_t, n, None)
            if callable(fn):
                return int(fn(text))
    except Exception:
        pass
    return max(1, len(text) // 4)


def _by_last_index(facts: list[Fact]) -> list[Fact]:
    return sorted(facts, key=lambda f: (-int(f.last_index), f.fact_id))


def sections(state: WorkingState, current_turn: int | None = None) -> list[tuple[str, list[str]]]:
    act = state.active_facts()
    reqs = [f for f in act if f.kind == "request"]
    files = [f for f in act if f.kind == "file"]
    fails = [f for f in act if f.kind == "failure"]
    pending = [f for f in act if f.kind == "tool_call"]
    todos = [f for f in act if f.kind == "todo"]

    out: list[tuple[str, list[str]]] = []
    if current_turn is None:
        current_turn = max([int(f.value.get("turn") or 0) for f in reqs], default=0)
    cur = [f for f in _by_last_index(reqs) if int(f.value.get("turn") or 0) == current_turn]
    older = [f for f in _by_last_index(reqs) if f not in cur]
    if cur:
        out.append(("CURRENT REQUEST", [_clip(f.value.get("literal")) for f in cur]))
    if older:
        out.append(("OPEN REQUESTS (lifecycle undetermined)",
                    [_clip(f.value.get("literal")) for f in older]))
    if fails:
        out.append(("UNRESOLVED", [f"{f.value.get('tool') or '?'}: "
                                   f"{_clip(f.value.get('detail'))}" for f in
                                   _by_last_index(fails)]))
    if files:
        out.append(("WORKING SET", [f"{f.key} [v{f.version}@"
                                    f"{f.created_by}]" for f in _by_last_index(files)]))
    if todos:
        out.append(("TODO", [f"[{f.value.get('todo_status')}] "
                             f"{_clip(f.value.get('literal'))}" for f in
                             _by_last_index(todos)]))
    if pending:
        out.append(("PENDING TOOLS", [f"{f.value.get('tool') or '?'} {f.key}"
                                      for f in _by_last_index(pending)]))
    return out


def render(state: WorkingState, current_turn: int | None = None) -> str:
    return "\n".join(f"[{name}]\n" + "\n".join(lines)
                     for name, lines in sections(state, current_turn))


def state_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:16]


__all__ = ["render", "sections", "token_len", "state_hash", "ACTIVE"]
