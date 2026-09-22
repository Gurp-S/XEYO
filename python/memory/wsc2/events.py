"""Event Store 的只读视图：把持久化消息流摊成有序事件。

事件不新增存储——它就是 `~/.xeyo/sessions/<sid>.jsonl` 的行序（append-only、
行号即 stable event_id）。这里只做形状归一，不做任何语义判断。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

KIND_USER_TEXT = "user_text"
KIND_ASSISTANT_TEXT = "assistant_text"
KIND_TOOL_USE = "tool_use"
KIND_TOOL_RESULT = "tool_result"


def _text_of(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, Mapping):
        return str(content.get("text") or "")
    if isinstance(content, Iterable):
        out: list[str] = []
        for blk in content:
            if isinstance(blk, Mapping) and blk.get("type") in (None, "text"):
                out.append(str(blk.get("text") or ""))
        return "\n".join(s for s in out if s)
    return str(content)


def _blocks(content: Any) -> list[Mapping[str, Any]]:
    if isinstance(content, Iterable) and not isinstance(content, (str, bytes, Mapping)):
        return [b for b in content if isinstance(b, Mapping)]
    return []


def fingerprint(text: str, *, width: int = 12) -> str:
    norm = " ".join(text.split()).casefold()
    return hashlib.sha1(norm.encode("utf-8", "ignore")).hexdigest()[:width]


@dataclass(frozen=True)
class Event:
    event_id: str
    index: int
    turn: int
    kind: str
    tool: str = ""
    call_id: str = ""
    is_error: bool = False
    text: str = ""
    inputs: Mapping[str, Any] = field(default_factory=dict)
    result_for: str = ""
    paths: tuple[str, ...] = ()

    def brief(self) -> str:
        return self.text if len(self.text) <= 240 else self.text[:240] + "…"


def _norm_path(raw: Any) -> str:
    s = str(raw or "").strip().strip('"').strip("'")
    if not s:
        return ""
    s = s.replace("\\", "/")
    while "//" in s:
        s = s.replace("//", "/")
    if len(s) > 2 and s[1] == ":":
        s = s[0].lower() + s[1:]
    return s[:-1] if len(s) > 1 and s.endswith("/") else s


_PATH_KEYS = ("file_path", "path", "notebook_path", "files", "paths")


def _event_paths(inputs: Mapping[str, Any]) -> tuple[str, ...]:
    got: list[str] = []
    for key in _PATH_KEYS:
        val = inputs.get(key)
        raws: list[Any] = list(val) if isinstance(val, Iterable) and not isinstance(
            val, (str, bytes, Mapping)
        ) else [val]
        for r in raws:
            p = _norm_path(r)
            if p and p not in got:
                got.append(p)
    return tuple(got)


def _tool_rows(msg: Mapping[str, Any]) -> list[tuple[str, str, Mapping[str, Any]]]:
    """(call_id, tool_name, input) —— 兼容 Anthropic tool_use 块与 OpenAI tool_calls。"""
    out: list[tuple[str, str, Mapping[str, Any]]] = []
    for blk in _blocks(msg.get("content")):
        if blk.get("type") == "tool_use":
            inp = blk.get("input")
            out.append((str(blk.get("id") or ""), str(blk.get("name") or ""),
                        inp if isinstance(inp, Mapping) else {}))
    for call in msg.get("tool_calls") or []:
        if not isinstance(call, Mapping):
            continue
        fn = call.get("function")
        fn = fn if isinstance(fn, Mapping) else {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {"_raw": args}
        out.append((str(call.get("id") or ""), str(fn.get("name") or ""),
                    args if isinstance(args, Mapping) else {}))
    return out


def _result_rows(msg: Mapping[str, Any]) -> list[tuple[str, bool, str]]:
    """(call_id, is_error, text)。role=="tool" 行与 user 行里的 tool_result 块都算。"""
    role = str(msg.get("role") or "")
    out: list[tuple[str, bool, str]] = []
    if role == "tool":
        out.append((str(msg.get("tool_call_id") or ""), bool(msg.get("is_error")),
                    _text_of(msg.get("content"))))
    for blk in _blocks(msg.get("content")):
        if blk.get("type") == "tool_result":
            out.append((str(blk.get("tool_use_id") or ""), bool(blk.get("is_error")),
                        _text_of(blk.get("content"))))
    return out


def build_events(msgs: list[Mapping[str, Any]]) -> list[Event]:
    """行序即事件序；turn = 第几个 user 文本行之后（轮次块号，从 1 起）。"""
    events: list[Event] = []
    turn = 0
    tool_of_call: dict[str, str] = {}
    for idx, msg in enumerate(msgs):
        if not isinstance(msg, Mapping):
            continue
        role = str(msg.get("role") or "")
        for cid, name, inputs in _tool_rows(msg):
            if cid:
                tool_of_call[cid] = name
            events.append(Event(f"E{idx:05d}u{len(events):04d}", idx, turn,
                                KIND_TOOL_USE, tool=name, call_id=cid, inputs=inputs,
                                paths=_event_paths(inputs)))
        for cid, is_err, text in _result_rows(msg):
            events.append(Event(f"E{idx:05d}r{len(events):04d}", idx, turn,
                                KIND_TOOL_RESULT, tool=tool_of_call.get(cid, ""),
                                call_id=cid, is_error=is_err, text=text, result_for=cid))
        if role == "assistant":
            txt = _text_of(msg.get("content"))
            if txt.strip():
                events.append(Event(f"E{idx:05d}a{len(events):04d}", idx, turn,
                                    KIND_ASSISTANT_TEXT, text=txt))
            continue
        if role != "user":
            continue
        results = _result_rows(msg)
        used = _tool_rows(msg)
        if not results and not used:
            txt = _text_of(msg.get("content"))
            if txt.strip():
                turn += 1
                events.append(Event(f"E{idx:05d}w{len(events):04d}", idx, turn,
                                    KIND_USER_TEXT, text=txt))
    return events


def user_turn_bounds(events: list[Event]) -> dict[int, tuple[int, int]]:
    """turn -> [首事件 index, 末事件 index]（含该轮全部工具往返）。"""
    out: dict[int, list[int]] = {}
    for e in events:
        if e.turn <= 0:
            continue
        span = out.setdefault(e.turn, [e.index, e.index])
        span[0] = min(span[0], e.index)
        span[1] = max(span[1], e.index)
    return {t: (v[0], v[1]) for t, v in out.items()}
