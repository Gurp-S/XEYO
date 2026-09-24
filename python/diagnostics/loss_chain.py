"""信息丢失定位链：一条事实到底在哪一级消失。

按设计文档 6.2 的顺序查同一项事实：源历史 → 结构化状态 → 候选 → 选择 →
发射 → provider 正文 → 冷层句柄。每一级只报「找到 / 没找到 / 这一级没记账」，
没记账的级别必须在结论前出现时，整体判为无法归因。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from diagnostics.collect import RunEvidence
from diagnostics.identity import _s

FOUND = "found"
ABSENT = "absent"
NOT_RECORDED = "not_recorded"
NOT_CAPTURED = "not_captured"
UNREADABLE = "unreadable"

STAGES: tuple[tuple[str, str], ...] = (
	("source_history", "源历史（transcript）"),
	("structured_state", "结构化事件与状态"),
	("candidate", "进入候选"),
	("selected", "被选择"),
	("emitted", "已发射（投影）"),
	("provider_body", "最终请求体"),
	("cold_handle", "冷层句柄可回读"),
)

_STAGE_LABEL = dict(STAGES)


def _stage(name: str, state: str, *, evidence: list[dict[str, Any]], note: str = "") -> dict[str, Any]:
	return {
		"stage": name,
		"label": _STAGE_LABEL.get(name, name),
		"state": state,
		"evidence": evidence,
		"note": note,
	}


def _hit(needle: str, text: str) -> bool:
	"""子串匹配，且对 JSON 转码不敏感。

	``last_x_sent`` 一类字段可能是 ``ensure_ascii=True`` 序列化出来的（中文变
	``\\uXXXX``）；只按原文匹配会让"约束没送到模型"成为系统性误判。
	"""
	if not needle or not text:
		return False
	low = text.lower()
	n = needle.lower()
	if n in low:
		return True
	try:
		escaped = needle.encode("unicode_escape").decode("ascii").lower()
	except Exception:  # noqa: BLE001
		return False
	return bool(escaped) and escaped in low


def _iter_transcript(session_id: str, cap: int) -> Iterator[dict[str, Any]]:
	try:
		from session.persistence import transcript_path
	except Exception:  # noqa: BLE001
		return
	path = transcript_path(session_id)
	if not path.is_file():
		return
	with path.open("r", encoding="utf-8", errors="replace") as handle:
		lines = handle.readlines()
	for line in lines[-cap:]:
		line = line.strip()
		if not line:
			continue
		try:
			row = json.loads(line)
		except ValueError:
			continue
		if isinstance(row, dict):
			row["_path"] = str(path)
			yield row


def _resolve_body(row: dict[str, Any]) -> str:
	"""解引用 transcript 正文；文件不在时返回空串，由上层标 unreadable。"""
	content = row.get("content")
	if isinstance(content, str) and content:
		return content
	if not row.get("content_ref"):
		return "" if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
	try:
		from session.transcript_blobs import resolve_transcript_row

		resolved = resolve_transcript_row(row, Path(row.get("_path") or "."))
	except Exception:  # noqa: BLE001
		return ""
	value = resolved.get("content") if isinstance(resolved, dict) else None
	if isinstance(value, str):
		return value
	return "" if value is None else json.dumps(value, ensure_ascii=False)


def _transcript_locator(session_id: str) -> str:
	try:
		from session.persistence import transcript_path

		path = transcript_path(session_id)
		return str(path) if path.is_file() else ""
	except Exception:  # noqa: BLE001
		return ""


def _stage_source_history(run: RunEvidence, needle: str, cap: int) -> dict[str, Any]:
	if not _transcript_locator(run.session_id):
		return _stage(
			"source_history",
			NOT_CAPTURED,
			evidence=[],
			note="该会话没有 transcript 文件：无从判断这条事实是否在源历史里，不得报「不存在」",
		)
	hits: list[dict[str, Any]] = []
	unreadable = 0
	for row in _iter_transcript(run.session_id, cap):
		body = _resolve_body(row)
		if not body and row.get("content_ref"):
			unreadable += 1
		if _hit(needle, body) or _hit(needle, json.dumps(row.get("tool_call_id"), ensure_ascii=False)):
			hits.append(
				{
					"source": "transcript",
					"locator": _s(row.get("_path")),
					"ref_id": _s(row.get("id")),
					"detail": f"role={_s(row.get('role'))}",
				}
			)
	if hits:
		return _stage(
			"source_history",
			FOUND,
			evidence=hits[:10],
			note=f"命中 {len(hits)} 条消息" + (f"；另有 {unreadable} 条正文不可解引用" if unreadable else ""),
		)
	if unreadable:
		return _stage(
			"source_history",
			UNREADABLE,
			evidence=[{"source": "transcript", "locator": "", "ref_id": "", "detail": f"{unreadable} 条 blob 读不回"}],
			note="正文读不回来，不能说这条事实不在源历史里",
		)
	return _stage("source_history", ABSENT, evidence=[], note=f"最近 {cap} 行 transcript 内未命中")


def _structured_state_text(session_id: str) -> tuple[str, str]:
	"""可搜索的结构化状态文本（todos / 原子 / 已加载指令路径 / 已读文件）。

	与发射投影同理：只为本地匹配而读，正文不进报告。
	"""
	try:
		from memory.working import hydrate, path_for

		snap = hydrate(session_id)
	except Exception:  # noqa: BLE001
		return "", ""
	bits: list[Any] = []
	for name in (
		"todos",
		"tasks",
		"current_atoms",
		"loaded_nested_instruction_paths",
		"nested_hashes",
		"read_file_state",
		"speculation",
	):
		value = getattr(snap, name, None)
		if value:
			bits.append({name: value})
	return json.dumps(bits, ensure_ascii=False), str(path_for(session_id))


def _stage_structured_state(run: RunEvidence, needle: str) -> dict[str, Any]:
	events = run.events_for_turn()
	state_text, locator = _structured_state_text(run.session_id)
	if not state_text and not run.working and not events:
		return _stage(
			"structured_state",
			NOT_CAPTURED,
			evidence=[],
			note="既无状态快照也无本运行事件：这一级没有可比对的记录",
		)
	hits: list[dict[str, Any]] = []
	if _hit(needle, state_text):
		hits.append(
			{
				"source": "working",
				"locator": locator,
				"ref_id": "structured_state",
				"detail": "todos/原子/指令路径/已读文件里出现该事实",
			}
		)
	if _hit(needle, json.dumps(run.working or {}, ensure_ascii=False)):
		hits.append(
			{
				"source": "working",
				"locator": _s((run.working or {}).get("locator")),
				"ref_id": "working",
				"detail": "压缩游标与模式记录里出现该事实",
			}
		)
	for event in events:
		if _hit(needle, json.dumps(event.row, ensure_ascii=False)):
			hits.append(event.ref(_s(run.window("audit").locator) if run.window("audit") else "").to_dict())
	if hits:
		return _stage("structured_state", FOUND, evidence=hits[:10], note="命中即说明提取阶段留下了痕迹")
	return _stage(
		"structured_state",
		ABSENT,
		evidence=[],
		note="结构化记录未命中；正文类事实不经提取本就不会出现在这一级，因此这一级缺失不单独定责",
	)


def _stage_candidate(run: RunEvidence) -> dict[str, Any]:
	return _stage(
		"candidate",
		NOT_RECORDED,
		evidence=[],
		note="活路径没有落盘的候选账本：这一级无法判定，不得据此说信息是在候选阶段丢的",
	)


def _stage_selected(run: RunEvidence) -> dict[str, Any]:
	projections = run.projections or []
	if not projections:
		return _stage("selected", NOT_CAPTURED, evidence=[], note="没有投影 manifest，无法判断是否被选中")
	return _stage(
		"selected",
		NOT_RECORDED,
		evidence=[
			{
				"source": "projection",
				"locator": _s(p.get("locator")),
				"ref_id": _s(p.get("projection_id")),
				"detail": f"messages_kept={p.get('messages_kept')}",
			}
			for p in projections[:5]
		],
		note="manifest 只给计数与结构，不给逐条选择理由；能判断投影规模，不能判断这一条是否被选中",
	)


def _last_sent_projection(session_id: str) -> tuple[str, str]:
	"""取回上一枪实际发送的投影文本（只用于本地匹配，绝不进报告正文）。"""
	try:
		from memory.working import hydrate, path_for

		snap = hydrate(session_id)
	except Exception:  # noqa: BLE001 — 状态不可读时这一级判为未采集
		return "", ""
	return _s(getattr(snap, "last_x_sent", "")), str(path_for(session_id))


def _stage_emitted(run: RunEvidence, needle: str) -> dict[str, Any]:
	sent, locator = _last_sent_projection(run.session_id)
	if not sent:
		return _stage(
			"emitted",
			NOT_CAPTURED,
			evidence=[],
			note="working 未持久化上一枪实际发送的投影正文，无法判断是否已发射",
		)
	if _hit(needle, sent):
		return _stage(
			"emitted",
			FOUND,
			evidence=[
				{
					"source": "working",
					"locator": locator,
					"ref_id": "last_x_sent",
					"detail": f"发射投影内含该事实（投影 {len(sent)} 字符）",
				}
			],
			note="按规范化投影文本匹配；正文不入报告",
		)
	return _stage(
		"emitted",
		ABSENT,
		evidence=[{"source": "working", "locator": locator, "ref_id": "last_x_sent", "detail": f"投影 {len(sent)} 字符"}],
		note="发射投影里没有该事实",
	)


def _stage_provider_body(run: RunEvidence, needle: str) -> dict[str, Any]:
	captures = run.captures or []
	if not captures:
		return _stage(
			"provider_body",
			NOT_CAPTURED,
			evidence=[],
			note="该会话未开启可复现记录：只能定位到投影边界，看不到适配器最终请求体",
		)
	try:
		from diagnostics.capture import resolve_capture
	except Exception:  # noqa: BLE001
		return _stage("provider_body", NOT_RECORDED, evidence=[], note="捕获模块不可用")
	hits: list[dict[str, Any]] = []
	seen_hashes: set[str] = set()
	for row in captures:
		hashed = _s(row.get("body_hash"))
		if not hashed or hashed in seen_hashes:
			continue
		seen_hashes.add(hashed)
		doc = resolve_capture(hashed)
		if not doc or doc.get("state") in {"not_captured", "expired"}:
			continue
		if _hit(needle, json.dumps(doc.get("body"), ensure_ascii=False)):
			hits.append(
				{
					"source": "capture",
					"locator": _s(doc.get("locator")),
					"ref_id": hashed[:16],
					"detail": f"state={_s(doc.get('state'))} hash_matches={doc.get('hash_matches')}",
				}
			)
	if hits:
		return _stage("provider_body", FOUND, evidence=hits[:5], note="最终请求体里仍含该事实")
	return _stage(
		"provider_body",
		ABSENT,
		evidence=[
			{
				"source": "capture",
				"locator": _s(run.captures[0].get("locator")),
				"ref_id": "",
				"detail": f"已捕获 {len(seen_hashes)} 份请求体",
			}
		],
		note="在已捕获的请求体里未命中",
	)


def _stage_cold_handle(run: RunEvidence, needle: str) -> dict[str, Any]:
	handles = [row for row in run.transcript_rows if row.get("content_ref")]
	if not handles:
		return _stage("cold_handle", NOT_RECORDED, evidence=[], note="本运行可见记录里没有冷层句柄")
	broken = [
		{
			"source": "transcript",
			"locator": _s(row.get("locator")),
			"ref_id": _s(row.get("id")),
			"detail": f"body_state={_s(row.get('body_state'))}",
		}
		for row in handles
		if row.get("body_state") in {"missing_blob", "resolve_failed", "absent"}
	]
	if broken:
		return _stage("cold_handle", UNREADABLE, evidence=broken[:10], note=f"{len(broken)} 个句柄不可回读")
	refs = 0
	try:
		from memory.wsc_projection import _usage_ledger  # 只读账本，不触发写入

		path = Path(_usage_ledger())
		if path.is_file():
			for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]:
				try:
					doc = json.loads(line)
				except ValueError:
					continue
				if isinstance(doc, dict) and _s(doc.get("session")) == run.session_id:
					refs += int(doc.get("handle_refs") or 0)
	except Exception:  # noqa: BLE001 — 账本不可用不影响定位
		pass
	return _stage(
		"cold_handle",
		FOUND,
		evidence=[{"source": "config", "locator": "wsc_index_usage.jsonl", "ref_id": "", "detail": f"会话累计句柄引用 {refs} 次"}],
		note="句柄可读；但账本按会话聚合，不能证明模型为这一条事实发起过取回",
	)


def trace_fact(run: RunEvidence, needle: str, *, transcript_cap: int = 400) -> dict[str, Any]:
	"""跑一遍定位链。

	判读规则：源历史就没有 ⇒ 不是这次压缩丢的；发射级仍在 ⇒ 一路都在（中间级可以
	合理跳过，正文类事实本就不会进结构化状态）；否则取「最后一次可见」之后的第一个
	缺失级，且要求中间没有没记账的级别，不然只能报无法归因。
	"""
	needle_text = _s(needle)
	if not needle_text:
		raise ValueError("trace_fact 需要非空 needle")
	stages = [
		_stage_source_history(run, needle_text, transcript_cap),
		_stage_structured_state(run, needle_text),
		_stage_candidate(run),
		_stage_selected(run),
		_stage_emitted(run, needle_text),
		_stage_provider_body(run, needle_text),
		_stage_cold_handle(run, needle_text),
	]
	holes = {NOT_RECORDED, NOT_CAPTURED, UNREADABLE}
	state_at = {s["stage"]: s["state"] for s in stages}
	unprovable = [s["stage"] for s in stages if s["state"] in holes]

	def _hole_note(names: list[str]) -> str:
		return "、".join(_STAGE_LABEL.get(n, n) for n in names)

	# 只有这三级是不可跳过的通道；结构化提取、候选与选择都可以合理不经（正文类事实
	# 本来就不进 todos），把它们当定位点会造出假故障。
	if state_at.get("source_history") == ABSENT:
		verdict = "not_in_source_history"
		statement = "该事实在源历史（transcript）里就查不到：不是这次压缩丢的。"
	elif state_at.get("emitted") == FOUND or state_at.get("provider_body") == FOUND:
		verdict = "kept_through"
		statement = (
			"该事实在发射级仍然可查（中间级可以合理跳过，跳过不构成丢失）。"
			"它仍在热层时任务失败，只能排除「这条被直接删掉」，不能排除压缩通过信息顺序或噪声影响模型。"
		)
	elif state_at.get("emitted") == ABSENT:
		verdict = "lost_before:emitted"
		statement = (
			"该事实在源历史里查得到、在最后发射的投影里查不到。"
			f"中间的 {_hole_note(['candidate', 'selected'])} 没有落盘账本，不能再往下定位到具体一级。"
		)
	else:
		verdict = "unknown"
		last_visible = [ _STAGE_LABEL[s["stage"]] for s in stages if s["state"] == FOUND ]
		statement = (
			f"最后可见于 {'、'.join(last_visible) if last_visible else '无任何一级'}，"
			f"发射级本身没有可用记录（{_hole_note(unprovable)}）：无法归因。"
		)
	return {
		"needle": needle_text,
		"session_id": run.session_id,
		"turn_id": run.turn_id,
		"stages": stages,
		"verdict": verdict,
		"statement": statement,
		"unprovable_stages": unprovable,
		"caveat": "匹配是字符串级的：出现某个词不等于模型理解了它。",
	}


__all__ = ["ABSENT", "FOUND", "NOT_CAPTURED", "NOT_RECORDED", "STAGES", "UNREADABLE", "trace_fact"]
