"""引导（steer）消息的交付兜底：settle 时把滞留项转进 inbox 投递。

事故（2026-09-30）：``engine/t_now_steer.deliver`` 只在**采样前边界**被调用
（``engine/query_loop.py``）。若回合在下一次采样前就结束（模型直接给终答），
引导消息会一直留在内存队列里——

- 服务端已回 202「已排到本轮边界，模型下一步就能看到」，模型却整轮没见过它；
- 引导路径不建 inbox 卡，GUI 也没有任何待投递指示（乐观气泡即全部指示物）；
- 直到下一次人类回合的第一个边界才可能送达，或随
  ``t_now_steer.clear()``（会话删除 / 回溯 / drop_engine）静默作废。

本模块在 settlement 检查点兜底：把该会话滞留的引导项按**原 message_id** 转入
inbox registry ⇒ 复用其排水（批投 / 重试 / stuck / 手动 resume / GUI 卡）把消息
真正送到模型。转入不是新语义——队列里的消息本来就该「至少一次」送达。

口径（与 inbox 租户一致，避免两套规矩）：
- ``stopped`` / ``cancelled``：保持 hold（用户主动停回合时不做自动续跑，与
  inbox「interrupt 只停当前回合，停靠消息保留」同口径）；
- ``XEYO_INBOX_AUTORUN=0``：只转不投，等用户手动 resume；
- 转入失败的项原样放回 steer 队列队首（绝不丢）。

接线：``server/turn_settlement_hub.py`` 在 inbox 租户之后调用（inbox 租户仍排第一，
保证「用户消息优先于 goal」的既有不变量）。

HTTP 引导与已入队消息均已有 inbox 持久所有权；兜底恢复原队列位置，
不提前写 transcript，也不重复 enqueue。未经过 HTTP 的旧内部 push 调用
仍由其自身持久化契约负责，兜底保留兼容分支。
"""

from __future__ import annotations

import logging

_logger = logging.getLogger("xeyo.settlement.steer")


def fallback_pending(session_id: str) -> int:
	"""把该会话滞留的引导项转入 inbox；返回转入条数（0 = 无需兜底）。"""
	sid = (session_id or "").strip()
	if not sid:
		return 0
	try:
		from engine import t_now_steer
	except Exception:  # noqa: BLE001
		return 0
	try:
		if t_now_steer.pending_count(sid) <= 0:
			return 0
		items = t_now_steer.pop_all(sid)
	except Exception:  # noqa: BLE001
		_logger.debug("steer fallback: pop failed sid=%s", sid, exc_info=True)
		return 0
	if not items:
		return 0

	from server.inbox_registry import (
		InboxPersistenceError,
		InboxQueueFull,
		InboxTextTooLong,
		get_inbox_registry,
	)

	reg = get_inbox_registry()
	moved = 0
	leftovers: list[object] = []
	for it in items:
		try:
			# Selected inbox steer retains its queue identity and original order.
			# Direct steer has no inbox owner and needs a new queue entry.
			if not reg.restore_boundary_delivery(sid, it.message_id or ""):
				reg.enqueue(
					sid,
					it.text,
					media_refs=list(it.images or []),
					message_id=(it.message_id or None),
				)
			moved += 1
		except (InboxQueueFull, InboxTextTooLong, InboxPersistenceError):
			leftovers.append(it)
		except Exception:  # noqa: BLE001 — 单条异常不得吞掉其余条目
			_logger.debug("steer fallback: enqueue failed sid=%s", sid, exc_info=True)
			leftovers.append(it)
	if leftovers:
		try:
			t_now_steer.restore_front(sid, leftovers)  # type: ignore[arg-type]
		except Exception:  # noqa: BLE001
			_logger.warning(
				"steer fallback: restore failed sid=%s count=%s", sid, len(leftovers)
			)
	if moved:
		_logger.info("steer fallback: moved to inbox sid=%s count=%s", sid, moved)
		try:
			reg.arm(sid)
		except Exception:  # noqa: BLE001
			_logger.debug("steer fallback: arm failed sid=%s", sid, exc_info=True)
	return moved


async def on_turn_settled(
	session_id: str, final_status: str, stop_reason: str, user_message_id: str = ""
) -> None:
	"""hub 租户：回合正常结束（succeeded/failed）时兜底滞留的引导消息。

	异常全隔离——本协程绝不向调度方抛（hub 另有一层 try，见 §3.1）。
	"""
	try:
		if final_status not in ("succeeded", "failed", "stopped", "cancelled"):
			return
		if final_status in ("stopped", "cancelled"):
			from server.inbox_registry import get_inbox_registry

			get_inbox_registry().pause(session_id)
		fallback_pending(session_id)
	except Exception:  # noqa: BLE001
		_logger.debug("steer fallback skipped sid=%s", session_id, exc_info=True)


__all__ = ["fallback_pending", "on_turn_settled"]
