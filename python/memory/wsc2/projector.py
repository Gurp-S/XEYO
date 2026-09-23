"""V2 最小投影渲染（Phase 1 只用它的尺寸做对比，不接管 model input）。

段落顺序就是语义分组顺序——这里刻意不管缓存：缓存是 Transport 的事（§十三）。
"""

from __future__ import annotations

from .state import ACTIVE, Fact, Observation, WorkingState

_MAX_LITERAL = 320


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


def _file_line(f: Fact, obs: Observation | None) -> str:
    """路径 [版本@创建事件] + V1 `FileState` 的那几样语义（有则写，无则不占位）。"""
    line = f"{f.key} [v{f.version}@{f.created_by}]"
    if obs is None:
        return line
    if obs.observed_hash:
        line += f" hash={obs.observed_hash[:8]}"
    if obs.read_ranges:
        line += " read:" + ",".join(f"{a}-{b}" for a, b in obs.read_ranges)
    else:
        line += " read:未读"
    if obs.stale:
        line += f" STALE@{obs.stale_at}"
        if obs.diff_summary:
            line += f" diff:{_clip(obs.diff_summary, 90)}"
    elif obs.diff_summary:
        line += f" 写入:{_clip(obs.diff_summary, 90)}"
    return line


def _clip(s: str, limit: int = _MAX_LITERAL) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= limit else s[:limit] + "…"


def sections(state: WorkingState, current_turn: int | None = None) -> list[tuple[str, list[str]]]:
    act = state.active_facts()
    reqs = [f for f in act if f.kind == "request"]
    files = [f for f in act if f.kind == "file"]
    fails = [f for f in act if f.kind == "failure"]
    pending = [f for f in act if f.kind == "tool_call"]
    todos = [f for f in act if f.kind == "todo"]
    cons = [f for f in act if f.kind == "constraint"]

    out: list[tuple[str, list[str]]] = []
    if current_turn is None:
        current_turn = max([int(f.value.get("turn") or 0) for f in reqs], default=0)
    cur = [f for f in _by_last_index(reqs) if int(f.value.get("turn") or 0) == current_turn]
    older = [f for f in _by_last_index(reqs) if f not in cur]
    if cons:
        # 抽取器能确定"这句话出现过"，判不出"它还算不算数" ⇒ 段名直接写明寿命未定，
        # 让模型按事实自己权衡，而不是把它当成当前结论。
        out.append(("CONSTRAINTS (lifecycle undetermined)",
                    [_clip(f.value.get("literal")) for f in _by_last_index(cons)]))
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
        out.append(("WORKING SET", [_file_line(f, state.observation(f.key))
                                    for f in _by_last_index(files)]))
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
