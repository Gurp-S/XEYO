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

_BOUNDARY_OF_KIND: tuple[tuple[str, str], ...] = (
	("permission.", "tool_permission"),
	("model.", "model_request"),
	("llm.failure", "model_request"),
	("tool.", "tool_permission"),
	("mcp.tool.", "tool_permission"),
	("mcp.server.", "tool_permission"),
	("notice.channel", "sse_gui"),
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
	"""一次有界扫描的覆盖情况；截断必须显式说出来。"""

	source: str
	locator: str = ""
	complete: bool = False
	rows_scanned: int = 0
	rows_matched: int = 0
	bytes_read: int = 0
	note: str = ""

	def to_dict(self) -> dict[str, Any]:
		return {
			"source": self.source,
			"locator": self.locator,
			"complete": self.complete,
			"rows_scanned": self.rows_scanned,
			"rows_matched": self.rows_matched,
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
		gap = Gap(boundary=boundary, reason=reason, detail=detail)
		self.gaps.append(gap)
		return gap

	# ---------- 序列化 ----------

	def coverage(self) -> dict[str, Any]:
		out: dict[str, Any] = {}
		for w in self.windows:
			out[w.source] = {
				"state": COMPLETE if w.complete else (PARTIAL if w.rows_matched else ABSENT),
				"complete": w.complete,
				"rows": w.rows_matched,
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
				refs = [
					EvidenceRef("transcript", _s(t.get("locator", "")), _s(t.get("id")), "message")
					for t in self.transcript_rows
					if t.get("note_kind") == "verifier"
				]
			elif name == "sse_gui":
				refs = [e.ref("") for e in scoped if e.kind in {"notice.channel", "title.enhance.applied"}]
			else:
				refs = [e.ref("") for e in scoped if boundary_of(e.kind) == name]
			for g in self.gaps:
				if g.boundary == name:
					notes.append(f"{g.reason}: {g.detail}".strip(": "))
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


def _tail_jsonl(path: Path, max_bytes: int) -> tuple[list[tuple[int, dict[str, Any]]], int, bool]:
	"""从文件尾读至多 ``max_bytes``；返回 ``[(行号, dict)]``、读取字节、是否覆盖全文件。"""
	if not path.is_file():
		return [], 0, True
	size = path.stat().st_size
	with path.open("rb") as handle:
		offset = 0
		truncated = False
		if size > max_bytes:
			handle.seek(size - max_bytes)
			handle.readline()  # 丢弃可能被切断的首行
			offset = handle.tell()
			truncated = True
		raw = handle.read()
	first_line_no = 1
	if truncated:
		# 行号必须和物理行一致，否则证据指针指向别处；只数窗口前的换行。
		with path.open("rb") as handle:
			first_line_no = handle.read(offset).count(b"\n") + 1
	text = raw.decode("utf-8", "replace")
	out: list[tuple[int, dict[str, Any]]] = []
	for index, line in enumerate(text.splitlines()):
		line = line.strip()
		if not line:
			continue
		try:
			row = json.loads(line)
		except ValueError:
			continue
		if isinstance(row, dict):
			out.append((first_line_no + index, row))
	return out, len(raw), truncated


# ---------- 采集 ----------


def _collect_audit(run: RunEvidence, *, session_id: str, turn_id: str, path: Path, max_bytes: int) -> None:
	locator = str(path)
	entries, read_bytes, truncated = _tail_jsonl(path, max_bytes)
	matched = 0
	unattributed = 0
	window = Window(source="audit", locator=locator, bytes_read=read_bytes)
	for line_no, row in entries:
		window.rows_scanned += 1
		if session_id and _s(row.get("session_id")) != session_id:
			if not _s(row.get("session_id")):
				unattributed += 1
			continue
		event = normalize_event(window.rows_matched, line_no, row)
		matched += 1
		if turn_id and event.turn_id and event.turn_id != turn_id:
			# 权限/工具事件可能只带 trace_id；turn_id 未知的行保留为上下文，不参与轮次归因。
			continue
		run.events.append(event)
	window.rows_matched = matched
	window.complete = not truncated
	notes: list[str] = []
	if truncated:
		notes.append("尾窗截断：窗口外的更早事件按不存在处理会误判，已标 complete=false")
	if unattributed:
		notes.append(f"{unattributed} 行缺 session_id（旧格式），无法归入本会话，未补值")
	window.note = "；".join(notes)
	run.windows.append(window)
	if truncated:
		run.add_gap(
			"instruction_context",
			"out_of_window",
			f"audit 尾窗 {max_bytes} 字节，仅覆盖最近 {window.rows_scanned} 行",
		)


def _collect_working(run: RunEvidence, session_id: str) -> None:
	"""投影 manifest / 冻结前缀计量来自会话 working 快照（只有最后一份，须说明）。"""
	try:
		from memory.working import hydrate

		snap = hydrate(session_id)
	except Exception:  # noqa: BLE001 — 观测不可用只记缺项
		run.windows.append(Window(source="working", complete=False, note="hydrate 失败"))
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
		run.working["compact_checkpoint"] = {
			"anchor_cursor": int(getattr(checkpoint, "anchor_cursor", 0) or 0),
			"anchor_frozen_until": int(getattr(checkpoint, "anchor_frozen_until", 0) or 0),
			"window_chain": [dict(w) for w in chain if isinstance(w, dict)][-50:],
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
	run.add_gap(
		"instruction_context",
		"field_missing",
		"last_projection_manifest 单快照：本运行前的投影结构无法回放",
	)


def _working_locator(session_id: str) -> Path:
	try:
		from memory.working import path_for

		return path_for(session_id)
	except Exception:  # noqa: BLE001
		return Path("sessions/<session>.working.json")


def _collect_usage(run: RunEvidence, session_id: str) -> None:
	try:
		from usage.ledger import events_path
	except Exception:  # noqa: BLE001
		run.add_gap("model_request", "source_absent", "usage 账本不可导入")
		return
	path = events_path()
	entries, read_bytes, truncated = _tail_jsonl(path, _AUDIT_TAIL_BYTES)
	window = Window(
		source="usage",
		locator=str(path),
		bytes_read=read_bytes,
		complete=not truncated,
	)
	for line_no, row in entries:
		window.rows_scanned += 1
		if session_id and _s(row.get("session_id")) != session_id:
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
	run.windows.append(window)


def _collect_folds(run: RunEvidence, session_id: str) -> None:
	try:
		from usage.ledger import fold_events_path
	except Exception:  # noqa: BLE001
		return
	path = fold_events_path()
	entries, read_bytes, truncated = _tail_jsonl(path, _AUDIT_TAIL_BYTES)
	window = Window(
		source="fold_events",
		locator=str(path),
		bytes_read=read_bytes,
		complete=not truncated,
	)
	for line_no, row in entries:
		window.rows_scanned += 1
		if session_id and _s(row.get("session_id")) != session_id:
			continue
		window.rows_matched += 1
		run.fold_rows.append(row | {"locator": str(path), "line_no": line_no, "event_id": f"L{line_no}"})
	run.windows.append(window)


def _blob_present(anchor: Path, ref: str) -> bool:
	if not ref:
		return False
	try:
		from session.transcript_blobs import blobs_dir

		return (blobs_dir(anchor) / Path(ref).name).is_file()
	except Exception:  # noqa: BLE001 — 判不出来时按可读处理，交给规则去验证
		return True


def _collect_transcript(run: RunEvidence, session_id: str, wanted_tool_ids: set[str]) -> None:
	"""transcript 行不带 turn 身份；用本运行的 tool_use_id 锚定，锚不到的只给窗口。"""
	try:
		from session.persistence import transcript_path
	except Exception:  # noqa: BLE001
		run.add_gap("file_verifier", "source_absent", "transcript 路径不可用")
		return
	path = transcript_path(session_id)
	if not path.is_file():
		run.windows.append(Window(source="transcript", locator=str(path), complete=False, note="无 transcript 文件"))
		run.add_gap("file_verifier", "not_captured", "transcript 不存在，结果正文不可回读")
		return
	entries, read_bytes, truncated = _tail_jsonl(path, _AUDIT_TAIL_BYTES * 2)
	window = Window(
		source="transcript",
		locator=str(path),
		bytes_read=read_bytes,
		complete=not truncated,
	)
	anchor = path
	linked_ids: set[str] = set()
	for line_no, row in entries:
		window.rows_scanned += 1
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
					if isinstance(resolved, dict) and isinstance(resolved.get("content"), str):
						view["content"] = resolved["content"][:2000]
				except Exception:  # noqa: BLE001 — 回读失败由规则标成冷引用故障
					view["body_state"] = "missing_blob"
		if row.get("content_ref") and calls and calls not in wanted_tool_ids:
			view["in_run"] = False
		window.rows_matched += 1
		run.transcript_rows.append(view)
	if len(run.transcript_rows) > _TRANSCRIPT_ROW_CAP:
		del run.transcript_rows[: -_TRANSCRIPT_ROW_CAP]
		window.complete = False
		window.note = f"仅保留最近 {_TRANSCRIPT_ROW_CAP} 行"
	run.windows.append(window)
	for tool in run.tool_calls:
		if tool.tool_use_id in linked_ids:
			for row in run.transcript_rows:
				if row.get("tool_call_id") == tool.tool_use_id:
					tool.result_message_id = _s(row.get("id"))
					break
	if wanted_tool_ids and len(linked_ids) < len(wanted_tool_ids):
		run.add_gap(
			"file_verifier",
			"field_missing",
			f"{len(wanted_tool_ids) - len(linked_ids)} 个工具调用在 transcript 无对应结果行",
		)


def _collect_wire_drops(run: RunEvidence, wanted_tool_ids: set[str]) -> None:
	"""「最后一公里」丢行账本没有 session_id，只能按 dropped id 与本运行工具调用求交。

	这是唯一能证明"结果被丢弃而非未产生"的既有记录；交集为空不等于没丢过。
	"""
	try:
		from usage.ledger import wire_drops_path
	except Exception:  # noqa: BLE001
		return
	path = wire_drops_path()
	entries, read_bytes, truncated = _tail_jsonl(path, _AUDIT_TAIL_BYTES)
	window = Window(
		source="wire_drops",
		locator=str(path),
		bytes_read=read_bytes,
		complete=not truncated,
	)
	for line_no, row in entries:
		window.rows_scanned += 1
		ids = [str(i) for i in (row.get("ids") or []) if str(i)]
		hit = sorted(set(ids) & wanted_tool_ids) if wanted_tool_ids else []
		if not hit:
			continue
		window.rows_matched += 1
		run.wire_drops.append(
			dict(row) | {"locator": str(path), "line_no": line_no, "matched_ids": hit}
		)
	if truncated:
		window.note = "尾窗截断，更早的丢行未覆盖"
	run.windows.append(window)


def _collect_jobs(run: RunEvidence, jobs: list[dict[str, Any]] | None) -> None:
	if not jobs:
		run.windows.append(Window(source="jobs", complete=False, note="未注入 job 快照（进程内状态，需 server 侧提供）"))
		return
	for job in jobs:
		if not isinstance(job, dict):
			continue
		run.jobs.append(dict(job))
	run.windows.append(
		Window(source="jobs", complete=True, rows_matched=len(run.jobs), note="由调用方注入的 job 快照")
	)


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
					"error_code": _s(event.row.get("error_code")),
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

	# usage 按 (request_id, attempt) 挂到对应尝试；缺 request_id 的行单独列出不匹配。
	by_attempt: dict[str, dict[str, Any]] = {}
	for row in run.usage_rows:
		key = _s(row.get("attempt_key"))
		if key:
			by_attempt[key] = row
	for mr in models.values():
		for att in mr.attempts:
			key = request_key(mr.model_request_id, att.get("attempt"))
			row = by_attempt.get(key)
			if row is not None:
				mr.usage_by_attempt[key] = row

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
	return run


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
	except Exception:  # noqa: BLE001
		return
	run.pins.extend(pins_for_run(run.session_id, run.turn_id))


def list_runs(session_id: str, *, limit: int = 50, audit_path: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
	"""按 turn 聚合的有界运行列表：每个 turn 有哪些边界有记录。"""
	sid = _s(session_id)
	path = Path(audit_path) if audit_path else _default_audit_path()
	entries, _read, truncated = _tail_jsonl(path, _AUDIT_TAIL_BYTES * 2)
	turns: dict[str, dict[str, Any]] = {}
	for line_no, row in entries:
		if sid and _s(row.get("session_id")) != sid:
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
				"coverage_note": (
					"审计尾窗截断，更早的 turn 可能未列出" if truncated else ""
				),
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
