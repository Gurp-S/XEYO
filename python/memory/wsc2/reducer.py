"""deterministic StateReducer v0 —— 只在有明确事件证据时改变生命周期。

铁律：不明确 ⇒ KEEP。没有一条规则读工具输出文本、没有正则猜自然语言。
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from .events import (KIND_TOOL_RESULT, KIND_TOOL_USE, KIND_USER_TEXT, Event,
                     fingerprint)
from .sources import FileObserver, constraint_signals, error_sig
from .state import (ACTIVE, CANCELLED, RESOLVED, SUPERSEDED, Delta, Fact,
                    WorkingState)

_WRITE_TOOLS = frozenset({"write", "edit", "multiedit", "notebookedit", "searchreplace",
                          "strreplace", "createfile", "applypatch", "insertedit",
                          "editfile", "writefile"})
_READ_TOOLS = frozenset({"read", "readfile", "cat"})
_TODO_HINT = "todo"


def _canon(name: str) -> str:
    return "".join(ch for ch in str(name).casefold() if ch.isalnum())


def is_write_tool(name: str) -> bool:
    return _canon(name) in _WRITE_TOOLS


def is_read_tool(name: str) -> bool:
    return _canon(name) in _READ_TOOLS


def is_todo_tool(name: str) -> bool:
    return _TODO_HINT in _canon(name)


def _dumps(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return repr(value)


def call_signature(tool: str, inputs: Mapping[str, Any]) -> str:
    """同工具 + 同入参 ⇒ 同一次"尝试"。用于 failure 的 retry 判据（不含输出文本）。"""
    return fingerprint(f"{_canon(tool)}|{_dumps(inputs)}", width=16)


def _todo_items(inputs: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    out: list[Mapping[str, Any]] = []
    for val in inputs.values():
        if isinstance(val, list):
            out.extend(v for v in val if isinstance(v, Mapping))
    return out


def _todo_key(item: Mapping[str, Any]) -> str:
    for k in ("id", "content", "text", "title", "subject"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return fingerprint(v, width=14)
    return fingerprint(_dumps(item), width=14)


def _todo_status(item: Mapping[str, Any]) -> str:
    for k in ("status", "state"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip().casefold()
    for k in ("completed", "done"):
        if item.get(k) is True:
            return "completed"
    return "open"


class StateReducer:
    """state + event -> state'。增量：每条事件的工作量与该事件本身有关，与历史长度无关。"""

    def __init__(self) -> None:
        self._files = FileObserver()

    def apply(self, state: WorkingState, e: Event) -> Delta:
        d = Delta(e.event_id, e.index, e.kind)
        if e.kind == KIND_USER_TEXT:
            self._on_user_text(state, e, d)
        elif e.kind == KIND_TOOL_USE:
            self._on_tool_use(state, e, d)
        elif e.kind == KIND_TOOL_RESULT:
            self._on_tool_result(state, e, d)
        for p in self._files.on_event(e):
            o = self._files.observe(p)
            if o is not None:
                state.set_observation(o)
        state.events_seen += 1
        state.last_event_id = e.event_id
        state.last_event_index = e.index
        return d

    def _on_user_text(self, state: WorkingState, e: Event, d: Delta) -> None:
        key = fingerprint(e.text)
        prev = state.latest("request", key)
        if prev is not None:
            # 同文重发：不新增事实，只记 provenance（这就是"重复表示"的正确归处）
            if e.event_id not in prev.provenance:
                prev.provenance.append(e.event_id)
            state.mark_used(prev, event_id=e.event_id, event_index=e.index)
            prev.value["repeat"] = int(prev.value.get("repeat", 1)) + 1
            d.touched.append(prev.fact_id)
        else:
            f = state.add("request", key, {"literal": e.text.strip()[:4000], "turn": e.turn},
                          event_id=e.event_id, event_index=e.index, evidence="user_text")
            d.created.append(f.fact_id)
        # 新请求**不** supersede 旧请求：完成与否没有 deterministic 证据。
        self._on_constraints(state, e, d)

    def _on_constraints(self, state: WorkingState, e: Event, d: Delta) -> None:
        """约束走 V1 的确定性抽取器；生命周期 UNKNOWN ⇒ **只登记不淘汰**。

        没有一条规则会把 constraint 转成 SUPERSEDED/RESOLVED：一句话有没有作废判不出来
        （§十一.4），误判"已作废"会让约束从上下文里消失，代价远大于留在里面多占几行。
        """
        for sig in constraint_signals([e]):
            cur = state.latest(sig.kind, sig.key)
            if cur is not None:
                if e.event_id not in cur.provenance:
                    cur.provenance.append(e.event_id)
                state.mark_used(cur, event_id=e.event_id, event_index=e.index)
                cur.value["repeat"] = int(cur.value.get("repeat", 1)) + 1
                d.touched.append(cur.fact_id)
                continue
            f = state.add(sig.kind, sig.key, dict(sig.value),
                          event_id=e.event_id, event_index=e.index,
                          evidence=sig.evidence, provenance=sig.provenance,
                          authority=sig.authority)
            d.created.append(f.fact_id)

    def _on_tool_use(self, state: WorkingState, e: Event, d: Delta) -> None:
        if e.call_id:
            call = state.latest("tool_call", e.call_id)
            if call is None:
                f = state.add("tool_call", e.call_id,
                              {"tool": e.tool, "turn": e.turn,
                               "signature": call_signature(e.tool, e.inputs),
                               "paths": list(e.paths)},
                              event_id=e.event_id, event_index=e.index,
                              evidence="tool_use")
                d.created.append(f.fact_id)
            else:
                state.mark_used(call, event_id=e.event_id, event_index=e.index)
                d.touched.append(call.fact_id)

        if is_write_tool(e.tool):
            for p in e.paths:
                prev = state.latest("file", p)
                f = state.add("file", p, {"op": _canon(e.tool) or "write", "path": p,
                                          "turn": e.turn, "version_source": "tool_use",
                                          "hash_verified": False},
                              event_id=e.event_id, event_index=e.index,
                              evidence="write_after_write" if prev else "first_write")
                d.created.append(f.fact_id)
                if prev is not None:
                    state.transition(prev, SUPERSEDED, event_id=e.event_id,
                                     event_index=e.index, evidence="write_after_write",
                                     successor=f.fact_id)
                    d.transitioned.append((prev.fact_id, prev.status, SUPERSEDED,
                                           "write_after_write"))
        elif is_read_tool(e.tool):
            for p in e.paths:
                cur = state.latest("file", p)
                if cur is None:
                    f = state.add("file", p, {"op": "read", "path": p, "turn": e.turn,
                                              "version_source": "read",
                                              "hash_verified": False},
                                  event_id=e.event_id, event_index=e.index,
                                  evidence="first_read")
                    d.created.append(f.fact_id)
                else:
                    state.mark_used(cur, event_id=e.event_id, event_index=e.index)
                    d.touched.append(cur.fact_id)

        if is_todo_tool(e.tool):
            self._on_todo(state, e, d)

    def _on_todo(self, state: WorkingState, e: Event, d: Delta) -> None:
        items = _todo_items(e.inputs)
        if not items:
            return
        seen: set[str] = set()
        for item in items:
            key = _todo_key(item)
            seen.add(key)
            status = _todo_status(item)
            cur = state.latest("todo", key)
            if cur is not None and str(cur.value.get("todo_status")) == status:
                state.mark_used(cur, event_id=e.event_id, event_index=e.index)
                d.touched.append(cur.fact_id)
                continue
            f = state.add("todo", key, {"todo_status": status,
                                        "literal": str(item.get("content")
                                                       or item.get("text") or "")[:400],
                                        "turn": e.turn},
                          event_id=e.event_id, event_index=e.index,
                          evidence="todo_snapshot" if cur else "todo_new")
            d.created.append(f.fact_id)
            if cur is not None:
                state.transition(cur, SUPERSEDED, event_id=e.event_id,
                                 event_index=e.index, evidence="todo_snapshot",
                                 successor=f.fact_id)
                d.transitioned.append((cur.fact_id, cur.status, SUPERSEDED,
                                       "todo_snapshot"))
            if status in ("completed", "done", "cancelled", "canceled", "deleted"):
                state.transition(f, RESOLVED if status in ("completed", "done")
                                 else CANCELLED, event_id=e.event_id,
                                 event_index=e.index, evidence="todo_status_literal")
                d.transitioned.append((f.fact_id, ACTIVE, f.status,
                                       "todo_status_literal"))

    def _resolve_retried_failure(self, state: WorkingState, sig: str, *, call_id: str,
                                 event_id: str, event_index: int,
                                 d: Delta) -> None:
        """同工具+同入参的**另一次调用**成功 ⇒ 旧 failure RESOLVED。唯一的 failure 退场证据。

        两道闸都是必须的：① `f.key == call_id` 排除"同一次调用的另一条回执"——真实转录里
        见过同一 `call_id` 在同一行出现两次（一次 is_error、一次不是），放行它等于让失败
        自己把自己撤销；② `f.created_index < event_index` 要求成功回执发生在失败**之后**，
        与审计金标同一条判据。
        """
        if not sig:
            return
        for fid in state.sig_index.get(sig, []):
            f = state.facts.get(fid)
            if f is None or f.kind != "failure" or f.status != ACTIVE:
                continue
            if call_id and f.key == call_id:
                continue
            if f.created_index >= event_index:
                continue
            state.transition(f, RESOLVED, event_id=event_id, event_index=event_index,
                             evidence="identical_retry_succeeded", successor=fid)
            d.transitioned.append((f.fact_id, ACTIVE, RESOLVED,
                                   "identical_retry_succeeded"))

    def _on_tool_result(self, state: WorkingState, e: Event, d: Delta) -> None:
        call = state.latest("tool_call", e.call_id) if e.call_id else None
        if call is not None:
            state.mark_used(call, event_id=e.event_id, event_index=e.index)
            d.touched.append(call.fact_id)
            state.transition(call, RESOLVED, event_id=e.event_id, event_index=e.index,
                             evidence="tool_result_paired", successor=e.event_id)
            d.transitioned.append((call.fact_id, call.status, RESOLVED,
                                   "tool_result_paired"))
        if not e.is_error:
            if call is not None:
                self._resolve_retried_failure(
                    state, str(call.value.get("signature") or ""),
                    call_id=e.call_id, event_id=e.event_id, event_index=e.index, d=d)
            return
        tool = (str(call.value.get("tool")) if call else e.tool) or ""
        # 签名必须与 tool_use 侧同源：从 call 事实取，不重新从（未存的）入参算。
        sig = str(call.value.get("signature")) if call else fingerprint(e.event_id, 16)
        key = e.call_id or e.event_id
        prev = state.latest("failure", key)
        if prev is not None:
            state.mark_used(prev, event_id=e.event_id, event_index=e.index)
            d.touched.append(prev.fact_id)
            return
        f = state.add("failure", key, {"tool": tool, "turn": e.turn, "signature": sig,
                                       "error_sig": error_sig(e.text),
                                       "paths": list(call.value.get("paths") or [])
                                       if call else [],
                                       "detail": e.text.strip()[:400]},
                      event_id=e.event_id, event_index=e.index, evidence="is_error",
                      provenance=[e.event_id] + ([call.fact_id] if call else []))
        d.created.append(f.fact_id)
        state.sig_index.setdefault(sig, []).append(f.fact_id)


def reduce_events(events: list[Event]) -> tuple[WorkingState, list[Delta]]:
    r = StateReducer()
    s = WorkingState()
    deltas: list[Delta] = []
    for e in events:
        deltas.append(r.apply(s, e))
    return s, deltas


def reduce_prefix(events: list[Event], upto_index: int) -> WorkingState:
    """重放到"消息行号 < upto_index"为止的快照（audit 用它取逐轮状态）。"""
    r = StateReducer()
    s = WorkingState()
    for e in events:
        if e.index >= upto_index:
            break
        r.apply(s, e)
    return s
