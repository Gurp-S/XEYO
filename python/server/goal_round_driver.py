"""Goal Round Driver（41 号 P0）：armed 内存态 + settlement 复检 + 预约 + 合成轮。

语义对齐 ``dsh-goal-round-driver``（docs/设计/41-goal-round-driver设计.md）：

- **armed 只在内存**：进程重启必静止；本模块不写任何落盘状态（goal 实体除外，
  由 GoalStore 权威）。driver 绝不杀 turn / 挡工具 / 阻塞人类消息（38 号铁律）。
- **settlement 检查点**（turn_runner finally 之后注册调用）：终态判定 →
  ``failed`` 补 blocked 记账 + disarm / ``stopped|cancelled`` disarm /
  ``succeeded`` 且 armed → 复检预约下一轮。
- **预约不消耗轮号**：预约只是内存 create_task；只有合成轮真正被引擎接受
  （turn start 成功）后才 ``admit_round_async`` CAS 推进 rounds。409 / CAS miss /
  让位 / disarm 一律作废，轮号不消耗（对齐 DSH「进入步骤才计数」）。
- **人类消息让位最高优先**：chat.py 主路径在 busy 闸前调 ``yield_to_human``
  取消在途预约（不消耗轮号）；人类轮结束后的 settlement 自然重新预约。
- **合成轮复用整条 submit 管线**：分离式 ASGI 自调用 POST /v1/chat/completions
  （「继续」+ ``X-Xeyo-Goal-Round`` 头；2026-09-05 修正：拿到响应头即返回、turn
  detached 续跑——不再把整个 turn 跑在预约 task 里），模型环境（model/key/
  workspace 等）取自最近一次人类请求的内存快照（``note_request_env``，仅内存、
  随进程消失）。
- **cap**：``resolved_max_rounds(goal, config.goal_round_cap)``；超 cap 由
  admit 软置候选（pending_complete），driver 复检见候选即自然停。

全路径 try/except 降级：driver 任何异常只记日志，绝不影响 turn 与人类请求。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from engine.goal_state import (
	STATUS_ACTIVE,
	GoalConflict,
	GoalStore,
	resolved_max_rounds,
)

_logger = logging.getLogger("xeyo.goal.driver")

# 预约到发起之间的防抖：让 GUI 渲染上一轮终态，并给人类消息留让位窗口。
_ROUND_DEBOUNCE_S = 2.0
# 合成轮标记头（chat.py 解析：<goal_id>@<round>@<cap>，注入 enriched resume prompt）。
GOAL_ROUND_HEADER = "X-Xeyo-Goal-Round"


def default_goal_round_cap() -> int:
	"""全局默认轮次上限：~/.xeyo/config.toml ``goal_round_cap``（缺省 32）。"""
	try:
		from cli.config_store import load_config

		cap = int(getattr(load_config(), "goal_round_cap", 32) or 32)
		return max(1, cap)
	except Exception:  # noqa: BLE001
		return 32


@dataclass
class _DriverState:
	"""per-session driver 状态（纯内存，随进程消失）。"""

	armed: bool = False
	# 在途预约 / 轮中任务（_round_task）。预约期 = 任务在 sleep/precheck；
	# 轮中期 = 任务在 drain SSE。两者都可被取消且不消耗轮号（轮中取消不杀 turn）。
	pending: asyncio.Task | None = None
	# 轮中的 (goal_id, round_no)；settlement 后清空。
	active_round: tuple[str, int] | None = None


class GoalRoundDriver:
	"""单会话至多一个在途合成轮；状态机见模块 docstring 与 41 号 §4。"""

	def __init__(self) -> None:
		self._states: dict[str, _DriverState] = {}
		# 测试注入点：goals.py 同款取根 + TurnRunner 判活。
		self._pool: Any = None

	# ------------------------------------------------------------------
	# 可覆写钩子（测试 monkeypatch）
	# ------------------------------------------------------------------
	def _session_root(self, session_id: str) -> str:
		try:
			if self._pool is None:
				from server.deps import _pool

				self._pool = _pool
			return str(
				(self._pool.session_cwd(session_id) or self._pool.cwd) or ""
			).strip()
		except Exception:  # noqa: BLE001
			return ""

	def _turn_running(self, session_id: str) -> bool:
		try:
			from engine.turn_runner import get_turn_runner

			return bool(get_turn_runner().is_running(session_id))
		except Exception:  # noqa: BLE001
			return False

	# ------------------------------------------------------------------
	# 请求环境快照（42 号起收敛到 server.synthetic_round 共享 stash）
	# ------------------------------------------------------------------
	def note_request_env(self, session_id: str, env: dict[str, Any]) -> None:
		"""记录最近一次人类请求的模型环境（api_key 含在内；仅内存、随进程消失）。"""
		try:
			from server.synthetic_round import note_request_env as _note

			_note(session_id, env)
		except Exception:  # noqa: BLE001
			pass

	def _env_for(self, session_id: str) -> dict[str, Any] | None:
		try:
			from server.synthetic_round import env_for

			return env_for(session_id)
		except Exception:  # noqa: BLE001
			return None

	# ------------------------------------------------------------------
	# 状态读 / arm / disarm / 让位
	# ------------------------------------------------------------------
	def snapshot(self, session_id: str) -> dict[str, Any] | None:
		"""GUI 投影（41 号 §9.4：XEYO 有意比 DSH 多暴露 armed 态）。"""
		st = self._states.get(session_id)
		if st is None:
			return None
		pending = st.pending is not None and not st.pending.done()
		return {
			"activation": "armed" if st.armed else "disarmed",
			"pending": pending,
			"active_round": list(st.active_round) if st.active_round else None,
		}

	def arm(self, session_id: str) -> dict[str, Any]:
		"""显式 arm（冻结口径 2：绝不随 goal 创建自动 armed）。空闲则立即预约。"""
		st = self._states.setdefault(session_id, _DriverState())
		st.armed = True
		self._schedule(session_id)
		return self.snapshot(session_id) or {}

	def disarm(self, session_id: str) -> dict[str, Any]:
		"""取消 armed + 作废在途预约（不杀轮中 turn——driver 不做执行控制）。"""
		st = self._states.get(session_id)
		if st is not None:
			st.armed = False
			st.active_round = None
			self._cancel_pending(st)
		return self.snapshot(session_id) or {
			"activation": "disarmed",
			"pending": False,
			"active_round": None,
		}

	def poke(self, session_id: str) -> None:
		"""armed 且无在途预约时补一次预约（goal 从 paused/blocked 恢复 active 后调用）。

		无运行事件循环（同步端点线程池）时静默放弃——等下一次 settlement。
		"""
		st = self._states.get(session_id)
		if st is not None and st.armed:
			self._schedule(session_id)

	def drop_session(self, session_id: str) -> None:
		"""会话删除 / 回溯解耦：清 per-session 内存态（armed + 在途预约）。"""
		self.disarm(session_id)
		self._states.pop(session_id, None)

	def yield_to_human(self, session_id: str) -> None:
		"""人类消息让位（chat.py 主路径 busy 闸前调用）：作废在途预约。"""
		st = self._states.get(session_id)
		if st is None:
			return
		if st.pending is not None and not st.pending.done():
			_logger.info("goal round yield_to_human session=%s", session_id)
		self._cancel_pending(st)

	def shutdown(self) -> None:
		"""app lifespan teardown：全量 disarm + 作废预约（请求环境由 hub 清）。"""
		for sid in list(self._states.keys()):
			self.disarm(sid)
		self._states.clear()

	def _cancel_pending(self, st: _DriverState) -> None:
		task = st.pending
		st.pending = None
		if task is not None and not task.done():
			task.cancel()

	def _schedule(self, session_id: str) -> None:
		"""预约下一轮（不消耗轮号）。仅 async 上下文调用（arm 端点 / settlement）。"""
		st = self._states.get(session_id)
		if st is None or not st.armed:
			return
		if st.pending is not None and not st.pending.done():
			return
		try:
			st.pending = asyncio.create_task(
				self._round_task(session_id),
				name=f"xeyo-goal-round-{session_id}",
			)
		except RuntimeError:
			# 无运行循环（如同步端点误调）：放弃预约，等下一次 settlement。
			st.pending = None

	# ------------------------------------------------------------------
	# settlement 检查点（turn_runner 注册调用）
	# ------------------------------------------------------------------
	async def on_turn_settled(
		self, session_id: str, final_status: str, stop_reason: str
	) -> None:
		"""turn 终态：failed→blocked+disarm / stopped→disarm / succeeded→复检预约。

		异常全隔离——本协程绝不向调度方抛（turn_runner create_task 不等待它）。
		"""
		try:
			st = self._states.get(session_id)
			if st is not None and st.active_round is not None:
				st.active_round = None
			if final_status == "failed":
				await self._mark_blocked(session_id, stop_reason)
				if st is not None and st.armed:
					self.disarm(session_id)
				return
			if final_status in ("stopped", "cancelled"):
				# 用户停 / HTTP 取消：停止续跑（冻结口径 3），goal 保持 active。
				if st is not None and st.armed:
					_logger.info("goal driver disarm on %s session=%s", final_status, session_id)
					self.disarm(session_id)
				return
			if final_status == "succeeded":
				if st is not None and st.armed:
					self._schedule(session_id)
		except Exception:  # noqa: BLE001
			_logger.debug(
				"goal settlement skipped session=%s", session_id, exc_info=True
			)

	async def _mark_blocked(self, session_id: str, reason: str) -> None:
		"""failed turn → goal blocked（补 38 号触发点 #2 记账；CAS miss 放弃）。"""
		try:
			root = self._session_root(session_id)
			if not root:
				return
			gstore = GoalStore(root)
			goal = gstore.current(session_id)
			if goal is None or goal.status != STATUS_ACTIVE:
				return
			await gstore.transition_async(
				goal.goal_id,
				"blocked",
				revision=goal.revision,
				blocked_reason=(reason or "turn_failed")[:400],
			)
			_logger.info(
				"goal blocked session=%s goal=%s reason=%s",
				session_id,
				goal.goal_id,
				reason,
			)
		except GoalConflict:
			_logger.debug("goal blocked CAS miss session=%s", session_id)
		except Exception:  # noqa: BLE001
			_logger.debug("goal blocked mark skipped session=%s", session_id, exc_info=True)

	# ------------------------------------------------------------------
	# 预约 → 防抖 → 复检 → 合成轮 → admit
	# ------------------------------------------------------------------
	async def _round_task(self, session_id: str) -> None:
		"""预约任务：防抖 → 复检 → 合成轮 → admit（进 turn 才计轮）。"""
		st = self._states.get(session_id)
		try:
			await asyncio.sleep(_ROUND_DEBOUNCE_S)
			pre = await self._precheck(session_id)
			if pre is None:
				return
			goal, cap = pre
			# 42 号 §3.4：goal 复检唤醒与 job 唤醒共享 per-session 唤醒预算
			# （maxConsecutiveWakes=3）；任何一方的自产出都不恢复，只有人类
			# 输入恢复（chat.py 入口 restore_wake）。预算尽 → 不开轮、不消耗
			# 轮号，armed 保持；goal cap 是独立的另一道闸（轮数上限 ≠ 唤醒上限）。
			wake_consumed = False
			try:
				from server.job_registry import get_job_registry

				wake_consumed = get_job_registry().consume_wake(session_id)
				if not wake_consumed:
					_logger.info(
						"goal round skipped session=%s wake budget exhausted",
						session_id,
					)
					return
			except Exception:  # noqa: BLE001 — 预算器异常不挡 41 号主链
				pass
			if st is not None:
				st.active_round = (goal.goal_id, int(goal.rounds))
			started = await self._submit_round(
				session_id, goal.goal_id, int(goal.rounds), cap
			)
			if not started:
				# 提交失败（无 env / 409 让位 / 拒绝 / 超时）：轮未跑不消耗轮号，
				# 也不白扣共享唤醒预算（退还）；不自动重排——有 turn 在跑时其
				# settlement 会重新预约，无 turn 时由下一次人类 settlement 兜底。
				if wake_consumed:
					try:
						from server.job_registry import get_job_registry

						get_job_registry().refund_wake(session_id)
					except Exception:  # noqa: BLE001
						pass
				return
			# turn 已被引擎接受（响应头 200）→ 此时才消耗轮号。CAS miss 重试少量
			# 次（分离式提交下 admit 落在 turn 起点，revision 竞速窗口极小；重读
			# 仅在 goal 仍 active 时继续，轮号语义不变形）。
			try:
				root = self._session_root(session_id)
				gstore = GoalStore(root) if root else None
				for _attempt in range(3):
					if gstore is None:
						break
					try:
						await gstore.admit_round_async(
							goal.goal_id, revision=goal.revision, cap=cap
						)
						break
					except GoalConflict:
						fresh = gstore.get(goal.goal_id)
						if fresh is None or fresh.status != STATUS_ACTIVE:
							_logger.debug(
								"goal admit CAS miss and goal not active goal=%s",
								goal.goal_id,
							)
							break
						goal = fresh
			except GoalConflict:
				_logger.debug(
					"goal admit CAS miss (round uncounted) goal=%s", goal.goal_id
				)
		except asyncio.CancelledError:
			# 让位 / disarm / shutdown：作废预约，轮号不消耗。
			raise
		except Exception:  # noqa: BLE001
			_logger.debug(
				"goal round aborted session=%s", session_id, exc_info=True
			)
		finally:
			cur = self._states.get(session_id)
			if cur is not None and cur.pending is asyncio.current_task():
				cur.pending = None
			if cur is not None:
				cur.active_round = None

	async def _precheck(
		self, session_id: str
	) -> tuple[Any, int] | None:
		"""复检（41 号 §4 ①②③④）：armed / active 无候选 / 有余量 / 无活 turn。"""
		st = self._states.get(session_id)
		if st is None or not st.armed:
			return None
		# 在途预约检查须排除当前任务自身（预约任务本人就是 st.pending，
		# 否则永远自阻塞）。done 的旧任务不算在途。
		try:
			_cur = asyncio.current_task()
		except RuntimeError:  # pragma: no cover
			_cur = None
		if (
			st.pending is not None
			and st.pending is not _cur
			and not st.pending.done()
		):
			return None
		root = self._session_root(session_id)
		if not root:
			return None
		try:
			gstore = GoalStore(root)
			goal = gstore.current(session_id)
			if goal is None or goal.status != STATUS_ACTIVE or goal.pending_complete:
				return None
			cap = resolved_max_rounds(goal, default_goal_round_cap())
			# 即将开的是第 goal.rounds 轮：rounds > cap 说明已无余量。
			if int(goal.rounds) > cap:
				return None
			if self._turn_running(session_id):
				return None
			return goal, cap
		except Exception:  # noqa: BLE001
			_logger.debug("goal precheck failed session=%s", session_id, exc_info=True)
			return None

	async def _submit_round(
		self, session_id: str, goal_id: str, round_no: int, cap: int
	) -> bool:
		"""合成轮提交（42 号起委托共享通道）：「继续」+ 41 号标记头。

		返回 True = 引擎已接受（HTTP 200，turn 将 detached 续跑）。分离式提交：
		拿到响应头即返回，不等待轮次结束——settlement 时本预约 task 已收尾，
		``_schedule`` 不会被未完成的 pending 卡住（2026-09-05 停摆修正）。
		复用整条管线：T31 durable 模式 / T_now 注入 / 权限 ASK / 持久化 / goal 绑定。
		"""
		_logger.info(
			"goal round submit session=%s goal=%s round=%s/%s",
			session_id,
			goal_id,
			round_no,
			cap,
		)
		try:
			from server.synthetic_round import submit_synthetic

			return await submit_synthetic(
				session_id,
				"继续",
				surface="goal-driver",
				extra_headers={GOAL_ROUND_HEADER: f"{goal_id}@{round_no}@{cap}"},
			)
		except Exception:  # noqa: BLE001
			_logger.debug(
				"goal round submit failed session=%s", session_id, exc_info=True
			)
			return False


# 模块单例（照 get_turn_runner 范式）。
_driver: GoalRoundDriver | None = None


def get_goal_round_driver() -> GoalRoundDriver:
	global _driver
	if _driver is None:
		_driver = GoalRoundDriver()
	return _driver
