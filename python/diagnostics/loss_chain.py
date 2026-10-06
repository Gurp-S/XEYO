"""信息丢失定位链：一条事实到底在哪一级消失。

按设计文档 6.2 的顺序查同一项事实：源历史 → 结构化状态 → 候选 → 选择 →
发射 → provider 正文 → 冷层句柄。每一级只报「找到 / 没找到 / 这一级没记账」，
没记账的级别必须在结论前出现时，整体判为无法归因。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from diagnostics.collect import RunEvidence
from diagnostics.identity import _f, _s

FOUND = "found"
FOLDED_OUT = "folded_out"
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

#: 每一级状态的中文说法。CLI 的正文只用中文，机器枚举留在结构化字段里
#: （与 fault_split 的 _SHOWN_TEXT 同一裁定）。键集必须与导出的契约一致，
#: 由 tests/diagnostics/test_export_contract.py 钉住：新增一档而这里没登记就红。
STATE_TEXT: dict[str, str] = {
	FOUND: "找到",
	ABSENT: "未命中",
	FOLDED_OUT: "被折叠移出留存投影",
	NOT_RECORDED: "该级未记账",
	NOT_CAPTURED: "该级未采集",
	UNREADABLE: "不可读",
}

#: 结论档位的短标签：长句 `statement` 单独一行跟着印，这里只给"这一条算哪种结论"。
VERDICT_TEXT: dict[str, str] = {
	"not_in_source_history": "源历史里就没有",
	"kept_through": "一路都在（发射级仍查得到）",
	"folded_out_of_projection": "被折叠移出留存投影",
	"lost_before:emitted": "丢在发射之前（中间两级无账本，定位不到具体一级）",
	"unknown": "无法归因",
}


def _stage(name: str, state: str, *, evidence: list[dict[str, Any]], note: str = "") -> dict[str, Any]:
	return {
		"stage": name,
		"label": _STAGE_LABEL.get(name, name),
		"state": state,
		"evidence": evidence,
		"note": note,
	}


_JSON_ESC_RX = re.compile(r"\\(u[0-9a-fA-F]{4}|[nrtbf\"'/\\])")


def _json_unescaped(text: str) -> str:
	"""还原一层常见 JSON 转义（``\\n`` / ``\\uXXXX`` 等）。

	只处理这几种安全形态：整体 ``codecs.decode(..., 'unicode_escape')`` 会把非 ASCII
	字节按 latin-1 解，中文会变成乱码。
	"""

	def _one(m: "re.Match[str]") -> str:
		token = m.group(1)
		if token[0] in "uU":
			try:
				return chr(int(token[1:], 16))
			except ValueError:
				return m.group(0)
		return {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}.get(token, token)

	return _JSON_ESC_RX.sub(_one, text)


def _collapse_ws(text: str) -> str:
	"""连续空白折成单个空格：排版差异不得判成"这条约束没送到模型"。

	只折叠不删除：删掉空白会让 "x y" 匹配上 "xy"，那是把"没送到"误判成"送到了"。
	"""
	return re.sub(r"\s+", " ", text).strip()


def _hit(needle: str, text: str) -> bool:
	"""子串匹配，且对 JSON 转码与排版差异不敏感。

	``last_x_sent`` 一类字段可能是 ``ensure_ascii=True`` 序列化出来的（中文变
	``\\uXXXX``）；只按原文匹配会让"约束没送到模型"成为系统性误判。真实数据实测
	（150 个真实轮）：5 轮的约束原文就在发射投影里，却因为用户消息自带换行而判成
	"没送到"，其中 3 轮已经产出 ``context_dropped_constraint``（引擎定责）——
	即报告里最强那句指控有 3/5 是匹配器造出来的。
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
	if bool(escaped) and escaped in low:
		return True
	needle_forms = {n, _collapse_ws(n)}
	haystack_forms = {_collapse_ws(low), _collapse_ws(_json_unescaped(low))}
	return any(nd and nd in hay for nd in needle_forms for hay in haystack_forms)


def _transcript_window(session_id: str, cap: int) -> tuple[list[dict[str, Any]], int, int]:
	"""返回 (窗口内解析出的行, 扫过的行数, 文件总行数)。

	总行数必须一起带出来：窗外还有多少行，决定"这一级没查到"能不能被说成
	"源历史里没有这条事实"。不报总数，定位链就会拿最后 400 行给更早的枪脱罪。
	"""
	try:
		from session.persistence import transcript_path
	except Exception:  # noqa: BLE001
		return [], 0, 0
	path = transcript_path(session_id)
	if not path.is_file():
		return [], 0, 0
	with path.open("r", encoding="utf-8", errors="replace") as handle:
		lines = [line.strip() for line in handle.readlines()]
	lines = [line for line in lines if line]
	window = lines[-cap:] if cap else lines
	rows: list[dict[str, Any]] = []
	for i, line in enumerate(window):
		try:
			row = json.loads(line)
		except ValueError:
			continue
		if isinstance(row, dict):
			row["_path"] = str(path)
			# 整份文件里的 1-based 序号：折叠游标量的就是这个序号，窗外那些行也得有身份
			row["_line_no"] = (len(lines) - len(window)) + i + 1
			rows.append(row)
	return rows, len(window), len(lines)


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


def _stage_source_history(run: RunEvidence, needle: str, cap: int) -> tuple[dict[str, Any], list[int]]:
	"""源历史级。第二个返回值是命中行在整份转录里的序号 —— 折叠判定要吃它。

	发射级原来只能拿 ``run.transcript_rows``（采集器按本运行锚定的子集）判折叠：约束行
	没被锚进来时，"被折叠移出投影"这一支永远拿不到输入，于是一条确实被折掉的事实会被
	说成"从未进入投影"。整份扫描已经算得出行号，就没必要让机制判断卡在采集口径上。
	"""
	if not _transcript_locator(run.session_id):
		return (
			_stage(
				"source_history",
				NOT_CAPTURED,
				evidence=[],
				note="该会话没有 transcript 文件：无从判断这条事实是否在源历史里，不得报「不存在」",
			),
			[],
		)
	rows, scanned, total = _transcript_window(run.session_id, cap)
	hits: list[dict[str, Any]] = []
	hit_lines: list[int] = []
	unreadable = 0
	for row in rows:
		body = _resolve_body(row)
		if not body and row.get("content_ref"):
			unreadable += 1
		if _hit(needle, body) or _hit(needle, json.dumps(row.get("tool_call_id"), ensure_ascii=False)):
			hit_lines.append(int(row.get("_line_no") or 0))
			hits.append(
				{
					"source": "transcript",
					"locator": _s(row.get("_path")),
					"ref_id": _s(row.get("id")),
					"detail": f"role={_s(row.get('role'))}",
				}
			)
	if hits:
		return (
			_stage(
				"source_history",
				FOUND,
				evidence=hits[:10],
				note=f"命中 {len(hits)} 条消息" + (f"；另有 {unreadable} 条正文不可解引用" if unreadable else ""),
			),
			hit_lines,
		)
	# ↑ 命中行的序号单独返回：发射级判"落在折叠区间内"要吃它，而不是吃采集载荷里的子集
	if unreadable:
		return (
			_stage(
				"source_history",
				UNREADABLE,
				evidence=[{"source": "transcript", "locator": "", "ref_id": "", "detail": f"{unreadable} 条 blob 读不回"}],
				note="正文读不回来，不能说这条事实不在源历史里",
			),
			[],
		)
	if total > scanned:
		# 窗覆盖不到整份转录：这一级的"没查到"是"没读到"，不是"不存在"。
		# 真实数据实测（28 个 >=4 轮会话、137 枪）：只扫最后 400 行时 28 枪（20%）的
		# 用户原话落在窗外，被这条结论判成"源历史里就查不到，不是这次压缩丢的"。
		return (
			_stage(
				"source_history",
				NOT_CAPTURED,
				evidence=[],
				note=(
					f"扫描窗只有最近 {scanned} 行，窗外还有 {total - scanned} 行没读到："
					"这一级说不出「源历史里没有这条事实」"
				),
			),
			[],
		)
	return (
		_stage("source_history", ABSENT, evidence=[], note=f"整份 transcript {total} 行内未命中"),
		[],
	)


def _structured_state_text(session_id: str) -> tuple[str, str]:
	"""可搜索的结构化状态文本（todos / 原子 / 已加载指令路径 / 已读文件）。

	与发射投影同理：只为本地匹配而读，正文不进报告。
	"""
	try:
		from memory.working import hydrate, path_for

		snap = hydrate(session_id, source_layout=None)
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


#: 判定"这条记录还属于这个范围"时允许的时间误差（授权等待、时钟抖动都算在内）。
_OBLIGATION_TOLERANCE_SEC = 2.0


def _turn_last_ts(run: RunEvidence) -> float | None:
	ts = [e.ts for e in run.events_for_turn() if e.ts is not None]
	return max(ts) if ts else None


def _emitted_projection_in_turn(run: RunEvidence) -> bool:
	"""working 里的 last_x_sent 是整会话的最后一份投影，可能出自更晚的一轮。

	拿它判断「本轮的约束没送到模型」会把后面几轮的内容当成这一轮的输入。只有
	manifest 的创建时刻不晚于本轮最后一条记录时，这份投影才还是这一轮的。
	判不动就返回 False：宁可不判，也不替引擎凭空认账。
	"""
	upper = _turn_last_ts(run)
	if upper is None:
		# 一条带时间戳的记录都没有 ⇒ 这份留存投影出自哪一枪根本无从核对。返回 True 等于
		# "默认它就是我们这一枪"，于是会话级报告可以拿整会话最后一枪去判某一枪送没送到：
		# 真实数据 404 个会话里有 7 个这样被判成引擎丢了约束（且原因条目 evidence 为空）。
		# 与 _last_user_obligation 对同一事实的处理保持一致：界不了就不界，宁可不判。
		return False
	stamps = [_f(p.get("created_at")) for p in run.projections]
	stamps = [s for s in stamps if s is not None]
	if not stamps:
		return False
	return max(stamps) <= upper + _OBLIGATION_TOLERANCE_SEC


def _last_sent_projection(session_id: str) -> tuple[str, str]:
	"""取回上一枪实际发送的投影文本（只用于本地匹配，绝不进报告正文）。"""
	try:
		from memory.working import hydrate, path_for

		snap = hydrate(session_id, source_layout=None)
	except Exception:  # noqa: BLE001 — 状态不可读时这一级判为未采集
		return "", ""
	return _s(getattr(snap, "last_x_sent", "")), str(path_for(session_id))


def _stage_emitted(
	run: RunEvidence, needle: str, *, source_hit_lines: list[int] | None = None
) -> dict[str, Any]:
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
	# 区分两种"没在投影里"：被折叠移出投影 vs 从未进入投影。用既有游标，不新建账本。
	cursor = int((run.working or {}).get("compact_cursor") or 0)
	if source_hit_lines is None:
		# 独立调用（责任划分那条路）仍按采集器锚定的行判；定位链会把整份扫描算出的行号传进来。
		source_hit_lines = [
			int(row.get("line_no") or 0)
			for row in run.transcript_rows
			if isinstance(row.get("content"), str) and _hit(needle, row["content"])
		]
	hit_lines = [ln for ln in source_hit_lines if ln]
	folded_out = bool(hit_lines) and any(0 < (ln - 1) < cursor for ln in hit_lines)
	if folded_out:
		return _stage(
			"emitted",
			FOLDED_OUT,
			evidence=[
				{
					"source": "working",
					"locator": locator,
					"ref_id": "compact_cursor",
					"detail": f"游标 {cursor}：第 {min(hit_lines)} 行落在被折叠区间内",
				}
			],
			note=(
				"该消息在 compact_cursor 之前：被折叠移出投影，而不是从未进入投影。"
				"前提是 transcript 行序与游标同为消息序号；游标口径变了这里会误判。"
			),
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


def trace_fact(run: RunEvidence, needle: str, *, transcript_cap: int = 2000) -> dict[str, Any]:
	"""跑一遍定位链。

	判读规则：整份源历史扫过且没有 ⇒ 不是这次压缩丢的；发射级仍在 ⇒ 一路都在（中间级
	可以合理跳过，正文类事实本就不会进结构化状态）；否则取「最后一次可见」之后的第一个
	缺失级，且要求中间没有没记账的级别，不然只能报无法归因。

	两条"落空"结论各带一个前提：发射级要落得下"丢在发射之前"，必须先知道这份留存投影
	属于被问的那个范围（``_emitted_projection_in_turn``），且这条事实确实进过源历史 ——
	扫描窗没盖住整份转录时，"没查到"只是"没读到"。
	"""
	needle_text = _s(needle)
	if not needle_text:
		raise ValueError("trace_fact 需要非空 needle")
	source_stage, source_hit_lines = _stage_source_history(run, needle_text, transcript_cap)
	stages = [
		source_stage,
		_stage_structured_state(run, needle_text),
		_stage_candidate(run),
		_stage_selected(run),
		_stage_emitted(run, needle_text, source_hit_lines=source_hit_lines),
		_stage_provider_body(run, needle_text),
		_stage_cold_handle(run, needle_text),
	]
	holes = {NOT_RECORDED, NOT_CAPTURED, UNREADABLE}
	state_at = {s["stage"]: s["state"] for s in stages}
	unprovable = [s["stage"] for s in stages if s["state"] in holes]
	# 发射级只有整会话留存的那一份投影：命中是自证的（正文带着这段原文 ⇒ 发它的时候这段话
	# 已经存在），落空不是 —— 归属核不上时，"不在这一份里"既可能是被某一级丢了，也可能
	# 这一份本来就早于它。责任划分那边同一条裁定（fault_split::_shown_to_model）。
	emitted_bound = _emitted_projection_in_turn(run)
	# "丢在某一级之前"这句话有两个前提，缺一个就只能停在无法归因：这份投影属于被问的那个范围，
	# 以及这条事实确实进过源历史。第二个前提在窗外没读到 / 正文读不回时不成立。
	source_seen = state_at.get("source_history") == FOUND

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
	elif state_at.get("emitted") == FOLDED_OUT and emitted_bound and source_seen:
		verdict = "folded_out_of_projection"
		statement = (
			"该事实在源历史里查得到，但落在 compact_cursor 之前的折叠区间内：是折叠把它移出投影的。"
			"折叠本身可以是对的，需要复核的是这条是否该被保留。"
		)
	elif state_at.get("emitted") == ABSENT and emitted_bound and source_seen:
		verdict = "lost_before:emitted"
		statement = (
			"该事实在源历史里查得到、在最后发射的投影里查不到。"
			f"中间的 {_hole_note(['candidate', 'selected'])} 没有落盘账本，不能再往下定位到具体一级。"
		)
	else:
		verdict = "unknown"
		last_visible = [ _STAGE_LABEL[s["stage"]] for s in stages if s["state"] == FOUND ]
		if state_at.get("emitted") in {ABSENT, FOLDED_OUT} and not emitted_bound:
			# 有可比对的投影，只是核不出它属不属于这个范围：这句话不能说成"没丢"也不能说成"丢了"
			statement = (
				"发射级只留存整会话最后一份投影，且无从核对它属不属于这个范围："
				"该事实不在这一份里，既不能定位到哪一级丢的，也不能排除这份投影本来就早于它。"
			)
		elif state_at.get("emitted") in {ABSENT, FOLDED_OUT}:
			# 投影归属核得上，但"它在源历史里"这件事没被证实（窗外没读到 / 正文读不回）：
			# 少了这个前提，"丢在发射之前"和"源历史里查得到"都是凭空补的。
			statement = (
				"发射级里没有这段事实，但源历史级也给不出可比对的记录（见该级说明）："
				"既不能断定它进过历史，也就不能断定它是在哪一级丢的。"
			)
		else:
			statement = (
				f"最后可见于 {'、'.join(last_visible) if last_visible else '无任何一级'}；"
				f"{_hole_note(unprovable)} 没有可比对的记录：无法归因。"
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


__all__ = [
	"ABSENT",
	"FOLDED_OUT",
	"FOUND",
	"NOT_CAPTURED",
	"NOT_RECORDED",
	"STAGES",
	"STATE_TEXT",
	"UNREADABLE",
	"VERDICT_TEXT",
	"trace_fact",
]
