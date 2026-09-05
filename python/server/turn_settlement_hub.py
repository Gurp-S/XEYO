"""Turn Settlement Hub（42 号）— settlement 单槽的多租户分发。

41 号在 ``turn_runner`` 暴露的是**单个**回调槽（engine 不 import server）。
42 号把同一位置泛化：server 启动时把 hub 注册进槽，hub 再分发给各租户——

- ``InboxRegistry.on_turn_settled``（P1 mid-turn inbox：排第一——inbox 先提交则 goal 的
  ``_precheck`` 见 ``_turn_running`` 为真自动跳过，实现「用户消息优先于 goal 续跑」）
- ``GoalRoundDriver.on_turn_settled``（41 号检查点，不变）
- ``JobRegistry.on_turn_settled``（42 号：turn 期间挂起的完成通知并投递）

turn_runner 仍只认识一个回调；各租户独立注册进 hub，互不感知（§3.1）。
每个租户的异常完全隔离：任何一个挂了不影响另一个与 turn teardown。
"""

from __future__ import annotations

import logging

_logger = logging.getLogger("xeyo.settlement.hub")


async def on_turn_settled(
	session_id: str, final_status: str, stop_reason: str
) -> None:
	"""settlement 分发（由 turn_runner 槽调用；绝不上抛）。"""
	# P1 租户（排第一）：mid-turn inbox 排水。先于 goal —— inbox 提交后 goal 的
	# precheck 见 _turn_running 为真而跳过，实现「用户消息优先于 goal 自动续跑」。
	try:
		from server.inbox_registry import get_inbox_registry

		await get_inbox_registry().on_turn_settled(
			session_id, final_status, stop_reason
		)
	except Exception:  # noqa: BLE001
		_logger.debug(
			"settlement hub: inbox tenant failed sid=%s",
			session_id,
			exc_info=True,
		)
	# 41 号租户：goal round driver 检查点。
	try:
		from server.goal_round_driver import get_goal_round_driver

		await get_goal_round_driver().on_turn_settled(
			session_id, final_status, stop_reason
		)
	except Exception:  # noqa: BLE001
		_logger.debug(
			"settlement hub: goal tenant failed sid=%s",
			session_id,
			exc_info=True,
		)
	# 42 号租户：job 完成通知投递决策。
	try:
		from server.job_registry import get_job_registry

		await get_job_registry().on_turn_settled(
			session_id, final_status, stop_reason
		)
	except Exception:  # noqa: BLE001
		_logger.debug(
			"settlement hub: jobs tenant failed sid=%s",
			session_id,
			exc_info=True,
		)


def shutdown() -> None:
	"""lifespan teardown：清各租户内存态（armed / 唤醒任务 / 请求环境）。"""
	try:
		from server.inbox_registry import get_inbox_registry

		get_inbox_registry().shutdown()
	except Exception:  # noqa: BLE001
		_logger.debug("settlement hub: inbox shutdown failed", exc_info=True)
	try:
		from server.goal_round_driver import get_goal_round_driver

		get_goal_round_driver().shutdown()
	except Exception:  # noqa: BLE001
		_logger.debug("settlement hub: goal shutdown failed", exc_info=True)
	try:
		from server.job_registry import get_job_registry

		get_job_registry().shutdown()
	except Exception:  # noqa: BLE001
		_logger.debug("settlement hub: jobs shutdown failed", exc_info=True)
	try:
		from server.synthetic_round import clear_request_envs

		clear_request_envs()
	except Exception:  # noqa: BLE001
		_logger.debug("settlement hub: env clear failed", exc_info=True)
