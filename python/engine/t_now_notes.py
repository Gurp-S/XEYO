"""T_now 留痕条目落库（管道 2「进历史」那半边）。

边界顺序（唯一注入时机 + 落库时点）：
1. **本轮注入前** → :func:`persist_pending`：把上一轮登记的留痕条目追加进
   MessageStore + transcript。于是本轮投影里这一版已经在历史中 ⇒ 台账判
   「值没变」成立 ⇒ T_now 尾部不再重发（管道 2 纪律落地）。
2. **本轮注入后** → 装配点 :func:`prompt.inject_store.note` 登记新版本
   （只登记"值变了"的那一次；同 key 只留最新）。
3. **历史被压缩改写** → :func:`invalidate_after_compaction` 清账 ⇒ 下一轮按
   当前值重注（先压缩、后重注）。

失败一律 fail-open：留痕写不进去不抛、不阻断主循环；未提交的版本下一轮会
重新登记（最坏是重复注入一次，绝不丢信息）。
"""

from __future__ import annotations

import logging
from typing import Any

from msgtypes.message import Message, system_note
from prompt import inject_store

_log = logging.getLogger(__name__)


def current_session_id() -> str:
	"""从工作区上下文取当前会话（与 ``query_loop._attach_turn_context`` 同源）。"""
	try:
		from engine.workspace_context import get_workspace_context

		ctx = get_workspace_context()
		return str(getattr(ctx, "session_id", "") or "").strip()
	except Exception:  # noqa: BLE001
		return ""


def persist_pending(
	store: Any,
	*,
	session_id: str = "",
	snapshot: Any = None,
	allow_notes: bool = True,
) -> int:
	"""把待落库留痕条目写进历史（append-only，绝不 insert/改中间）。

	返回落库条数。``store`` 是 MessageStore；``snapshot`` 给出时会顺手清掉
	投影缓存（追加了新历史，缓存前缀不再有效）。

	``allow_notes=False``（A 闸：本轮声道不是 system_channel ⇒ 厂商不吃中段
	system）：**不写新留痕**，把待落库条目丢弃并清账 —— 状态块改由 notice
	声道送达，避免"历史里塞 system 导致每次请求都 4xx"。
	"""
	sid = (session_id or "").strip() or current_session_id()
	if not sid:
		return 0
	try:
		notes = inject_store.drain_notes(sid)
	except Exception:  # noqa: BLE001
		return 0
	if not notes:
		return 0
	if not allow_notes:
		# 丢弃待落库条目 + 清账：下一轮按当前值走 notice 声道重注
		try:
			inject_store.note_disarmed(sid)
			inject_store.invalidate(sid)
		except Exception:  # noqa: BLE001
			_log.debug("t_now disarm failed", exc_info=True)
		return 0
	msgs: list[Message] = []
	for n in notes:
		try:
			msg = system_note(n.text, key=n.key, fp=n.fp, kind=n.kind)
			store.append(msg)
		except Exception:  # noqa: BLE001
			_log.debug("t_now note append failed: %s", n.key, exc_info=True)
			continue
		# 只有真的进了历史才提交台账：未落库的版本下一轮照旧重发
		# （最坏重复注入一次，绝不出现"账上说有、其实没有"）。
		try:
			inject_store.commit(sid, n.key, n.fp)
		except Exception:  # noqa: BLE001
			_log.debug("t_now ledger commit failed: %s", n.key, exc_info=True)
		msgs.append(msg)
	if not msgs:
		return 0
	if snapshot is not None:
		try:
			snapshot.proj_cache = None
		except Exception:  # noqa: BLE001
			pass
	try:
		from session.record_transcript import record_transcript_sync

		record_transcript_sync(msgs, session_id=sid)
	except Exception:  # noqa: BLE001
		_log.debug("t_now note transcript write failed", exc_info=True)
	return len(msgs)


def invalidate_after_compaction(session_id: str = "") -> None:
	"""压缩改写历史后清账：下一轮按当前值重注（先压缩、后重注）。"""
	sid = (session_id or "").strip() or current_session_id()
	if not sid:
		return
	try:
		inject_store.invalidate(sid)
	except Exception:  # noqa: BLE001
		_log.debug("t_now ledger invalidate failed", exc_info=True)


__all__ = [
	"current_session_id",
	"invalidate_after_compaction",
	"persist_pending",
]
