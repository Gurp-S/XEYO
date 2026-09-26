"""诊断层的身份与证据引用契约。

全部沿用运行时既有 ID：``session_id + turn_id``、``(model_request_id, attempt)``、
``tool_use.id``、审批 ``request_id``、``projection_id``。本模块不发明新主键，
只负责把审计行里同名字段的**多义**按 kind 归一（``request_id`` 在 tool.* 里是
tool_use id，在 model.* 里是模型请求 id，在 permission.* 里是审批 id）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

SCHEMA_VERSION = 1

# 归因状态：设计文档第 6 节的三档，不允许出现"绿色/通过"这类隐含结论。
CONFIRMED_FAULT = "confirmed_fault"
SUSPECTED_CAUSE = "suspected_cause"
UNKNOWN = "unknown"

# 采集完整性：只有 full 才允许声称可精确回放。
COMPLETE = "full"
PARTIAL = "partial"
REDACTED = "redacted"
EXPIRED = "expired"
ABSENT = "absent"
NOT_CAPTURED = "not_captured"


def _s(value: Any) -> str:
	return str(value if value is not None else "").strip()


#: 缺项原因码 → 中文。机器枚举只留在结构化字段里；把 ``out_of_window`` 这类内部
#: 状态名拼进正文，界面与导出报告就会把机器名投给人读的那一行。
GAP_REASON_TEXT = {
	"absent": "该来源缺失",
	"out_of_window": "超出采集窗口",
	"source_absent": "来源文件不存在",
	"not_captured": "未采集",
	"not_recorded": "该级未记账",
	"missing_evidence": "缺原始证据",
	"missing_blob": "冷层正文已不在盘上",
	"read_failed": "读取失败",
}


def gap_reason_text(reason: Any) -> str:
	text = _s(reason)
	if not text:
		return "未记录原因"
	return GAP_REASON_TEXT.get(text, f"未归类原因（{text}）")


def _f(value: Any) -> float | None:
	try:
		f = float(value)
	except (TypeError, ValueError):
		return None
	return f if f == f else None  # NaN 视为未知


def _i(value: Any) -> int | None:
	try:
		return int(value)
	except (TypeError, ValueError):
		return None


def request_key(model_request_id: str, attempt: int | None) -> str:
	"""一次**实际尝试**的键；逻辑调用用 ``model_request_id``，不得互相覆盖。"""
	rid = _s(model_request_id)
	if not rid:
		return ""
	return rid if attempt is None else f"{rid}#{int(attempt)}"


def row_turn_id(row: dict[str, Any]) -> str:
	"""轮次身份：``turn_id`` 优先，回落到 ``trace_id``（现状 trace_id=turn_id）。"""
	return _s(row.get("turn_id")) or _s(row.get("trace_id"))


@dataclass(frozen=True)
class EvidenceRef:
	"""指向原始记录的指针，不复制正文；每条结论都必须能回到这里。"""

	source: str  # audit | transcript | usage | projection | capture | job | pin | baseline | config
	locator: str  # 文件路径或存储标识（旧记录缺字段时只到文件级）
	ref_id: str = ""  # 行号 / 消息 id / request_id 等可复核定位
	detail: str = ""  # 该证据是什么（kind、role、字段名），不含正文

	def to_dict(self) -> dict[str, Any]:
		return {
			"source": self.source,
			"locator": self.locator,
			"ref_id": self.ref_id,
			"detail": self.detail,
		}

	@property
	def key(self) -> str:
		return f"{self.source}|{self.locator}|{self.ref_id}|{self.detail}"


@dataclass
class Gap:
	"""证据缺项：说明缺什么、为什么，禁止用默认值填补。

	``scope`` 区分"本轮特有"与"整个会话共有"：后者是采集姿态级事实（同一会话内要么
	每轮都在、要么每轮都不在），逐轮重复它不携带本轮信息，界面应折叠到会话级一次呈现。
	"""

	boundary: str
	reason: str  # source_absent | read_failed | out_of_window | not_captured | field_missing
	detail: str = ""
	scope: str = "per_turn"  # per_turn | session

	def to_dict(self) -> dict[str, Any]:
		return {
			"boundary": self.boundary,
			"reason": self.reason,
			"detail": self.detail,
			"scope": self.scope,
		}


@dataclass
class Finding:
	"""一条确定性规则的输出。置信度用证据等级表达，不编造概率。"""

	rule_id: str
	rule_version: int
	phenomenon: str  # 发生了什么（事实型措辞）
	boundary: str  # 全链路边界名
	component: str  # 功能归属（来自事件所在组件，不按错误文字猜文件）
	status: str  # confirmed_fault | suspected_cause | unknown
	evidence: list[EvidenceRef] = field(default_factory=list)
	impact: str = ""
	coverage_gap: str = ""  # 这条规则看不到的范围，必须写明
	allowed_conclusion: str = ""  # 允许下的结论（防越界表述）

	def to_dict(self) -> dict[str, Any]:
		return {
			"rule_id": self.rule_id,
			"rule_version": self.rule_version,
			"phenomenon": self.phenomenon,
			"boundary": self.boundary,
			"component": self.component,
			"status": self.status,
			"evidence": [e.to_dict() for e in self.evidence],
			"impact": self.impact,
			"coverage_gap": self.coverage_gap,
			"allowed_conclusion": self.allowed_conclusion,
		}


@dataclass
class Event:
	"""一条审计事件与其归一化身份。``row`` 保持原样，不改写、不补值。"""

	seq: int
	line_no: int
	kind: str
	ts: float | None
	row: dict[str, Any]
	session_id: str = ""
	turn_id: str = ""
	model_request_id: str = ""
	attempt: int | None = None
	tool_use_id: str = ""
	approval_id: str = ""
	action_id: str = ""
	projection_id: str = ""

	def ref(self, locator: str, detail: str = "") -> EvidenceRef:
		return EvidenceRef(
			source="audit",
			locator=locator,
			ref_id=f"L{self.line_no}",
			detail=detail or self.kind,
		)

	def to_dict(self, locator: str) -> dict[str, Any]:
		return {
			"seq": self.seq,
			"line_no": self.line_no,
			"kind": self.kind,
			"ts": self.ts,
			"session_id": self.session_id,
			"turn_id": self.turn_id,
			"model_request_id": self.model_request_id,
			"attempt": self.attempt,
			"tool_use_id": self.tool_use_id,
			"approval_id": self.approval_id,
			"action_id": self.action_id,
			"projection_id": self.projection_id,
			"row": dict(self.row),
			"evidence": self.ref(locator).to_dict(),
		}


def normalize_event(seq: int, line_no: int, row: dict[str, Any]) -> Event:
	"""按 kind 归一一行审计；字段缺失一律留空，不用 0 或 unknown 冒充。"""
	kind = _s(row.get("kind"))
	rid = _s(row.get("request_id"))
	model_rid = _s(row.get("model_request_id"))
	tool_use_id = ""
	approval_id = ""
	if kind.startswith("tool.") or kind.startswith("mcp.tool."):
		tool_use_id = rid
	elif kind.startswith("permission."):
		approval_id = rid
	elif kind.startswith("model.") or kind == "llm.failure":
		model_rid = model_rid or rid
	return Event(
		seq=seq,
		line_no=line_no,
		kind=kind,
		ts=_f(row.get("ts")),
		row=dict(row),
		session_id=_s(row.get("session_id")),
		turn_id=row_turn_id(row),
		model_request_id=model_rid,
		attempt=_i(row.get("attempt")),
		tool_use_id=tool_use_id,
		approval_id=approval_id,
		action_id=_s(row.get("action_id")),
		projection_id=_s(row.get("projection_id")),
	)


def dedupe_refs(refs: Iterable[EvidenceRef]) -> list[EvidenceRef]:
	seen: set[str] = set()
	out: list[EvidenceRef] = []
	for ref in refs:
		if ref.key in seen:
			continue
		seen.add(ref.key)
		out.append(ref)
	return out


__all__ = [
	"ABSENT",
	"COMPLETE",
	"CONFIRMED_FAULT",
	"EXPIRED",
	"Event",
	"EvidenceRef",
	"Finding",
	"Gap",
	"NOT_CAPTURED",
	"PARTIAL",
	"REDACTED",
	"SCHEMA_VERSION",
	"SUSPECTED_CAUSE",
	"UNKNOWN",
	"dedupe_refs",
	"normalize_event",
	"request_key",
	"row_turn_id",
]
