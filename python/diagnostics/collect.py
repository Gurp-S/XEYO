"""按既有身份把散落的证据合并成一个运行视图。

只做有界 join，不复制权威数据：审计行、transcript 行、usage 行都以「指针 +
原始字段」的形式呈现，缺项一律记 ``Gap``，绝不用 0 / unknown 冒充观测值。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from diagnostics.identity import (
	ABSENT,
	COMPLETE,
	NOT_CAPTURED,
	PARTIAL,
	SCHEMA_VERSION,
	Event,
	EvidenceRef,
	Gap,
	gap_reason_text,
	normalize_event,
	request_key,
	_s,
)
from diagnostics import store


def _env_bytes(name: str, default: int) -> int:
	try:
		return max(4096, int(os.environ.get(name, "").strip() or default))
	except ValueError:
		return default


_AUDIT_TAIL_BYTES = _env_bytes("XEYO_DIAGNOSTICS_AUDIT_BYTES", 4 * 1024 * 1024)
# 尾窗没盖到本轮时的第二次读取上限：只在"本轮一行都没扫到"的分支上付费。
# 实测（2026-09-25，本机 11.3 MiB / 38 550 行审计文件）整份重扫 0.16s、尾窗 0.06s。
_AUDIT_WIDEN_BYTES = _env_bytes("XEYO_DIAGNOSTICS_AUDIT_WIDEN_BYTES", 64 * 1024 * 1024)
_TRANSCRIPT_ROW_CAP = 400

# 全链路边界（设计文档第 4 节的表）。名字是稳定主键，标签只用于展示。
BOUNDARIES: tuple[tuple[str, str], ...] = (
	("user_request", "用户请求 / 接收"),
	("resume_schedule", "会话恢复与调度"),
	("instruction_context", "指令与上下文"),
	("wsc_fold", "WSC 折叠"),
	("adapter", "适配器最终请求"),
	("model_request", "模型请求与响应"),
	("tool_permission", "工具与权限"),
	("background_job", "后台任务"),
	("file_verifier", "文件与验收"),
	("sse_gui", "SSE / 界面"),
)

# 会话级采集限制：这些缺项由"整个会话的窗/账本/采集姿态"决定，在同一会话内要么每轮都在、
# 要么每轮都不在，逐轮重复只会把本轮真特有的缺项淹成噪声。
#
# 判据不是"总体占比高"（那是错的轴），而是**逐会话测得全有或全无（PARTIAL==0）**。
# 实测（2026-09-26，540 真实轮 / 316 会话，只读）：下列 12 条 (边界, 原因) 在 316 个会话里
# PARTIAL 均为 0（有的会话全有、有的全无，但绝不在同一会话内忽有忽无）；它们都从会话级的
# 窗口截断 / 账本缺失 / 未开启采集 推出，与具体轮次无关。
#
# 反向证据（真·随轮变化，刻意不折叠）：file_verifier/field_missing PARTIAL=3、
# instruction_context/not_comparable PARTIAL=4 —— 同一会话内有的轮有、有的轮没有，是本轮事实。
# 频率低不代表会随轮变，PARTIAL>0 才代表会；这两条是"按判据而非按频率筛"的活样本。
SESSION_CONSTANT_GAPS: frozenset[tuple[str, str]] = frozenset(
	{
		("adapter", "not_captured"),
		("adapter", "source_absent"),
		("file_verifier", "not_captured"),
		("file_verifier", "not_recorded"),
		("file_verifier", "out_of_window"),
		("wsc_fold", "no_records"),
		("instruction_context", "no_records"),
		("instruction_context", "out_of_window"),
		("instruction_context", "recovered_outside_window"),
		("model_request", "out_of_window"),
		("model_request", "recovered_outside_window"),
		("model_request", "unattributed_rows"),
		("wsc_fold", "unattributed_rows"),
	}
)

_BOUNDARY_OF_KIND: tuple[tuple[str, str], ...] = (
	("permission.", "tool_permission"),
	("model.", "model_request"),
	("llm.failure", "model_request"),
	("tool.", "tool_permission"),
	("mcp.tool.", "tool_permission"),
	("mcp.server.", "tool_permission"),
	("notice.channel", "sse_gui"),
	("stream.gap", "sse_gui"),
	("config.invalid", "instruction_context"),
	("policy.invalid", "instruction_context"),
	("bash_rules.invalid", "instruction_context"),
	("memory.aging.", "wsc_fold"),
	("title.enhance", "sse_gui"),
)


def boundary_of(kind: str) -> str:
	for prefix, name in _BOUNDARY_OF_KIND:
		if kind.startswith(prefix):
			return name
	return "instruction_context"


@dataclass
class Window:
	"""一次有界扫描的覆盖情况。

	「来源不存在」「尾窗截断」「整份读完」是三件不同的事，各自有字段；
	把前两件混成一件会让报告在根本没有东西可截断时声称窗口太小。
	读到了却被丢弃的行同样按原因分开计数——任何一类非零都不允许再写「完整」。
	"""

	source: str
	locator: str = ""
	complete: bool = False
	rows_scanned: int = 0
	rows_matched: int = 0
	bytes_read: int = 0
	note: str = ""
	# 来源本身是否存在（文件 / 快照拿不到 ≠ 截断）。
	present: bool = True
	# 尾窗是否真的把窗口之前的内容排除在外。
	truncated: bool = False
	# 窗口之外的物理行数：只有截断时才有值。
	rows_outside_window: int = 0
	# 窗口内读到但没能带进载荷的行，按原因分开计数。
	rows_unparsable: int = 0
	rows_unattributed: int = 0
	rows_capped: int = 0
	# 归因到别处（其他会话 / 其他轮次）的行：属于正常过滤，不算丢证据。
	rows_other_session: int = 0
	rows_other_turn: int = 0

	def add_note(self, text: str) -> None:
		"""把多条事实拼进同一个说明字段；空串不产生分隔符。"""
		chunk = _s(text)
		if not chunk:
			return
		self.note = f"{self.note}；{chunk}" if self.note else chunk

	@property
	def rows_dropped(self) -> int:
		"""确实被丢弃 / 未带进载荷的行数（截断另由 ``truncated`` 表达）。"""
		return self.rows_unparsable + self.rows_unattributed + self.rows_capped

	def to_dict(self) -> dict[str, Any]:
		return {
			"source": self.source,
			"locator": self.locator,
			"complete": self.complete,
			"present": self.present,
			"truncated": self.truncated,
			"rows_scanned": self.rows_scanned,
			"rows_matched": self.rows_matched,
			"rows_outside_window": self.rows_outside_window,
			"rows_unparsable": self.rows_unparsable,
			"rows_unattributed": self.rows_unattributed,
			"rows_other_session": self.rows_other_session,
			"rows_other_turn": self.rows_other_turn,
			"rows_capped": self.rows_capped,
			"bytes_read": self.bytes_read,
			"note": self.note,
		}


@dataclass
class ModelRequest:
	model_request_id: str
	provider: str = ""
	model: str = ""
	turn_id: str = ""
	projection_id: str = ""
	attempts: list[dict[str, Any]] = field(default_factory=list)
	tool_use_ids: list[str] = field(default_factory=list)
	usage_by_attempt: dict[str, dict[str, Any]] = field(default_factory=dict)
	capture: dict[str, Any] | None = None
	evidence: list[EvidenceRef] = field(default_factory=list)

	def attempt_ids(self) -> list[str]:
		"""去重后的尝试序列：started/finished 两行同属一次尝试。"""
		seen: list[str] = []
		for att in self.attempts:
			key = request_key(self.model_request_id, att.get("attempt"))
			if key and key not in seen:
				seen.append(key)
		return seen

	def to_dict(self) -> dict[str, Any]:
		return {
			"model_request_id": self.model_request_id,
			"provider": self.provider,
			"model": self.model,
			"turn_id": self.turn_id,
			"projection_id": self.projection_id,
			"attempts": list(self.attempts),
			"attempt_keys": self.attempt_ids(),
			"tool_use_ids": list(self.tool_use_ids),
			"usage_by_attempt": dict(self.usage_by_attempt),
			"capture": dict(self.capture) if self.capture else None,
			"evidence": [e.to_dict() for e in self.evidence],
		}


@dataclass
class ToolCall:
	tool_use_id: str
	tool_name: str = ""
	turn_id: str = ""
	model_request_id: str = ""
	projection_id: str = ""
	action_id: str = ""
	started: dict[str, Any] | None = None
	finished: dict[str, Any] | None = None
	approval_ids: list[str] = field(default_factory=list)
	result_message_id: str = ""
	is_error: bool | None = None
	error_kind: str = ""
	evidence: list[EvidenceRef] = field(default_factory=list)

	@property
	def paired(self) -> bool:
		return self.started is not None and self.finished is not None

	def to_dict(self) -> dict[str, Any]:
		return {
			"tool_use_id": self.tool_use_id,
			"tool_name": self.tool_name,
			"turn_id": self.turn_id,
			"model_request_id": self.model_request_id,
			"projection_id": self.projection_id,
			"action_id": self.action_id,
			"started": dict(self.started) if self.started else None,
			"finished": dict(self.finished) if self.finished else None,
			"paired": self.paired,
			"approval_ids": list(self.approval_ids),
			"result_message_id": self.result_message_id,
			"is_error": self.is_error,
			"error_kind": self.error_kind,
			"evidence": [e.to_dict() for e in self.evidence],
		}


@dataclass
class RunEvidence:
	session_id: str
	turn_id: str
	generated_at: float = field(default_factory=lambda: time.time())
	events: list[Event] = field(default_factory=list)
	model_requests: list[ModelRequest] = field(default_factory=list)
	tool_calls: list[ToolCall] = field(default_factory=list)
	permissions: list[dict[str, Any]] = field(default_factory=list)
	projections: list[dict[str, Any]] = field(default_factory=list)
	transcript_rows: list[dict[str, Any]] = field(default_factory=list)
	usage_rows: list[dict[str, Any]] = field(default_factory=list)
	fold_rows: list[dict[str, Any]] = field(default_factory=list)
	wire_drops: list[dict[str, Any]] = field(default_factory=list)
	captures: list[dict[str, Any]] = field(default_factory=list)
	jobs: list[dict[str, Any]] = field(default_factory=list)
	pins: list[dict[str, Any]] = field(default_factory=list)
	working: dict[str, Any] = field(default_factory=dict)
	windows: list[Window] = field(default_factory=list)
	gaps: list[Gap] = field(default_factory=list)
	notes: list[str] = field(default_factory=list)

	# ---------- 查询辅助（规则层用） ----------

	def by_kind(self, *prefixes: str) -> list[Event]:
		return [e for e in self.events if e.kind.startswith(prefixes)]

	def events_for_turn(self) -> list[Event]:
		if not self.turn_id:
			return list(self.events)
		return [e for e in self.events if e.turn_id == self.turn_id]

	def window(self, source: str) -> Window | None:
		for w in self.windows:
			if w.source == source:
				return w
		return None

	def add_gap(self, boundary: str, reason: str, detail: str = "") -> Gap:
		scope = "session" if (boundary, reason) in SESSION_CONSTANT_GAPS else "per_turn"
		gap = Gap(boundary=boundary, reason=reason, detail=detail, scope=scope)
		self.gaps.append(gap)
		return gap

	# ---------- 序列化 ----------

	def coverage(self) -> dict[str, Any]:
		"""每个来源的覆盖三态：来源不存在才是 absent，读到东西就谈不上 absent。"""
		out: dict[str, Any] = {}
		for w in self.windows:
			if not w.present:
				state = ABSENT
			elif w.complete:
				state = COMPLETE
			else:
				state = PARTIAL
			out[w.source] = {
				"state": state,
				"complete": w.complete,
				"present": w.present,
				"truncated": w.truncated,
				"rows": w.rows_matched,
				"rows_scanned": w.rows_scanned,
				"rows_unparsable": w.rows_unparsable,
				"rows_unattributed": w.rows_unattributed,
				"rows_capped": w.rows_capped,
				"locator": w.locator,
				"note": w.note,
			}
		return out

	def boundaries(self) -> list[dict[str, Any]]:
		"""每个边界是否有证据、有哪些证据；不推断"没记录=没发生"。"""
		scoped = self.events_for_turn()
		out: list[dict[str, Any]] = []
		for name, label in BOUNDARIES:
			refs: list[EvidenceRef] = []
			notes: list[str] = []
			if name == "model_request":
				refs = [r for m in self.model_requests for r in m.evidence]
				if any(m.capture for m in self.model_requests):
					notes.append("含适配器捕获引用")
			elif name == "tool_permission":
				refs = [r for t in self.tool_calls for r in t.evidence]
				refs += [
					EvidenceRef("audit", ref.locator, ref.ref_id, "permission")
					for p in self.permissions
					for ref in p.get("_refs", [])
				]
			elif name == "instruction_context":
				refs = [
					EvidenceRef("projection", str(p.get("locator", "")), _s(p.get("projection_id")), "manifest")
					for p in self.projections
				]
			elif name == "wsc_fold":
				refs = [
					EvidenceRef("usage", str(f.get("locator", "")), _s(f.get("event_id")), "fold")
					for f in self.fold_rows
				]
			elif name == "adapter":
				refs = [
					EvidenceRef("capture", _s(c.get("locator", "")), _s(c.get("body_hash")), "request_body")
					for c in self.captures
				]
			elif name == "background_job":
				refs = [
					EvidenceRef("job", _s(j.get("locator", "")), _s(j.get("job_id")), "job")
					for j in self.jobs
				]
			elif name == "file_verifier":
				# 验收记录只有 pins 一条来源（diagnostics.pins.record_verifier，由 CLI / 界面提交）。
				# 这里原先看的是 transcript 行的 ``note_kind == "verifier"``，而 note_kind 的取值
				# 只有 ``state`` / ``event``（prompt/pre_llm_inject 的管道标记），全仓库没有生产者
				# ⇒ 已经落盘的验收也被报成"该边界无记录"，而同一份报告的责任划分那句"已验收"
				# 正是从这条 pin 读的。
				refs = [
					EvidenceRef("pin", _s(p.get("locator", "")), _s(p.get("pin_id")), "verifier")
					for p in self.pins
					if _s(p.get("kind")) == "verifier"
				]
			elif name == "sse_gui":
				refs = [e.ref("") for e in scoped if e.kind in {"notice.channel", "title.enhance.applied"}]
			else:
				refs = [e.ref("") for e in scoped if boundary_of(e.kind) == name]
			for g in self.gaps:
				if g.boundary == name:
					notes.append(f"{gap_reason_text(g.reason)}：{g.detail}".strip("："))
			out.append(
				{
					"name": name,
					"label": label,
					"present": bool(refs),
					"evidence": [r.to_dict() for r in refs[:40]],
					"evidence_count": len(refs),
					"notes": notes,
				}
			)
		return out

	def to_dict(self, *, include_rows: bool = True) -> dict[str, Any]:
		locator = _audit_locator()
		doc: dict[str, Any] = {
			"schema_version": SCHEMA_VERSION,
			"session_id": self.session_id,
			"turn_id": self.turn_id,
			"generated_at": round(self.generated_at, 3),
			"coverage": self.coverage(),
			"boundaries": self.boundaries(),
			"identity": {
				"model_request_ids": [m.model_request_id for m in self.model_requests],
				"attempt_keys": [k for m in self.model_requests for k in m.attempt_ids() if k],
				"tool_use_ids": [t.tool_use_id for t in self.tool_calls],
				"approval_ids": [_s(p.get("request_id")) for p in self.permissions],
				"projection_ids": [_s(p.get("projection_id")) for p in self.projections],
			},
			"model_requests": [m.to_dict() for m in self.model_requests],
			"tool_calls": [t.to_dict() for t in self.tool_calls],
			"permissions": [{k: v for k, v in p.items() if k != "_refs"} for p in self.permissions],
			"projections": self.projections,
			"usage": self.usage_rows,
			"folds": self.fold_rows,
			"wire_drops": self.wire_drops,
			"captures": self.captures,
			"jobs": self.jobs,
			"pins": self.pins,
			"working": self.working,
			"windows": [w.to_dict() for w in self.windows],
			"gaps": [g.to_dict() for g in self.gaps],
			"notes": self.notes,
			"versions": store.code_version(),
		}
		if include_rows:
			doc["events"] = [e.to_dict(locator) for e in self.events_for_turn()]
			doc["transcript"] = [
				{k: v for k, v in row.items() if k != "content"} | {"has_content": "content" in row}
				for row in self.transcript_rows
			]
		return doc


def _audit_locator() -> str:
	from audit.log import default_audit_log

	try:
		return str(default_audit_log().path)
	except Exception:  # noqa: BLE001 — 定位符失败不影响合并
		return "audit:unavailable"


@dataclass
class _TailScan:
	"""一次尾窗扫描的原始事实：拿到哪些行、丢了几行、来源到底存不存在。"""

	rows: list[tuple[int, dict[str, Any]]] = field(default_factory=list)
	bytes_read: int = 0
	present: bool = True
	truncated: bool = False
	rows_scanned: int = 0
	rows_outside_window: int = 0
	rows_unparsable: int = 0


def _scan_jsonl_tail(path: Path, max_bytes: int) -> _TailScan:
	"""从文件尾读至多 ``max_bytes``，给出窗口内的 ``(物理行号, dict)`` 与丢弃计数。

	行号一律是**物理行号**：按 ``b"\\n"`` 切行。绝不能用 ``str.splitlines()``——
	它连 U+0085、\\x0b、\\x0c、\\x1c-\\x1e 也算换行，而这些字符可以合法地出现在
	JSON 字符串正文里（实测 transcript 里的 ELF 十六进制转储就带 U+0085），
	一行被劈成两半后既少一行、又让之后所有证据指针 L<n> 集体错位。

	文件不存在与截断是两件事：这里分开表达（``present`` / ``truncated``）。
	"""
	scan = _TailScan()
	if not path.is_file():
		scan.present = False
		return scan
	size = path.stat().st_size
	first_line_no = 1
	with path.open("rb") as handle:
		if size > max_bytes:
			handle.seek(size - max_bytes)
			handle.readline()  # 丢弃可能被切断的首行
			offset = handle.tell()
			raw = handle.read()
			scan.truncated = True
			# 行号必须和物理行一致，否则证据指针指向别处；只数窗口前的换行。
			handle.seek(0)
			first_line_no = handle.read(offset).count(b"\n") + 1
			scan.rows_outside_window = first_line_no - 1
		else:
			raw = handle.read()
	scan.bytes_read = len(raw)
	for index, chunk in enumerate(raw.split(b"\n")):
		line = chunk.strip()
		if not line:
			continue
		scan.rows_scanned += 1
		try:
			row = json.loads(line.decode("utf-8", "replace"))
		except ValueError:
			scan.rows_unparsable += 1
			continue
		if not isinstance(row, dict):
			scan.rows_unparsable += 1
			continue
		scan.rows.append((first_line_no + index, row))
	return scan


def _tail_jsonl(path: Path, max_bytes: int) -> tuple[list[tuple[int, dict[str, Any]]], int, bool]:
	"""``_scan_jsonl_tail`` 的三值视角：行、字节、**是否真的截断**。

	文件不存在时 truncated 为 False——没有内容可截断；旧实现返回 True，
	于是每个运行详情都把「本机没有这个文件」说成「尾窗太小、覆盖不全」。
	"""
	scan = _scan_jsonl_tail(path, max_bytes)
	return scan.rows, scan.bytes_read, scan.truncated


def _window_from_scan(source: str, locator: str, scan: _TailScan, *, max_bytes: int) -> Window:
	"""把一次扫描落成 Window：absent / truncated / full 三态各自有措辞与字段。"""
	window = Window(
		source=source,
		locator=locator,
		bytes_read=scan.bytes_read,
		present=scan.present,
		truncated=scan.truncated,
		rows_scanned=scan.rows_scanned,
		rows_outside_window=scan.rows_outside_window,
		rows_unparsable=scan.rows_unparsable,
	)
	if not scan.present:
		window.complete = False
		window.add_note(f"{locator or source} 不存在：没有可扫描的记录，非尾窗截断")
	elif scan.truncated:
		window.complete = False
		window.add_note(
			f"尾窗截断：{source} 只读最近 {max_bytes} 字节，覆盖窗口内 {scan.rows_scanned} 行，"
			f"更早的 {scan.rows_outside_window} 行未覆盖"
		)
	else:
		window.complete = True
	return window


def _seal_window(window: Window) -> Window:
	"""收尾：丢过证据的来源不得声称完整。

	「没发现异常」只有在证据没被扔掉时才有意义，所以只要 ``rows_dropped``
	非零就把状态从 full 降级并写明原因，而不是让 complete 继续为真。
	"""
	if window.rows_unparsable:
		window.add_note(f"{window.rows_unparsable} 行读到了却解不出 JSON 对象，已丢弃")
	if window.rows_dropped:
		window.complete = False
	return window


def _publish_window(run: RunEvidence, window: Window) -> Window:
	"""每个来源共用同一道收尾：先按丢行情况降级，再进窗口列表。"""
	window = _seal_window(window)
	run.windows.append(window)
	return window


# ---------- 采集 ----------


def _scan_has_turn(scan: _TailScan, session_id: str, turn_id: str) -> bool:
	"""窗口里有没有**本会话**这一轮的行（只看身份字段，不做归因、不改载荷）。

	身份空白的行不算：评测/模拟器直写的行不带 session_id，turn_id 却常在 1、2
	这种小值上和在跑的会话撞号（真实账本里 122 行是这个形状）。把它们当作"本轮
	已在窗内"会跳过扩窗，于是本会话真正的那一行永远读不到——而这一判定直接决定
	后面能不能说"本轮无记录"。
	"""
	if not turn_id:
		return True
	if not session_id:
		# 没有可比身份就不许声称"窗内已有"：宁可多扩一次窗，也不把读不出说成没有。
		return False
	for _, row in scan.rows:
		if _s(row.get("turn_id")) != turn_id:
			continue
		if _s(row.get("session_id")) == session_id:
			return True
	return False


def _collect_audit(run: RunEvidence, *, session_id: str, turn_id: str, path: Path, max_bytes: int) -> None:
	locator = str(path)
	audit_bytes = max_bytes
	scan = _scan_jsonl_tail(path, audit_bytes)
	if not scan.present:
		# 没有审计文件不是「窗口太小」：两者是不同的事实，措辞也必须不同。
		run.add_gap("instruction_context", "source_absent", f"审计文件不存在：{locator}")
		_publish_window(run, _window_from_scan("audit", locator, scan, max_bytes=audit_bytes))
		return
	if turn_id and scan.truncated and not _scan_has_turn(scan, session_id, turn_id):
		# 尾窗没扫到本轮 ⇒ 先扩窗读完，再决定要不要下"本轮无记录"的结论。
		# 分层普查 57 个真实轮次里 11 轮（19%）属于这一类：它们的行确实都在文件里，
		# 只是排在 4 MiB 之外（最近的也在第 7 338 行以外）。不扩窗时这 19% 永远只能
		# 得到"本轮无记录"，而扩一次窗只多花 0.1s。
		wide = _scan_jsonl_tail(path, max(audit_bytes, _AUDIT_WIDEN_BYTES))
		found = _scan_has_turn(wide, session_id, turn_id)
		audit_bytes = max(audit_bytes, _AUDIT_WIDEN_BYTES)
		run.add_gap(
			"instruction_context",
			"recovered_outside_window" if found else "not_found_in_full_file",
			(
				f"audit 尾窗 {max_bytes} 字节没盖到本轮，扩到 {audit_bytes} 字节后读到（扫描 {wide.rows_scanned} 行）"
				if found
				else f"audit 已读完 {audit_bytes} 字节上限（扫描 {wide.rows_scanned} 行）仍未见 turn_id={turn_id} 的行"
			),
		)
		scan = wide
	window = _window_from_scan("audit", locator, scan, max_bytes=audit_bytes)
	matched = 0
	for line_no, row in scan.rows:
		row_session = _s(row.get("session_id"))
		if session_id and row_session != session_id:
			if not row_session:
				window.rows_unattributed += 1  # 旧格式行：谁也不是，只能记数
			else:
				window.rows_other_session += 1
			continue
		event = normalize_event(matched, line_no, row)
		matched += 1
		if turn_id and event.turn_id and event.turn_id != turn_id:
			# 权限/工具事件可能只带 trace_id；turn_id 未知的行保留为上下文，不参与轮次归因。
			window.rows_other_turn += 1
			continue
		run.events.append(event)
	window.rows_matched = matched
	if window.rows_unattributed:
		window.add_note(
			f"{window.rows_unattributed} 行 session_id 为空（旧审计格式，或评测/模拟器直接写入），"
			"无法归入本会话，未补值"
		)
	if window.rows_other_session:
		window.add_note(f"{window.rows_other_session} 行属于其他会话，未并入本运行")
	if window.rows_other_turn:
		window.add_note(f"{window.rows_other_turn} 行属于本会话的其他轮次，未并入本运行")
	_seal_window(window)
	run.windows.append(window)
	if scan.truncated:
		run.add_gap(
			"instruction_context",
			"out_of_window",
			f"audit 尾窗 {audit_bytes} 字节，仅覆盖最近 {window.rows_scanned} 行，"
			f"窗口外更早的 {window.rows_outside_window} 行未读",
		)


def _collect_working(run: RunEvidence, session_id: str) -> None:
	"""投影 manifest / 冻结前缀计量来自会话 working 快照（只有最后一份，须说明）。"""
	try:
		from memory.working import hydrate

		snap = hydrate(session_id)
	except Exception:  # noqa: BLE001 — 观测不可用只记缺项
		run.windows.append(Window(source="working", complete=False, present=False, note="hydrate 失败：working 快照读不出来"))
		run.add_gap("instruction_context", "read_failed", "working 快照不可读")
		return
	manifest = getattr(snap, "last_projection_manifest", None)
	digest = getattr(snap, "last_projection", None)
	checkpoint = getattr(snap, "compact_checkpoint", None)
	run.working = {
		"session_id": _s(getattr(snap, "session_id", session_id)),
		"compact_cursor": int(getattr(snap, "compact_cursor", 0) or 0),
		"c1_frozen_until": int(getattr(snap, "c1_frozen_until", 0) or 0),
		"turns_since_c2": int(getattr(snap, "turns_since_c2", 0) or 0),
		"last_action": _s(getattr(snap, "last_action", "")),
		"agent_mode": _s(getattr(snap, "agent_mode", "")),
		"locator": str(_working_locator(session_id)),
	}
	if isinstance(manifest, dict) and manifest:
		run.projections.append(dict(manifest) | {"locator": run.working["locator"], "scope": "last_only"})
	if digest is not None:
		run.working["last_projection"] = {
			"prefix_hash": _s(getattr(digest, "prefix_hash", "")),
			"total_len": int(getattr(digest, "total_len", 0) or 0),
			"frozen_len": int(getattr(digest, "frozen_len", 0) or 0),
			"tail_len": int(getattr(digest, "tail_len", 0) or 0),
		}
	if checkpoint is not None:
		chain = getattr(checkpoint, "window_chain", None) or []
		# 整条带给规则：每条只有三个整数（cursor/frozen_until/summary_fp），实测最长
		# 116 条（50 个真实会话）。原先切 [-50:]，冻结前缀规则于是只核对最后 50 条
		# 却照发"不变量失败/通过"的结论 —— 更长的链里最早那一段违规被静默丢掉。
		chain_rows = [dict(w) for w in chain if isinstance(w, dict)]
		run.working["compact_checkpoint"] = {
			"anchor_cursor": int(getattr(checkpoint, "anchor_cursor", 0) or 0),
			"anchor_frozen_until": int(getattr(checkpoint, "anchor_frozen_until", 0) or 0),
			"window_chain": chain_rows,
			"window_chain_total": len(chain_rows),
			"summary_fp": _s((chain[-1] if chain else {}) or {}).strip()[:16] if chain else "",
		}
	run.windows.append(
		Window(
			source="working",
			locator=run.working.get("locator", ""),
			complete=False,
			rows_matched=len(run.projections),
			note="working 只保留最后一份 manifest；历史投影需靠审计 projection_id 关联",
		)
	)
	manifest_id = _s(run.projections[0].get("projection_id")) if run.projections else ""
	turn_projection_ids = {
		_s(event.row.get("projection_id")) for event in run.events_for_turn() if _s(event.row.get("projection_id"))
	}
	if manifest_id and manifest_id not in turn_projection_ids:
		# 本轮没有属于自己的投影判据这件事要说出来：规则层会因此不出投影结论，
		# 读者需要知道那是"拿不到本轮的那一份"，不是"本轮查过没问题"。
		# 原因名用 not_comparable：这里字段是在的（manifest 存在），缺的是
		# "它属于哪一轮"的粒度 —— 叫 field_missing 会让界面说成"记录里缺该字段"。
		run.add_gap(
			"instruction_context",
			"not_comparable",
			f"working 只有本会话最后一份 manifest（projection_id={manifest_id[:12]}），"
			"它不是本轮提交的那一份：本轮没有可核对的投影判据，规则层不会用别轮的投影顶替。",
		)
	elif not manifest_id:
		# 快照里连一份 manifest 都没有：这是"这个来源对本会话没有记录行"，
		# 不是"记录里缺字段"（field_missing 在界面上就是后者）。
		run.add_gap(
			"instruction_context",
			"no_records",
			"working 快照里没有 last_projection_manifest：本运行的投影结构无从核对。",
		)
	# 本轮的投影判据在手时不再补任何缺项：working 窗口已经写明"只保留最后一份
	# manifest"这条采集范围事实，逐轮再挂一条 field_missing 是 540/540 的恒真噪音。


def _working_locator(session_id: str) -> Path:
	try:
		from memory.working import path_for

		return path_for(session_id)
	except Exception:  # noqa: BLE001
		return Path("sessions/<session>.working.json")


def _collect_usage(run: RunEvidence, session_id: str) -> None:
	"""读用量账本进 ``run.usage_rows``：per-attempt 费用由它喂给挂载步骤。"""
	try:
		from usage.ledger import events_path
	except Exception:  # noqa: BLE001
		run.add_gap("model_request", "source_absent", "usage 账本不可导入")
		return
	path = events_path()
	usage_bytes = _AUDIT_TAIL_BYTES
	scan = _scan_jsonl_tail(path, usage_bytes)
	if scan.present and scan.truncated and run.model_requests:
		# "这一枪没有用量账"是一句关于**整份账本**的话：只读了 61% 就没资格断言。
		# 与审计同法，在读到截断且本轮确实有要归账的调用时扩窗重读
		# （本机 6.28 MB 全读 0.09s、尾窗 0.058s）。
		scan = _scan_jsonl_tail(path, max(usage_bytes, _AUDIT_WIDEN_BYTES))
		usage_bytes = max(usage_bytes, _AUDIT_WIDEN_BYTES)
		run.add_gap(
			"model_request",
			"recovered_outside_window",
			f"usage 账本尾窗 {_AUDIT_TAIL_BYTES} 字节是截断的，已扩到 {usage_bytes} 字节读完整份再判缺账",
		)
	window = _window_from_scan("usage", str(path), scan, max_bytes=usage_bytes)
	if not scan.present:
		run.add_gap("model_request", "source_absent", f"usage 账本不存在：{path}，无费用可依据")
		_publish_window(run, window)
		return
	for line_no, row in scan.rows:
		row_session = _s(row.get("session_id"))
		if session_id and row_session != session_id:
			if not row_session:
				window.rows_unattributed += 1
			else:
				window.rows_other_session += 1
			continue
		window.rows_matched += 1
		run.usage_rows.append(
			row
			| {
				"locator": str(path),
				"line_no": line_no,
				"attempt_key": request_key(_s(row.get("request_id")), row.get("attempt")),
			}
		)
	if window.rows_unattributed:
		window.add_note(f"{window.rows_unattributed} 行缺 session_id，无法归入本会话，未补值")
	if window.rows_other_session:
		window.add_note(f"{window.rows_other_session} 行属于其他会话，未并入本运行")
	# 账本行不带轮次身份：归属只到"会话 + 尾窗"这一级。此前规则层把窗口里的这类行
	# 当作**每一轮**的结论重复报出（真实数据 37/40 轮、消息字字相同：同一会话的 13 轮
	# 报的都是同一行 line_no）。事实本身属于采集范围，挪到缺项清单，一次说清。
	unlinked_usage = [row for row in run.usage_rows if not _s(row.get("attempt_key"))]
	if unlinked_usage:
		run.add_gap(
			"model_request",
			"unattributed_rows",
			f"本会话的账本窗口里有 {len(unlinked_usage)} 笔用量不带 request_id，无法归到某一次请求，"
			"也无法归轮（账本行本身不记 turn_id）。已知两类来源：记账 meta 注入上线前的旧行；"
			"以及在 engine/query_loop 之外构造适配器、未注入 _meta_request_id 的调用。"
			"金额仍在账（行内有 cost_cny），只是不能按请求下钻；按会话聚合不受影响。",
		)
	if scan.truncated:
		run.add_gap(
			"model_request",
			"out_of_window",
			f"usage 尾窗 {usage_bytes} 字节，仅覆盖最近 {window.rows_scanned} 行，"
			f"窗口外更早的 {window.rows_outside_window} 行未读",
		)
	_publish_window(run, window)


def _collect_folds(run: RunEvidence, session_id: str) -> None:
	try:
		from usage.ledger import fold_events_path
	except Exception:  # noqa: BLE001
		return
	path = fold_events_path()
	scan = _scan_jsonl_tail(path, _AUDIT_TAIL_BYTES)
	window = _window_from_scan("fold_events", str(path), scan, max_bytes=_AUDIT_TAIL_BYTES)
	if not scan.present:
		run.add_gap("wsc_fold", "source_absent", f"fold_events 账本不存在：{path}")
		_publish_window(run, window)
		return
	for line_no, row in scan.rows:
		row_session = _s(row.get("session_id"))
		if session_id and row_session != session_id:
			if not row_session:
				window.rows_unattributed += 1
			else:
				window.rows_other_session += 1
			continue
		window.rows_matched += 1
		run.fold_rows.append(row | {"locator": str(path), "line_no": line_no, "event_id": f"L{line_no}"})
	if window.rows_unattributed:
		window.add_note(f"{window.rows_unattributed} 行缺 session_id，无法归入本会话，未补值")
	# "账本在、窗口完整、但本会话一行都没有"是采集范围事实，不是某一轮的结论：
	# 折叠事件按会话写、行内不带轮次身份，所以这条对每一轮都同形（真实数据 27/40 轮
	# 曾被规则层当成"本轮未定"重复报出）。放在这里，措辞只说这一级没有可核对的记录。
	if scan.present and window.complete and not window.rows_matched:
		# 全量普查（540 真实轮）里这条对 539 轮同形 —— 一条恒真的"没记录"不携带
		# 本轮信息。但同一批数据里有 50 个会话的 working 快照确实带着折叠边界
		# （中位 29 条）：那部分会话这条缺项可以多说一句真话，把它从噪音变成证据。
		chain_total = int(
			(run.working.get("compact_checkpoint") or {}).get("window_chain_total") or 0
		)
		folding_evidence = (
			f"同一会话的 working 快照里有 {chain_total} 条折叠边界记录（折叠发生过，"
			f"只是这一级账本没记上）"
			if chain_total
			else "working 快照也没有折叠边界记录"
		)
		run.add_gap(
			"wsc_fold",
			"no_records",
			"折叠账本可读且窗口完整，但本会话没有任何折叠记录行："
			f"这一级没有可核对的记录 —— 既不能说明折叠没发生，也不能说明发生过。{folding_evidence}。",
		)
	if scan.truncated:
		run.add_gap(
			"wsc_fold",
			"out_of_window",
			f"fold_events 尾窗 {_AUDIT_TAIL_BYTES} 字节，仅覆盖最近 {window.rows_scanned} 行",
		)
	_publish_window(run, window)


def _blob_present(anchor: Path, ref: str) -> bool:
	if not ref:
		return False
	try:
		from session.transcript_blobs import blobs_dir

		return (blobs_dir(anchor) / Path(ref).name).is_file()
	except Exception:  # noqa: BLE001 — 判不出来时按可读处理，交给规则去验证
		return True


def _content_text(value: Any) -> str:
	"""把 transcript 行的正文折成可读文本。

	真实 transcript 里 assistant 正文是块列表（``[{"type":"text","text":…},
	{"type":"tool_use",…}]``：本机两个会话 302/303 与 273/273 都是列表，纯 str 只
	有 1 行）。按 ``isinstance(content, str)`` 取正文 ⇒ 自述核对一句也读不到，
	整条模型侧判据在真实数据上永不成立。只取 text 块：工具块不是"说的话"。
	"""
	if isinstance(value, str):
		return value
	if isinstance(value, list):
		parts: list[str] = []
		for block in value:
			if isinstance(block, dict) and _s(block.get("type")) == "text":
				text = block.get("text")
				if isinstance(text, str) and text:
					parts.append(text)
		return "\n".join(parts)
	return ""


def _collect_transcript(run: RunEvidence, session_id: str, wanted_tool_ids: set[str]) -> None:
	"""transcript 行不带 turn 身份；用本运行的 tool_use_id 锚定，锚不到的只给窗口。"""
	try:
		from session.persistence import transcript_path
	except Exception:  # noqa: BLE001
		run.add_gap("file_verifier", "source_absent", "transcript 路径不可用")
		return
	path = transcript_path(session_id)
	if not path.is_file():
		run.windows.append(
			Window(
				source="transcript",
				locator=str(path),
				complete=False,
				present=False,
				note=f"{path} 不存在：无 transcript 文件，非尾窗截断",
			)
		)
		run.add_gap("file_verifier", "not_captured", "transcript 不存在，结果正文不可回读")
		return
	scan = _scan_jsonl_tail(path, _AUDIT_TAIL_BYTES * 2)
	window = _window_from_scan("transcript", str(path), scan, max_bytes=_AUDIT_TAIL_BYTES * 2)
	anchor = path
	linked_ids: set[str] = set()
	for line_no, row in scan.rows:
		calls = _s(row.get("tool_call_id"))
		view = {
			"id": _s(row.get("id")),
			"role": _s(row.get("role")),
			"ts": row.get("ts"),
			"tool_call_id": calls,
			"line_no": line_no,
			"locator": str(path),
		}
		for key in ("name", "note_kind", "note_key", "note_fp", "note_retracted", "interrupted"):
			if key in row:
				view[key] = row[key]
		if row.get("content_ref"):
			view["content_ref"] = _s(row.get("content_ref"))
			view["content_hash"] = _s(row.get("content_hash"))
			# 缺 blob 时 resolve 只会安静地给空串，必须自己验存在性。
			view["body_state"] = "blob" if _blob_present(path, _s(row.get("content_ref"))) else "missing_blob"
		elif "content" in row:
			view["body_state"] = "inline"
			# 行内正文必须带进载荷：模型自述（"测试通过"）就在 assistant 行里，而
			# 这些行不带 tool_call_id。旧写法只在"本轮工具结果"分支里塞 content，
			# 于是真实数据 20/20 轮读不到一句自述——自述核对与整条模型侧归因
			# 在结构上永不成立。序列化时 to_dict 仍会剥掉 content，不外发。
			text = _content_text(row.get("content"))
			if text:
				view["content"] = text[:2000]
		else:
			view["body_state"] = "absent"
		if calls and wanted_tool_ids and calls in wanted_tool_ids:
			linked_ids.add(calls)
			view["in_run"] = True
			# 小正文留在行里，大正文按需在报告侧回读；缺 blob 不去解引用。
			if view["body_state"] == "blob":
				try:
					from session.transcript_blobs import resolve_transcript_row

					resolved = resolve_transcript_row(row, anchor)
					if isinstance(resolved, dict):
						text = _content_text(resolved.get("content"))
						if text:
							view["content"] = text[:2000]
				except Exception:  # noqa: BLE001 — 回读失败由规则标成冷引用故障
					view["body_state"] = "missing_blob"
		if row.get("content_ref") and calls and calls not in wanted_tool_ids:
			view["in_run"] = False
		run.transcript_rows.append(view)
	# 行数按载荷实际携带量报：保留上限裁掉的行不得再被 rows_matched 声称在内。
	scanned_rows = len(run.transcript_rows)
	if scanned_rows > _TRANSCRIPT_ROW_CAP:
		window.rows_capped = scanned_rows - _TRANSCRIPT_ROW_CAP
		del run.transcript_rows[: -_TRANSCRIPT_ROW_CAP]
		window.add_note(
			f"transcript 保留上限 {_TRANSCRIPT_ROW_CAP} 行：更早的 {window.rows_capped} 行未带入载荷，"
			f"本次实际携带 {len(run.transcript_rows)} 行"
		)
	window.rows_matched = len(run.transcript_rows)
	if scan.truncated:
		run.add_gap(
			"file_verifier",
			"out_of_window",
			f"transcript 尾窗 {_AUDIT_TAIL_BYTES * 2} 字节，窗口外更早的 {window.rows_outside_window} 行未读",
		)
	if window.rows_capped:
		run.add_gap(
			"file_verifier",
			"out_of_window",
			f"transcript 保留上限裁掉更早的 {window.rows_capped} 行，裁掉的行不在载荷里",
		)
	_publish_window(run, window)
	# 锚定关系只能按载荷实际内容算：被裁掉的行不再充当已链接的证据。
	linked_ids &= {_s(r.get("tool_call_id")) for r in run.transcript_rows}
	for tool in run.tool_calls:
		if tool.tool_use_id in linked_ids:
			for row in run.transcript_rows:
				if row.get("tool_call_id") == tool.tool_use_id:
					tool.result_message_id = _s(row.get("id"))
					break
	if wanted_tool_ids and len(linked_ids) < len(wanted_tool_ids):
		unlinked = [t for t in run.tool_calls if t.tool_use_id not in linked_ids]
		# 只有"已经结束、却没有结果行"才是配对缺失；从未结束的调用本就不可能有结果行，
		# 把它算进来会把一件事报成两件（那件事由 tool_pair_integrity 的 started-only 分支说）。
		finished_missing = [t for t in unlinked if t.finished]
		open_unlinked = len(unlinked) - len(finished_missing)
		tail = f"（另有 {open_unlinked} 个调用只有开始记录，不计在这里）" if open_unlinked else ""
		if finished_missing and window.complete:
			run.add_gap(
				"file_verifier",
				"field_missing",
				f"{len(finished_missing)} 个已结束的调用在 transcript 无对应结果行{tail}",
			)
		elif finished_missing:
			# 载荷本身残缺（尾窗没盖到 / 保留上限裁过行）时"没有结果行"是断不出来的。
			# 2026-09-25 分层普查 57 轮：这条缺项有 4 轮落在被裁过的 transcript 上，
			# 计数最高 41 个 —— 那些调用只是排在保留窗（400 行）之前，不是没有结果。
			# 锚定关系仍然按实际载荷算（上面的 linked_ids 已经不含裁掉的行），
			# 变的只是这句话的强度：从"没有"改成"读不出"。
			run.add_gap(
				"file_verifier",
				"out_of_window",
				f"{len(finished_missing)} 个已结束的调用的结果行不在本次读到的 transcript 范围内，配对读不出{tail}",
			)
		elif open_unlinked:
			window.add_note(f"{open_unlinked} 个工具调用只有开始记录，本次不声称它们缺结果行")


def _collect_wire_drops(run: RunEvidence, wanted_tool_ids: set[str]) -> None:
	"""「最后一公里」丢行账本没有 session_id，只能按 dropped id 与本运行工具调用求交。

	这是唯一能证明"结果被丢弃而非未产生"的既有记录；交集为空不等于没丢过。
	"""
	try:
		from usage.ledger import wire_drops_path
	except Exception:  # noqa: BLE001
		return
	path = wire_drops_path()
	scan = _scan_jsonl_tail(path, _AUDIT_TAIL_BYTES)
	window = _window_from_scan("wire_drops", str(path), scan, max_bytes=_AUDIT_TAIL_BYTES)
	if not scan.present:
		run.add_gap(
			"adapter",
			"source_absent",
			f"wire_drops 账本不存在：{path}。它只由 openai_compat 链路的出口护栏写入"
			"（model/anthropic.py 的同类裁剪不落账），所以文件不存在只说明这条链路没记到丢行。",
		)
		_publish_window(run, window)
		return
	for line_no, row in scan.rows:
		ids = [str(i) for i in (row.get("ids") or []) if str(i)]
		hit = sorted(set(ids) & wanted_tool_ids) if wanted_tool_ids else []
		if not hit:
			continue
		window.rows_matched += 1
		run.wire_drops.append(
			dict(row) | {"locator": str(path), "line_no": line_no, "matched_ids": hit}
		)
	if scan.truncated:
		run.add_gap(
			"adapter",
			"out_of_window",
			f"wire_drops 尾窗 {_AUDIT_TAIL_BYTES} 字节，仅覆盖最近 {window.rows_scanned} 行",
		)
	_publish_window(run, window)


def _collect_jobs(run: RunEvidence, jobs: list[dict[str, Any]] | None) -> None:
	if not jobs:
		run.windows.append(
			Window(
				source="jobs",
				complete=False,
				present=False,
				note="未注入 job 快照（进程内状态，需 server 侧提供）",
			)
		)
		return
	unusable = 0
	for job in jobs:
		if not isinstance(job, dict):
			unusable += 1
			continue
		run.jobs.append(dict(job))
	window = Window(
		source="jobs",
		complete=True,
		rows_matched=len(run.jobs),
		rows_scanned=len(jobs),
		rows_unattributed=unusable,
		note="由调用方注入的 job 快照",
	)
	if unusable:
		window.add_note(f"{unusable} 条注入的 job 快照不是对象，未带入载荷")
	_publish_window(run, window)


# ---------- 归并 ----------


def _merge(run: RunEvidence) -> None:
	models: dict[str, ModelRequest] = {}
	tools: dict[str, ToolCall] = {}

	for event in run.events:
		kind = event.kind
		if kind.startswith("model.") or kind == "llm.failure":
			rid = event.model_request_id
			if not rid:
				continue
			mr = models.setdefault(rid, ModelRequest(model_request_id=rid))
			if event.turn_id and not mr.turn_id:
				mr.turn_id = event.turn_id
			if event.projection_id and not mr.projection_id:
				mr.projection_id = event.projection_id
			mr.provider = mr.provider or _s(event.row.get("provider"))
			mr.model = mr.model or _s(event.row.get("model"))
			mr.attempts.append(
				{
					"attempt": event.attempt,
					"kind": kind,
					"ts": event.ts,
					"status": _s(event.row.get("status")),
					# llm.failure 把同一个事实写在 `code` 上（engine/query_loop.py::_audit_llm_failure），
					# error_code 只有 model.* 行才有：只读后者会让现象里的 code= 恒为空。
					"error_code": _s(event.row.get("error_code")) or _s(event.row.get("code")),
					"http_status": event.row.get("status") if kind == "llm.failure" else None,
					"duration_ms": event.row.get("duration_ms"),
					"error_kind": _s(event.row.get("error_kind")),
					"line_no": event.line_no,
				}
			)
			mr.evidence.append(event.ref(_audit_locator()))
		elif kind.startswith("tool.") or kind.startswith("mcp.tool."):
			tid = event.tool_use_id
			if not tid:
				continue
			tc = tools.setdefault(tid, ToolCall(tool_use_id=tid))
			tc.tool_name = tc.tool_name or _s(event.row.get("tool_name"))
			tc.turn_id = tc.turn_id or event.turn_id
			tc.model_request_id = tc.model_request_id or event.model_request_id
			tc.projection_id = tc.projection_id or event.projection_id
			tc.action_id = tc.action_id or event.action_id
			if kind == "tool.started":
				tc.started = dict(event.row) | {"line_no": event.line_no}
			elif kind == "tool.finished":
				tc.finished = dict(event.row) | {"line_no": event.line_no}
				tc.is_error = bool(event.row.get("is_error")) if "is_error" in event.row else None
				tc.error_kind = _s(event.row.get("error_kind"))
			tc.evidence.append(event.ref(_audit_locator()))
			if tc.model_request_id and tc.model_request_id in models:
				if tid not in models[tc.model_request_id].tool_use_ids:
					models[tc.model_request_id].tool_use_ids.append(tid)
		elif kind.startswith("permission."):
			run.permissions.append(
				dict(event.row)
				| {
					"line_no": event.line_no,
					"_refs": [event.ref(_audit_locator())],
				}
			)

	# usage 到尝试的挂载不在此处：账本由 _collect_usage 填充，而它在 _merge 之后
	# 才跑，在这里 join 永远看到空账本。见 _attach_usage_to_attempts。

	run.model_requests = sorted(
		models.values(),
		key=lambda m: (float(m.attempts[0].get("ts") or 0.0) if m.attempts else 0.0, m.model_request_id),
	)
	run.tool_calls = sorted(
		tools.values(),
		key=lambda t: (
			float((t.started or {}).get("ts") or (t.finished or {}).get("ts") or 0.0),
			t.tool_use_id,
		),
	)

	# 权限审批与本运行工具调用的关联：补口后 permission.* 带 tool_use_id / model_request_id。
	for per in run.permissions:
		tid = _s(per.get("tool_use_id")) or _s(per.get("request_id"))
		if not tid:
			continue
		for tc in run.tool_calls:
			if tc.tool_use_id == tid and per.get("request_id") not in tc.approval_ids:
				tc.approval_ids.append(_s(per.get("request_id")))
	run.permissions.sort(key=lambda p: float(p.get("ts") or 0))


def _attach_usage_to_attempts(run: RunEvidence) -> None:
	"""把用量账按 ``(model_request_id, attempt)`` 挂到对应尝试。

	必须在所有采集之后跑：join 的左值来自 ``run.usage_rows``（由 ``_collect_usage``
	填充），提前跑会让每次尝试都拿不到账，界面逐次显示「费用未知」，而用量汇总
	同时声称这些尝试都有价——两边说的是相反的事实。
	"""
	by_attempt: dict[str, dict[str, Any]] = {}
	for row in run.usage_rows:
		key = _s(row.get("attempt_key"))
		if key:
			by_attempt[key] = row
	for mr in run.model_requests:
		mr.usage_by_attempt = {}
		for att in mr.attempts:
			key = request_key(mr.model_request_id, att.get("attempt"))
			row = by_attempt.get(key)
			if row is not None:
				mr.usage_by_attempt[key] = row


# ---------- 入口 ----------


def collect_run(
	session_id: str,
	turn_id: str = "",
	*,
	audit_path: str | os.PathLike[str] | None = None,
	jobs: list[dict[str, Any]] | None = None,
	max_audit_bytes: int | None = None,
) -> RunEvidence:
	"""合并一次运行（一个 turn，或整会话）的证据。只读，不写任何权威来源。"""
	sid = _s(session_id)
	tid = _s(turn_id)
	if not sid:
		raise ValueError("collect_run 需要 session_id")
	path = Path(audit_path) if audit_path else _default_audit_path()
	run = RunEvidence(session_id=sid, turn_id=tid)
	_collect_audit(run, session_id=sid, turn_id=tid, path=path, max_bytes=max_audit_bytes or _AUDIT_TAIL_BYTES)
	_merge(run)
	_collect_working(run, sid)
	_collect_usage(run, sid)
	_collect_folds(run, sid)
	wanted = {t.tool_use_id for t in run.tool_calls}
	_collect_transcript(run, sid, wanted)
	_collect_wire_drops(run, wanted)
	_collect_jobs(run, jobs)
	_attach_captures(run)
	_attach_pins(run)
	# 用量挂载必须在所有采集之后：join 的左操作数是 run.usage_rows，提前跑会永远空表。
	_attach_usage_to_attempts(run)
	_note_identity_granularity(run)
	_note_turn_less_spills(run)
	return run


def _note_turn_less_spills(run: RunEvidence) -> None:
	"""``tool.spill`` 行不带轮次身份 ⇒ 本轮的冷层句柄可回读性判不了。

	生产者的 spill 分支（tools/tool_registry.py）只写 ``session_id``：采集把这些行留在
	上下文里，但 ``events_for_turn`` 会滤掉它们。于是"本轮没有冷层故障"其实是"本轮读不到
	spill 行"——这句话必须写在缺项里，不能靠沉默。真实审计 11 行里 11 行都没有轮次身份
	（2026-09-26 只读普查），所以 ``cold_reference`` 的 spill 分支只有会话级报告走得到。
	"""
	if not run.turn_id:
		return
	turn_less = sum(1 for e in run.events if e.kind == "tool.spill" and not e.turn_id)
	if not turn_less:
		return
	run.add_gap(
		"wsc_fold",
		"unattributed_rows",
		f"本会话窗口里有 {turn_less} 行 tool.spill 不带轮次身份（生产者只写 session_id）："
		"被截断输出的回读句柄归不到本轮，本轮的冷层可回读性判不了，只有会话级报告能判。",
	)


def _note_identity_granularity(run: RunEvidence) -> None:
	"""permission_snapshot_id 的量具粒度：它记的是写入瞬间，不是这次请求。

	规则层因此不再拿它判"指令上下文漂移"（见 rules._DRIFT_FIELDS 的实测理由）。
	这条缺项只在本运行真的看到分裂时才出现 —— 不是恒真措辞。
	"""
	ids_by_request: dict[str, set[str]] = {}
	for event in run.events:
		if not event.kind.startswith("model.") or not event.model_request_id:
			continue
		snap = _s(event.row.get("permission_snapshot_id"))
		if snap:
			ids_by_request.setdefault(event.model_request_id, set()).add(snap)
	split = [rid for rid, ids in ids_by_request.items() if len(ids) > 1]
	if not split:
		return
	run.add_gap(
		"instruction_context",
		"not_comparable",
		f"{len(split)} 个逻辑调用在本轮带着不止一个 permission_snapshot_id。"
		"该字段是写入瞬间的 ambient 权限身份（permissions/trace.py::permission_snapshot 把 mode/revision/cwd "
		"一起取哈希，revision 由 begin_turn 与每次 set() 递增），不是这次请求的身份："
		"用它判不出指令上下文是否漂移，需要的是请求级身份钉在请求行上（引擎侧补口）。",
	)


def _default_audit_path() -> Path:
	from audit.log import default_audit_log

	return default_audit_log().path


def _attach_captures(run: RunEvidence) -> None:
	try:
		from diagnostics.capture import captures_for_run
	except Exception:  # noqa: BLE001
		return
	rows = captures_for_run(run.session_id, run.turn_id)
	run.captures.extend(rows)
	if not rows:
		run.windows.append(
			Window(
				source="captures",
				complete=False,
				present=False,  # 没捕获到任何东西：覆盖态是 absent，不是 partial
				note="该会话未开启可复现记录",
			)
		)
		run.add_gap("adapter", NOT_CAPTURED, "未捕获适配器最终请求体：只能定位到投影边界")
		return
	run.windows.append(
		Window(source="captures", complete=True, rows_matched=len(rows), locator=str(store.captures_dir()))
	)


def _attach_pins(run: RunEvidence) -> None:
	try:
		from diagnostics.pins import pins_for_run
	except Exception:  # noqa: BLE001 — 读不到固定记录本尊，不能反过来断言"没验收"
		return
	run.pins.extend(pins_for_run(run.session_id, run.turn_id))
	# 「本运行没有验收记录」是采集缺口，不是每条结论：它此前作为一条 unknown 结论
	# 出现在**每一轮**（真实数据 40/40），把"未定"桶占满、淹掉真正说不清的信号。
	# 事实保留在原位 —— 缺项清单里，措辞只说"固定记录里没有该条目"，并把两种解释并列，
	# 不单独断言"没验收"。
	if not [p for p in run.pins if str(p.get("kind") or "").strip() == "verifier"]:
		run.add_gap(
			"file_verifier",
			"not_recorded",
			"本运行的固定记录里没有 kind=verifier 的条目（未验收，或验收结果未落盘）",
		)


def list_runs(
	session_id: str,
	*,
	limit: int = 50,
	audit_path: str | os.PathLike[str] | None = None,
	coverage_sink: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
	"""按 turn 聚合的有界运行列表：每个 turn 有哪些边界有记录。

	``coverage_sink``：列表为空时，"读完整份没有"与"尾窗没盖到"是两句不同的话，
	而 coverage_note 挂在每一条 run 上 —— 零条时没有承载处，所以这里给一个出口。
	"""
	sid = _s(session_id)
	path = Path(audit_path) if audit_path else _default_audit_path()
	max_bytes = _AUDIT_TAIL_BYTES * 2
	scan = _scan_jsonl_tail(path, max_bytes)
	widened = False
	if scan.present and scan.truncated and sid and not any(
		_s(row.get("session_id")) == sid for _, row in scan.rows
	):
		# 列表读不到、详情却查得到 —— 同一个会话的两个入口口径不一致。
		# 与 _collect_audit 同法：只在"这个会话一行都不在尾窗里"时扩窗重读一次。
		scan = _scan_jsonl_tail(path, max(max_bytes, _AUDIT_WIDEN_BYTES))
		max_bytes = max(max_bytes, _AUDIT_WIDEN_BYTES)
		widened = True
	turns: dict[str, dict[str, Any]] = {}
	unattributed = 0
	for line_no, row in scan.rows:
		row_session = _s(row.get("session_id"))
		if sid and row_session != sid:
			if not row_session:
				unattributed += 1  # 旧格式行：连属于哪个 turn 都无从判断
			continue
		event = normalize_event(0, line_no, row)
		tid = event.turn_id or "(无轮次身份)"
		item = turns.setdefault(
			tid,
			{
				"turn_id": event.turn_id,
				"first_ts": event.ts,
				"last_ts": event.ts,
				"kinds": set(),
				"boundaries": set(),
				"model_request_ids": set(),
				"tool_use_ids": set(),
				"line_min": line_no,
				"line_max": line_no,
			},
		)
		item["kinds"].add(event.kind)
		item["boundaries"].add(boundary_of(event.kind))
		if event.ts is not None:
			if item["first_ts"] is None or event.ts < item["first_ts"]:
				item["first_ts"] = event.ts
			if item["last_ts"] is None or event.ts > item["last_ts"]:
				item["last_ts"] = event.ts
		if event.model_request_id:
			item["model_request_ids"].add(event.model_request_id)
		if event.tool_use_id:
			item["tool_use_ids"].add(event.tool_use_id)
		item["line_max"] = max(item["line_max"], line_no)
		item["line_min"] = min(item["line_min"], line_no)
	# 覆盖说明：缺失 / 截断 / 丢行是三种不同的事实，各自一句话，绝不互相顶替。
	fragments: list[str] = []
	if not scan.present:
		fragments.append(f"审计文件不存在：{path}，无记录可列（非尾窗截断）")
	else:
		if scan.truncated:
			fragments.append(
				f"审计尾窗截断：{max_bytes} 字节仅覆盖最近 {scan.rows_scanned} 行，"
				f"更早的 {scan.rows_outside_window} 行里的 turn 未列出"
			)
		elif widened:
			if turns:
				fragments.append(
					f"本会话不在默认尾窗内，已扩到 {max_bytes} 字节读到（扫描 {scan.rows_scanned} 行、{len(turns)} 个 turn）"
				)
			else:
				fragments.append(
					f"已按 {max_bytes} 字节读完 {scan.rows_scanned} 行，本会话没有任何行（不是尾窗没盖到）"
				)
		if scan.rows_unparsable:
			fragments.append(f"{scan.rows_unparsable} 行解不出 JSON 对象，未计入任何 turn")
		if unattributed:
			fragments.append(f"{unattributed} 行缺 session_id，无法归入本会话，未计入任何 turn")
	coverage_note = "；".join(fragments)
	coverage = {
		"source": "audit",
		"locator": str(path),
		"present": scan.present,
		"truncated": scan.truncated,
		"rows_scanned": scan.rows_scanned,
		"rows_outside_window": scan.rows_outside_window,
		"rows_unparsable": scan.rows_unparsable,
		"rows_unattributed": unattributed,
		"complete": scan.present and not scan.truncated and not scan.rows_unparsable and not unattributed,
		"widened": widened,
		"note": coverage_note,
	}
	if coverage_sink is not None:
		coverage_sink.clear()
		coverage_sink.update(coverage)
	out: list[dict[str, Any]] = []
	for item in turns.values():
		out.append(
			{
				"session_id": sid,
				"turn_id": item["turn_id"],
				"first_ts": item["first_ts"],
				"last_ts": item["last_ts"],
				"event_kinds": sorted(item["kinds"]),
				"boundaries": sorted(item["boundaries"]),
				"model_request_count": len(item["model_request_ids"]),
				"tool_call_count": len(item["tool_use_ids"]),
				"tool_use_ids": sorted(item["tool_use_ids"]),
				"audit_lines": [item["line_min"], item["line_max"]],
				"coverage_note": coverage_note,
				"coverage": dict(coverage),
			}
		)
	out.sort(key=lambda r: (r["last_ts"] or 0), reverse=True)
	return out[: max(1, int(limit))]


__all__ = [
	"BOUNDARIES",
	"ModelRequest",
	"RunEvidence",
	"ToolCall",
	"Window",
	"boundary_of",
	"collect_run",
	"list_runs",
]
