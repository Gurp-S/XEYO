"""管道 1 的补充声道：忙时排队用户消息的**边界投递**。

事故（2026-09-20）：忙时用户消息默认走 ``server.inbox_registry``，而该队列
**只在 settle 投递**（``on_turn_settled`` 是唯一投递点）。长回合（读—改—读探索
循环）迟迟不 settle ⇒ 消息一直挂在内存队列里，模型整轮看不见用户 ⇒ 表现为
"不听指令 / 答非所问"。同一时刻，steer（边界投递）语义本身是好的，只是默认
不启用。

本模块把排队消息接到既有的边界投递上：每次采样前（与 steer 同刻）把 inbox 里
的用户消息变成**真 user 消息**追加进历史——工具批次不被打断，模型下一个采样
前就看到。投递成功后条目已离开 inbox，settle 侧自然不再投（不重复）。

口径：
- 只在**边界**投递（与 steer 同刻，唯一注入时机）；
- 复用 steer 队列的全部可靠性（WAL / 幂等 / 至少一次 / 失败回队）；
- steer 队列满（``push`` 返回 False）⇒ 原样放回 inbox 队首，不丢消息、不计失败；
- 任何异常返回空列表，绝不挡主链；``XEYO_INBOX_BOUNDARY=0`` 关闭本声道。
"""

from __future__ import annotations

import logging
import os
from typing import Any

_log = logging.getLogger(__name__)


def _enabled() -> bool:
	raw = os.environ.get("XEYO_INBOX_BOUNDARY", "1").strip().lower()
	return raw not in ("0", "false", "no", "off")


def _registry() -> Any:
	from server.inbox_registry import get_inbox_registry

	return get_inbox_registry()


def deliver_queued_users(session_id: str, store: Any) -> list[Any]:
	"""把该会话 inbox 里排队的用户消息在边界投进历史；返回本次已进模型输入的消息。

	返回值含"新追加的"与"因幂等已在历史里的"——它是 ``steer_delivered`` 回执的
	依据（前端靠这批 id 撤卡），不是"要不要再落一次盘"的判据。
	返回空列表 = 本轮无排队消息（或声道关闭 / 取件失败）。异常一律 fail-open。
	"""
	sid = (session_id or "").strip()
	if not sid:
		return []
	if not _enabled():
		return []
	try:
		reg = _registry()
		items = reg.consume_for_boundary(sid)
	except Exception:  # noqa: BLE001 — inbox 不可用时绝不挡主链
		_log.debug("inbox boundary consume failed", exc_info=True)
		return []
	if not items:
		return []

	from engine.t_now_steer import deliver as _deliver
	from engine.t_now_steer import push as _push

	failed: list[Any] = []
	for it in items:
		ok = False
		try:
			ok = bool(
				_push(
					sid,
					it.text,
					images=list(it.media_refs or []),
					message_id=it.message_id or "",
				)
			)
		except Exception:  # noqa: BLE001
			_log.debug("inbox boundary push failed", exc_info=True)
		if not ok:
			failed.append(it)
	if failed:
		# 入队失败：原样放回队首（不计 attempts），settle 侧仍有机会投递。
		try:
			reg.restore_front(sid, failed)
		except Exception:  # noqa: BLE001
			_log.warning("inbox restore after failed push failed sid=%s", sid, exc_info=True)
	try:
		return _deliver(sid, store)
	except Exception:  # noqa: BLE001
		_log.debug("inbox boundary deliver failed", exc_info=True)
		return []