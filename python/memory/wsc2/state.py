"""CanonicalWorkingState schema v0 —— 只收"有可靠事件来源"的事实。

v0 故意不收 constraints / decisions：它们没有 deterministic 来源（见 audit 的
`unclassified_literal` 计量）。收进来就必须能回答"谁 supersede 了它"，答不出即
退化成第二种有损摘要。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

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
KIND_CONSTRAINT = "constraint"
KIND_DECISION = "decision"

FACT_KINDS = (KIND_REQUEST, KIND_FILE, KIND_TOOL_CALL, KIND_FAILURE, KIND_TODO,
              KIND_CONSTRAINT, KIND_DECISION)

#: 事实的来源档位 —— 决定"谁有资格让它退场"，不影响渲染措辞（详见 sources 的模块说明）。
AUTHORITATIVE = "authoritative"  # 运行时状态件直接持有（TodoStore / GoalStore）
DERIVED = "derived"              # 确定性推导层从转录算出
LITERAL = "literal"              # 事件原文
UNKNOWN = "unknown"              # 生命周期判不出来 ⇒ 必须渲染，永不静默丢弃
AUTHORITY_TIERS = (AUTHORITATIVE, DERIVED, LITERAL, UNKNOWN)


@dataclass
class Observation:
    """一个**路径**的读/写观测（与 V1 `FileState` 同义字段；路径级，不是版本级）。

    单独一张表而不是塞进 `Fact.value`：V1 的观测本来就是路径级的（hash 取最后一次精确读、
    stale 看最后一次观测之后有没有写），而 V2 的 file 事实是**版本级**的。把路径级观测写进
    版本级事实会造成"新版本继承旧观测"这种说不清的继承。
    """

    path: str
    observed_hash: str = ""
    last_read_index: int = -1
    read_ranges: tuple[tuple[int, int], ...] = ()
    stale: bool = False
    stale_at: int = -1
    diff_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "observed_hash": self.observed_hash,
                "last_read_index": self.last_read_index,
                "read_ranges": [list(r) for r in self.read_ranges],
                "stale": self.stale, "stale_at": self.stale_at,
                "diff_summary": self.diff_summary}

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "Observation":
        return Observation(
            path=str(d.get("path") or ""),
            observed_hash=str(d.get("observed_hash") or ""),
            last_read_index=int(d.get("last_read_index") or -1),
            read_ranges=tuple((int(a), int(b)) for a, b in d.get("read_ranges") or ()),
            stale=bool(d.get("stale")), stale_at=int(d.get("stale_at") or -1),
            diff_summary=str(d.get("diff_summary") or ""))


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
    authority: str = LITERAL

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
    #: 路径级读/写观测（`Observation.to_dict()` 形态，键 = 归一化路径）。由 reducer 的
    #: FileObserver 增量维护，projector 渲染时 join。
    obs: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: 路径触碰账：`path -> {"first": 首次事件下标, "last": 最后触碰下标, "fail": 是否失败现场}`。
    #: 与 `obs` 同类，**不是事实**：它不声称"这个文件是什么状态"，只记"这份前缀里碰过它"。
    #: 所以它不需要退场证据（V1 的解法也一样：配额 + 时效排序，见 `synaptic/paths.py`），
    #: 也就不会掉进"给事实加保质期 ⇒ 误删"那个已被实测判死的形状。
    paths: dict[str, dict[str, int]] = field(default_factory=dict)
    events_seen: int = 0
    last_event_id: str = ""
    last_event_index: int = -1

    def touch_path(self, path: str, index: int, *, failed: bool = False) -> None:
        """记一次触碰。首/末下标单调，重复触碰不产生新条目。"""
        cur = self.paths.get(path)
        if cur is None:
            self.paths[path] = {"first": int(index), "last": int(index),
                                "fail": 1 if failed else 0}
            return
        cur["last"] = max(int(cur["last"]), int(index))
        cur["first"] = min(int(cur["first"]), int(index))
        cur["fail"] = int(cur.get("fail", 0)) or (1 if failed else 0)

    def _slot(self, kind: str, key: str) -> str:
        return f"{kind}:{key}"

    def bucket(self, kind: str, key: str) -> list[str]:
        return self.index.get(self._slot(kind, key), [])

    def latest(self, kind: str, key: str) -> Fact | None:
        ids = self.bucket(kind, key)
        return self.facts[ids[-1]] if ids else None

    def history(self, kind: str, key: str) -> list[Fact]:
        return [self.facts[i] for i in self.bucket(kind, key)]

    def observation(self, path: str) -> Observation | None:
        d = self.obs.get(path)
        return Observation.from_dict(d) if d else None

    def set_observation(self, o: Observation) -> None:
        self.obs[o.path] = o.to_dict()

    def add(self, kind: str, key: str, value: dict[str, Any], *, event_id: str,
            event_index: int, evidence: str, provenance: Iterable[str] = (),
            authority: str = LITERAL) -> Fact:
        prev = self.latest(kind, key)
        version = 1 if prev is None else int(prev.version) + 1
        fact = Fact(f"f{len(self.order):05d}", kind, key, dict(value), ACTIVE,
                    event_id, event_index, event_id, event_index,
                    None, None, version, list(dict.fromkeys(provenance)) or [event_id],
                    evidence, authority)
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
                "stats": self.stats(), "observations": len(self.obs),
                "active": [f.to_dict() for f in self.active_facts()]}

    def to_jsonl_lines(self) -> list[str]:
        return [json.dumps(self.facts[i], ensure_ascii=False, default=str)
                for i in self.order]

    def obs_jsonl_lines(self) -> list[str]:
        """观测表单独一行一份：它是路径级 side-table，不是事实日志的一部分。"""
        return [json.dumps(self.obs[k], ensure_ascii=False, sort_keys=True,
                           default=str) for k in sorted(self.obs)]
