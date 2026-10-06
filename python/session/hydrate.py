"""把 transcript JSONL 行还原成 Message（坏行跳过）。

T4：tail-scan 未闭合 tool_use → 合成确定性 tool_result，防厂商 400：
- 只读工具：``TOOL_NOT_STARTED``（未执行）；
- 其余（写/副作用，含未知工具，fail-closed）：``TOOL_OUTCOME_UNKNOWN``
  （可能已执行；纯事实，防重放副作用由引擎执行层承担）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from msgtypes.message import Message, tool_result_message
from session.record_transcript import load_transcript, transcript_read_paths
from session.transcript_blobs import resolve_transcript_rows
from session.tool_sequence import (
	discard_unpaired_tool_results,
	reorder_system_messages_around_tool_results,
)

_ROLES: frozenset[str] = frozenset({"system", "user", "assistant", "tool"})


def message_from_row(row: dict[str, Any]) -> Message | None:
	if not isinstance(row, dict):
		return None
	role = row.get("role")
	if role not in _ROLES:
		return None
	content = row.get("content")
	if isinstance(content, list):
		pass
	elif content is None:
		content = ""
	elif not isinstance(content, str):
		content = str(content)
	kwargs: dict[str, Any] = {}
	mid = row.get("id")
	if isinstance(mid, str) and mid.strip():
		kwargs["id"] = mid.strip()
	tc = row.get("tool_call_id")
	if isinstance(tc, str) and tc.strip():
		kwargs["tool_call_id"] = tc.strip()
	name = row.get("name")
	if isinstance(name, str) and name.strip():
		kwargs["name"] = name.strip()
	narr = row.get("narration")
	if isinstance(narr, str) and narr.strip():
		kwargs["narration"] = narr  # T28：旁白随行恢复（background only）
	if row.get("interrupted") is True:
		kwargs["interrupted"] = True  # 44 号：中断锚恢复
	note_key = row.get("note_key")
	if isinstance(note_key, str) and note_key.strip():
		# T_now v2 留痕条目：三字段成套恢复（缺 kind/fp 时按最保守补空串，
		# 条目仍按 hidden 处理——身份由 note_key 决定）。
		kwargs["note_key"] = note_key.strip()
		kind = row.get("note_kind")
		kwargs["note_kind"] = kind.strip() if isinstance(kind, str) else ""
		fp = row.get("note_fp")
		kwargs["note_fp"] = fp.strip() if isinstance(fp, str) else ""
		if row.get("note_retracted") is True:
			kwargs["note_retracted"] = True
	return Message(role=role, content=content, **kwargs)  # type: ignore[arg-type]


def messages_from_rows(rows: list[dict[str, Any]]) -> list[Message]:
	out: list[Message] = []
	for row in rows:
		msg = message_from_row(row)
		if msg is not None:
			out.append(msg)
	return _repair_unclosed_tool_uses(out)


def _assistant_tool_uses(m: Message) -> list[tuple[str, str]]:
	if m.role != "assistant" or not isinstance(m.content, list):
		return []
	uses: list[tuple[str, str]] = []
	for block in m.content:
		if isinstance(block, dict) and block.get("type") == "tool_use":
			uid = str(block.get("id") or "")
			if uid:
				uses.append((uid, str(block.get("name") or "tool")))
	return uses


def _ledger_fact() -> str:
	"""进程台账里**可归因的存活事实**（只读、fail-open、门控关闭时返回空串）。

	为什么必须门控：``XEYO_PROC_LEDGER`` 默认关，关着时"无记录"是机制没开造成的
	空事实——报出去就是假信息（本模块的原则：宁缺勿假）。台账里剩下的存活对象
	至少能说明"上一进程确实 spawn 过东西"，比裸的"可能已执行"多一格信息。

	call 级归因（这一次调用是否开始过）由 ``session/call_trace.py`` 承担：执行层入口按
	``call_id`` 落一条开始记录，本模块只取**正向证据**（见 ``_call_start_fact``）。
	"""
	try:
		from engine.process_ledger import ledger_enabled, leftovers

		if not ledger_enabled():
			return ""
		alive = leftovers()
	except Exception:  # noqa: BLE001 — 台账不可用 ⇒ 不加这句
		return ""
	if not alive:
		return " 进程台账：无存活对象。"
	head = "; ".join(
		f"pid={getattr(entry, 'pid', '?')} "
		f"{(getattr(entry, 'cmdline', '') or '')[:60]}".strip()
		for entry in alive[:2]
	)
	more = f" 等 {len(alive)} 个" if len(alive) > 2 else ""
	return f" 进程台账：存活对象 {head}{more}。"


def _call_start_fact(call_id: str) -> str:
	"""执行起点台账里的**正向证据**：这一次调用确实进入了执行。

	只报正向证据：开关关着 / 会话未知 / 记录被裁剪 / 台账读炸 ⇒ 一律返回空串。
	"无记录"不构成"未开始"的证据，报出去就是假信息（本模块原则：宁缺勿假）。
	"""
	try:
		from engine.t_now_notes import current_session_id
		from session.call_trace import started

		session_id = current_session_id()
		if not session_id:
			return ""
		row = started(session_id, call_id)
	except Exception:  # noqa: BLE001 — 台账不可用 ⇒ 不加这句
		return ""
	if not row:
		return ""
	return " 执行起点台账：该调用已进入执行（有开始记录，无结果）。"


def _repair_unclosed_tool_uses(messages: list[Message]) -> list[Message]:
	"""T4：为没有对应 tool_result 行的 tool_use 合成确定性结果。"""
	messages = reorder_system_messages_around_tool_results(messages)
	messages = discard_unpaired_tool_results(messages)
	try:
		from tools.meta import READONLY_ALLOW as _readonly

		readonly = _readonly
	except Exception:  # noqa: BLE001
		readonly = frozenset()
	out: list[Message] = []
	i = 0
	while i < len(messages):
		m = messages[i]
		uses = _assistant_tool_uses(m)
		if not uses:
			out.append(m)
			i += 1
			continue
		out.append(m)
		j = i + 1
		have: set[str] = set()
		while j < len(messages) and messages[j].role == "tool":
			tid = messages[j].tool_call_id or ""
			if tid:
				have.add(tid)
			out.append(messages[j])
			j += 1
		for uid, name in uses:
			if uid in have:
				continue
			if name in readonly:
				text = (
					f"[{name}] TOOL_NOT_STARTED — 上一进程在工具开始前中断；"
					"该调用未执行。"
				)
			else:
				# F5 裁决：纯事实；防重放副作用由引擎执行层承担
				# （write_store missing_read 门 / unchanged 短路 / 语法门）。
				text = (
					f"[{name}] TOOL_OUTCOME_UNKNOWN — 上一进程中断且该调用"
					"可能已执行。" + _ledger_fact() + _call_start_fact(uid)
				)
			out.append(tool_result_message(uid, name, text, is_error=True))
		i = j
	return out


def messages_from_transcript(path: Path) -> list[Message]:
    """按时间顺序读取 transcript（含 .old 轮转归档），还原成 Message 列表。

    replace 事件化回溯：先对合并日志做 surface fold（影子化被回溯行），
    再还原 Message——旧日志无 marker 时 fold 恒等。
    """
    try:
        rows: list[dict[str, Any]] = []
        for p in transcript_read_paths(path):
            rows.extend(load_transcript(p))
    except OSError:
        return []
    from session.surface import fold_surface_rows

    return messages_from_rows(resolve_transcript_rows(fold_surface_rows(rows), path))


def surface_rows_for_session(session_id: str) -> list[dict[str, Any]]:
    """合并读取某会话全部 transcript 行（含归档）并 fold——模型可见面。

    供需要「与 hydrate 同一视图」的消费者复用（todo 恢复、回溯目标定位等）。
    """
    from session.persistence import transcript_path
    from session.surface import fold_surface_rows

    rows: list[dict[str, Any]] = []
    for p in transcript_read_paths(transcript_path(session_id)):
        rows.extend(load_transcript(p))
    return fold_surface_rows(resolve_transcript_rows(rows, transcript_path(session_id)))


def load_session_messages(session_id: str) -> list[Message]:
	"""按 session_id 从磁盘 hydrate 消息（SessionPool / CLI 共用）。"""
	from session.persistence import is_session_persistence_disabled, transcript_path

	if is_session_persistence_disabled():
		return []
	sid = (session_id or "").strip()
	if not sid:
		return []
	try:
		return messages_from_transcript(transcript_path(sid))
	except Exception:
		return []
