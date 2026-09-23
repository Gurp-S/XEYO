"""History Index（V2 Phase 3）—— append-only 的类型化索引 + 两级可执行 locator。

两条硬约束决定了这里的全部设计：

1. **不新增生产没有 parser 的 handle**（D1/§十二）。所有定位符都是普通
   ``Read(路径, offset=行号, limit=1)``，第二级指向 Event Store 的行号。
2. **页文件 append-only ⇒ 行号永不漂移**。事件流本身 append-only，且每个事实只在
   "产生它的那个事件"上开一行，生命周期变化**另起一行**而不是原地改写。
   Current State 允许重写，History Index 不允许——这正是 §十四要的分层。

v0 只有 4 个 namespace：requests / files / errors / tools。
原文不在这里重复：Event Store 自己就是 timeline，每行都可直接 `Read(session, offset=行号)`。
constraints、decisions 故意不做：它们没有 deterministic 来源（Phase 1/1.5 的结论），
先占个位就是把不可靠的东西伪装成可检索事实。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Iterable

from .events import (KIND_ASSISTANT_TEXT, KIND_TOOL_RESULT, KIND_TOOL_USE,
                     KIND_USER_TEXT, Event, fingerprint)

NAMESPACES = ("requests", "files", "errors", "tools")
_SUMMARY = 110
STATE_EXT = (".jsonl",)


def _summary(text: str) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= _SUMMARY else s[:_SUMMARY] + "…"


@dataclass(frozen=True)
class Record:
    ns: str
    line: int            # 页内 1-based 行号 ⇒ locator 的 offset
    event_id: str
    row: int             # Event Store（会话 jsonl）里的行号 ⇒ 第二级 locator 的 offset
    key: str
    text: str            # 页内正文（不含 `#<event_id>` 前缀）

    def page_line(self) -> str:
        return f"#{self.event_id} {self.text}"

    def read_locator(self, page: PurePosixPath | str) -> str:
        return f"Read({str(page)!r}, offset={self.line}, limit=1)"

    def raw_locator(self, session: PurePosixPath | str) -> str:
        return f"Read({str(session)!r}, offset={self.row + 1}, limit=1)"


@dataclass
class HistoryIndex:
    """append-only：同一前缀的任意扩写都以 `startnew == old` 开头（有测试守）。"""

    pages: dict[str, list[Record]] = field(
        default_factory=lambda: {n: [] for n in NAMESPACES})
    lines: dict[str, int] = field(default_factory=lambda: {n: 0 for n in NAMESPACES})
    n_events: int = 0

    def append(self, ns: str, *, event: Event, key: str, text: str) -> None:
        self.lines[ns] += 1
        self.pages[ns].append(Record(ns, self.lines[ns], event.event_id, event.index,
                                     key, text))

    def extend(self, other: "HistoryIndex") -> None:
        for ns in NAMESPACES:
            for rec in other.pages[ns]:
                self.lines[ns] += 1
                self.pages[ns].append(Record(ns, self.lines[ns], rec.event_id,
                                             rec.row, rec.key, rec.text))
        self.n_events = other.n_events

    @property
    def total_records(self) -> int:
        return sum(self.lines.values())

    def page_text(self, ns: str) -> str:
        return "\n".join(r.page_line() for r in self.pages[ns])

    def root_lines(self, index_dir: str, *, session: str = "",
                   n_rows: int = 0) -> str:
        """root 是**唯一常驻**的部分：一个类型目录 + "原文按行号自取"这一句。

        不列 timeline 页——Event Store 本身就是 timeline，且每行都可
        `Read(session, offset=行号, limit=1)`，再抄一份索引只是把 V1 的胖子重造一遍。
        """
        head = [f"index={index_dir}"]
        if session and n_rows:
            head.append(f"原文(逐行可取) Read({session!r}) 行 1-{n_rows}")
        for ns in NAMESPACES:
            n = self.lines[ns]
            if not n:
                continue
            head.append(f"{ns:<9} Read({ns}.md) 行 1-{n}")
        return "\n".join(head)

    def stats(self) -> dict[str, int]:
        out = {n: self.lines[n] for n in NAMESPACES}
        out["total"] = self.total_records
        return out


def index_events(events: Iterable[Event]) -> HistoryIndex:
    """从事件流建索引。每个事实只在"产生它的事件"上开一行，append-only。"""
    ix = HistoryIndex()
    seen_call: set[str] = set()
    for e in events:
        ix.n_events += 1
        if e.kind == KIND_USER_TEXT:
            ix.append("requests", event=e, key=fingerprint(e.text),
                      text=f"row={e.index + 1} turn={e.turn} {_summary(e.text)}")
            continue
        if e.kind == KIND_TOOL_USE:
            seen_call.add(e.call_id)
            ix.append("tools", event=e, key=e.call_id,
                      text=f"row={e.index + 1} call={e.call_id} tool={e.tool} "
                           f"{_summary(_dumps(e.inputs))}")
            for p in e.paths:
                ix.append("files", event=e, key=p.rsplit("/", 1)[-1],
                          text=f"row={e.index + 1} {p} tool={e.tool}")
            continue
        if e.kind == KIND_TOOL_RESULT and e.is_error:
            ix.append("errors", event=e, key=e.call_id or e.event_id,
                      text=f"row={e.index + 1} call={e.call_id} tool={e.tool} "
                           f"{_summary(e.text)}")
        elif e.kind == KIND_ASSISTANT_TEXT:
            pass
    return ix


def build_prefix(events: list[Event], upto_index: int) -> HistoryIndex:
    return index_events([e for e in events if e.index < upto_index])


def _dumps(v) -> str:
    try:
        return json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)[:_SUMMARY]
    except Exception:
        return repr(v)[:_SUMMARY]


def write_pages(ix: HistoryIndex, root) -> dict[str, str]:
    """把页落成真实文件（shadow/评测用；生产接线前不调用）。"""
    from pathlib import Path

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    out = {}
    for ns in NAMESPACES:
        if not ix.lines[ns]:
            continue
        p = root / f"{ns}.md"
        p.write_text(ix.page_text(ns) + "\n", encoding="utf-8")
        out[ns] = str(p)
    (root / "root.md").write_text(ix.root_lines(str(root)) + "\n", encoding="utf-8")
    out["root"] = str(root / "root.md")
    return out


def resolve_line(page_path: str, line: int) -> str | None:
    """按 Read 的语义解析一条 locator：1-based 行号，取 1 行。"""
    from pathlib import Path

    p = Path(page_path)
    if not p.exists() or line < 1:
        return None
    try:
        with p.open(encoding="utf-8") as f:
            for i, l in enumerate(f, start=1):
                if i == line:
                    return l.rstrip("\n")
    except Exception:
        return None
    return None


__all__ = ["HistoryIndex", "Record", "index_events", "build_prefix", "write_pages",
           "resolve_line", "NAMESPACES"]
