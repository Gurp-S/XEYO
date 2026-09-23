"""Working State audit —— 金标从**原始事件流**独立算出，不复用 reducer 的记账。

为什么必须独立：如果金标也用 reducer 的产出，Active Recall 恒等于 1（循环定义）。
这里用"全转录事后视角"（retrospective activeness）：一条事实在 t 之后仍被事件引用
⇒ 它在 t 是本事实。该判据只在离线可用（生产不许偷看未来），报告里必须带上这句。
"""

from __future__ import annotations

import re
from typing import Any

from .events import KIND_TOOL_RESULT, KIND_TOOL_USE, KIND_USER_TEXT, Event, fingerprint
from .reducer import (call_signature, is_read_tool, is_todo_tool, is_write_tool,
                      _todo_items, _todo_key, _todo_status)
from .state import ACTIVE, WorkingState

OPEN_TODO = ("open", "pending", "in_progress", "doing", "active", "started")
_FUTURE = 10 ** 9


def gold(events: list[Event], t: int) -> dict[str, Any]:
    """t = "消息行号 < t 已发生"（与 reduce_prefix 同边界）。"""
    before = [e for e in events if e.index < t]
    after = [e for e in events if e.index >= t]

    # --- files：路径在 t 之后仍被引用 ⇒ t 时的当前版本仍是活事实
    seen: dict[str, int] = {}
    last_write: dict[str, int] = {}
    writes: dict[str, int] = {}
    untracked: set[str] = set()
    for e in before:
        if e.kind != KIND_TOOL_USE:
            continue
        if not (is_write_tool(e.tool) or is_read_tool(e.tool)):
            # Grep/Glob 之类也带 path：状态层 v0 不跟踪，单独计账，不混进召回率
            untracked.update(p for p in e.paths if p not in seen)
            continue
        for p in e.paths:
            seen.setdefault(p, e.index)
            if is_write_tool(e.tool):
                writes[p] = writes.get(p, 0) + 1
                last_write[p] = e.index
    later: set[str] = set()
    for e in after:
        if e.kind == KIND_TOOL_USE and (is_write_tool(e.tool) or is_read_tool(e.tool)):
            later.update(e.paths)
    files = {p: {"writes": writes.get(p, 0), "last_write_index": last_write.get(p)}
             for p in seen if p in later}
    untracked -= set(files)

    # --- failures：错误签名在 t 之后（或从未）被同签名成功重跑 ⇒ t 时仍未解决
    sig_of_call: dict[str, str] = {}
    for e in events:
        if e.kind == KIND_TOOL_USE and e.call_id:
            sig_of_call[e.call_id] = call_signature(e.tool, e.inputs)
    ok_at: dict[str, list[int]] = {}
    for e in events:
        if e.kind == KIND_TOOL_RESULT and not e.is_error:
            s = sig_of_call.get(e.call_id, "")
            if s:
                ok_at.setdefault(s, []).append(e.index)
    failures: set[str] = set()
    for e in before:
        if e.kind == KIND_TOOL_RESULT and e.is_error:
            s = sig_of_call.get(e.call_id) or f"unsolved:{e.event_id}"
            # 只有**错误之后**的同签名成功才算解决证据：命令"以前也跑成功过"不是。
            later_ok = [i for i in ok_at.get(s, ()) if i > e.index]
            if not later_ok or later_ok[0] >= t:
                failures.add(s)

    # --- requests：轮次块跨过 t ⇒ 该请求在 t 仍是"正在解决的东西"
    span_end: dict[int, int] = {}
    for e in events:
        if e.turn > 0:
            span_end[e.turn] = max(span_end.get(e.turn, -1), e.index)
    cur_req: set[str] = set()
    past_req: set[str] = set()
    for e in before:
        if e.kind != KIND_USER_TEXT:
            continue
        (cur_req if span_end.get(e.turn, -1) >= t else past_req).add(
            f"req:{fingerprint(e.text)}")

    # --- todos：t 之前最后一次快照里仍 open ⇒ 活事实（不看 t 之后的快照）
    last_snap: dict[str, tuple[int, str]] = {}
    for e in before:
        if e.kind == KIND_TOOL_USE and is_todo_tool(e.tool):
            for item in _todo_items(e.inputs):
                last_snap[_todo_key(item)] = (e.index, _todo_status(item))
    todos = {f"todo:{k}" for k, (i, st) in last_snap.items() if st in OPEN_TODO}

    pending = {e.call_id for e in before
               if e.kind == KIND_TOOL_USE and e.call_id
               and any(x.kind == KIND_TOOL_RESULT and x.call_id == e.call_id
                       and x.index >= t for x in after)}
    return {"files": files, "failures": failures, "requests": cur_req,
            "past_requests": past_req, "todos": todos, "pending": pending,
            "last_write": last_write, "untracked": sorted(untracked)[:50]}


def active_keys(state: WorkingState) -> dict[str, Any]:
    act = state.active_facts()
    reqs = [f for f in act if f.kind == "request"]
    top = max([int(f.value.get("turn") or 0) for f in reqs], default=0)
    return {
        "files": {f.key: f for f in act if f.kind == "file"},
        "failures": {str(f.value.get("signature")) for f in act
                     if f.kind == "failure"},
        "current_requests": {f"req:{f.key}" for f in reqs
                             if int(f.value.get("turn") or 0) == top},
        "archive_requests": {f"req:{f.key}" for f in reqs
                             if int(f.value.get("turn") or 0) != top},
        "todos": {f"todo:{f.key}" for f in act if f.kind == "todo"},
        "pending": {f.key for f in act if f.kind == "tool_call"},
    }


def score(events: list[Event], t: int, state: WorkingState,
          v1_text: str = "") -> dict[str, Any]:
    g = gold(events, t)
    a = active_keys(state)
    out: dict[str, Any] = {"t": t, "n_events": len(events)}

    def _pr(gs: set[str], as_: set[str], name: str) -> None:
        tp = len(gs & as_)
        out[f"{name}_gold"] = len(gs)
        out[f"{name}_active"] = len(as_)
        out[f"{name}_recall"] = (tp / len(gs)) if gs else None
        out[f"{name}_stale"] = ((len(as_) - tp) / len(as_)) if as_ else None
        out[f"{name}_missed"] = len(gs - as_)

    _pr(set(g["files"]), set(a["files"]), "file")
    _pr(g["failures"], a["failures"], "failure")
    _pr(g["requests"], a["current_requests"], "request")
    _pr(g["todos"], a["todos"], "todo")
    out["request_archive_n"] = len(a["archive_requests"])
    out["request_past_oracle_n"] = len(g["past_requests"])
    out["file_untracked_paths"] = len(g.get("untracked") or ())

    # pending 是协议不变量（配对），不是召回话题
    out["pending_oracle"] = len(g["pending"])
    out["pending_leak"] = len(a["pending"] - g["pending"])
    out["pending_lost"] = len(g["pending"] - a["pending"])

    # 版本正确性：ACTIVE 的文件事实必须正是 t 之前最后一次写入产生的那条
    checked = wrong = 0
    for p, meta in g["files"].items():
        lw = meta.get("last_write_index")
        if lw is None:
            continue
        f = a["files"].get(p)
        if f is None:
            continue
        checked += 1
        if int(f.created_index) != int(lw):
            wrong += 1
    out["file_version_checked"] = checked
    out["file_wrong_version"] = wrong

    # 同 key 只允许一条 ACTIVE（"旧值+新值同时在场"的直接反证）
    dup: dict[str, int] = {}
    for f in state.active_facts():
        dup[f"{f.kind}:{f.key}"] = dup.get(f"{f.key}:{f.kind}", 0) + 1
    out["active_duplicate_keys"] = sum(1 for k, n in dup.items() if n > 1)

    if v1_text:
        out.update(v1_metrics(v1_text, g, a))
    return out


_SEC_RE = re.compile(r"^\[([A-Z][A-Z /()·_-]{2,30})\]\s*(.*)$")


def v1_sections(text: str) -> dict[str, list[str]]:
    """生产热层的段头是**行内**的（`[CONSTRAINTS] 目标: …`），不是独占一行。

    按独占行解析会把整份头灌进 _TOP ⇒ V1 侧全部指标假零（Phase 2 第一版就是这么错的）。
    """
    out: dict[str, list[str]] = {}
    cur = "_TOP"
    for line in str(text).splitlines():
        s = line.strip()
        if not s:
            continue
        m = _SEC_RE.match(s)
        if m:
            cur = m.group(1).strip()
            out.setdefault(cur, [])
            if m.group(2).strip():
                out[cur].append(m.group(2).strip())
            continue
        out.setdefault(cur, []).append(s)
    return out


def v1_metrics(text: str, g: dict[str, Any], a: dict[str, Any]) -> dict[str, Any]:
    secs = v1_sections(text)
    lines = [l for rows in secs.values() for l in rows]
    uniq = set(lines)
    norm = " ".join(text.split()).casefold()
    out: dict[str, Any] = {
        "v1_sections": len(secs),
        "v1_lines": len(lines),
        "v1_duplicate_lines": len(lines) - len(uniq),
        "v1_duplicate_ratio": (len(lines) - len(uniq)) / len(lines) if lines else 0.0,
    }
    gf = set(g["files"])
    if gf:
        out["v1_file_recall"] = sum(
            1 for p in gf if p.casefold() in norm or
            p.rsplit("/", 1)[-1].casefold() in norm) / len(gf)
    # V1 侧"旧版本仍在场"：同一 basename 在 ≥2 个段里各占一行
    by_sec: dict[str, set[str]] = {}
    for name, rows in secs.items():
        for l in rows:
            for tok in re.findall(r"[\w./\\-]{4,}\.\w{1,5}", l):
                by_sec.setdefault(tok.rsplit("/", 1)[-1].casefold(), set()).add(name)
    out["v1_multi_section_paths"] = sum(1 for v in by_sec.values() if len(v) >= 2)
    out["v1_path_tokens_seen"] = len(by_sec)
    return out


def category_flags(events: list[Event]) -> dict[str, Any]:
    """representative turns 的 deterministic 抽样判据（对齐 §八清单）。"""
    uses = [e for e in events if e.kind == KIND_TOOL_USE]
    results = [e for e in events if e.kind == KIND_TOOL_RESULT]
    wrote = {p for e in uses if is_write_tool(e.tool) for p in e.paths}
    errs = [e for e in results if e.is_error]
    wrote_multi: dict[str, int] = {}
    for e in uses:
        if is_write_tool(e.tool):
            for p in e.paths:
                wrote_multi[p] = wrote_multi.get(p, 0) + 1
    reqs = [e for e in events if e.kind == KIND_USER_TEXT]
    return {
        "multi_turn_user": len(reqs) >= 3,
        "multi_file_edit": len(wrote) >= 3,
        "tool_failure": bool(errs),
        "failure_then_retry": bool(errs) and len(uses) > 6,
        "todo_lifecycle": any(is_todo_tool(e.tool) for e in uses),
        "long_session": len(uses) >= 30,
        "superseded_file": any(n > 1 for n in wrote_multi.values()),
        "many_unresolved": len(errs) >= 3,
        "resumed": bool(events) and events[0].kind != KIND_USER_TEXT,
        "turn_count": len({e.turn for e in events if e.turn > 0}),
        "orphan_results": len([r for r in results if not any(
            u.call_id == r.call_id for u in uses)]),
    }


__all__ = ["gold", "active_keys", "score", "v1_sections", "v1_metrics",
           "category_flags", "OPEN_TODO"]
