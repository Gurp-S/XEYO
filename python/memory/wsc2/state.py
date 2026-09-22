"""CanonicalWorkingState schema v0 —— 只收"有可靠事件来源"的事实。

v0 故意不收 constraints / decisions：它们没有 deterministic 来源（见 audit 的
`unclassified_literal` 计量）。收进来就必须能回答"谁 supersede 了它"，答不出即
退化成第二种有损摘要。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

ACTIVE = "ACTIVE"
SUPERSEDED = "SUPERSEDED"
RESOLVED = "RESOLVED"
CANCELLED = "CANCELLED"
HISTORICAL = "HISTORICAL"

STATUSES = (ACTIVE, SUPERSEDED, RESOLVED, CANCELLED, HISTORICAL)
EXITED = (SUPERSEDED, RESOLVED, CANCELLED, HISTORICAL)

KIND_REQUEST = "request"
KIND_FILE = "file"
KIND_TOOL_CALL = "tool_call"
KIND_FAILURE = "failure"
KIND_TODO = "todo"

FACT_KINDS = (KIND_REQUEST, KIND_FILE, KIND_TOOL_CALL, KIND_FAILURE, KIND_TODO)


@dataclass
class Fact:
    fact_id: str
    kind: str
    key: str
    value: dict[str, Any]
    status: str = ACTIVE
    created_by: str = ""
    created_index: int = 0
    last_event: str = ""
    last_index: int = 0
    superseded_by: str | None = None
    resolved_by: str | None = None
    version: int = 1
    provenance: list[str] = field(default_factory=list)
    evidence: str = "created"

    def active(self) -> bool:
        return self.status == ACTIVE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Delta:
    """一次 apply 产生的变化。shadow log 用它做逐事件审计。"""

    event_id: str
    event_index: int
    kind: str
    created: list[str] = field(default_factory=list)
    transitioned: list[tuple[str, str, str, str]] = field(default_factory=list)
    touched: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.created or self.transitioned or self.touched)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "index": self.event_index,
            "kind": self.kind,
            "created": self.created,
            "transitioned": [{"fact": f, "from": a, "to": b, "evidence": e}
                             for f, a, b, e in self.transitioned],
            "touched": self.touched,
        }


@dataclass
class WorkingState:
    """current truth —— 允许重写；不是 history（history 在 Event Store 里）。"""

    facts: dict[str, Fact] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    index: dict[str, list[str]] = field(default_factory=dict)
    sig_index: dict[str, list[str]] = field(default_factory=dict)
    events_seen: int = 0
    last_event_id: str = ""
    last_event_index: int = -1

    def _slot(self, kind: str, key: str) -> str:
        return f"{kind}:{key}"

    def bucket(self, kind: str, key: str) -> list[str]:
        return self.index.get(self._slot(kind, key), [])

    def latest(self, kind: str, key: str) -> Fact | None:
        ids = self.bucket(kind, key)
        return self.facts[ids[-1]] if ids else None

    def history(self, kind: str, key: str) -> list[Fact]:
        return [self.facts[i] for i in self.bucket(kind, key)]

    def add(self, kind: str, key: str, value: dict[str, Any], *, event_id: str,
            event_index: int, evidence: str, provenance: Iterable[str] = ()) -> Fact:
        prev = self.latest(kind, key)
        version = 1 if prev is None else int(prev.version) + 1
        fact = Fact(f"f{len(self.order):05d}", kind, key, dict(value), ACTIVE,
                    event_id, event_index, event_id, event_index,
                    None, None, version, list(dict.fromkeys(provenance)) or [event_id],
                    evidence)
        self.facts[fact.fact_id] = fact
        self.order.append(fact.fact_id)
        self.index.setdefault(self._slot(kind, key), []).append(fact.fact_id)
        return fact

    def transition(self, fact: Fact, to: str, *, event_id: str, event_index: int,
                   evidence: str, successor: str | None = None) -> None:
        # 只允许"证据驱动"的退场；未知状态转换一律拒绝（保守闸）。
        if to not in STATUSES or fact.status == to:
            return
        if fact.status in EXITED and to == ACTIVE:
            return
        frm = fact.status
        fact.status = to
        fact.last_event = event_id
        fact.last_index = event_index
        fact.evidence = evidence
        if to == SUPERSEDED:
            fact.superseded_by = successor
        elif to == RESOLVED:
            fact.resolved_by = successor or event_id

    def mark_used(self, fact: Fact, *, event_id: str, event_index: int) -> None:
        fact.last_event = event_id
        fact.last_index = event_index

    def active_facts(self, kinds: tuple[str, ...] = FACT_KINDS) -> list[Fact]:
        return [self.facts[i] for i in self.order
                if self.facts[i].status == ACTIVE and self.facts[i].kind in kinds]

    def stats(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        for i in self.order:
            f = self.facts[i]
            by_status[f.status] = by_status.get(f.status, 0) + 1
            by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
        return {"facts": len(self.order), "by_status": by_status, "by_kind": by_kind,
                "events_seen": self.events_seen}

    def snapshot(self) -> dict[str, Any]:
        return {"events_seen": self.events_seen, "last_event": self.last_event_id,
                "stats": self.stats(),
                "active": [f.to_dict() for f in self.active_facts()]}

    def to_jsonl_lines(self) -> list[str]:
        return [json.dumps(self.facts[i], ensure_ascii=False, default=str)
                for i in self.order]
