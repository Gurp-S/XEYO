"""预算跟踪器（Turn / Tool Call / token / USD）。

一次 submit 内，一次 Turn = 一次模型 API 请求/响应周期。
每一次实际进入 Agent tool interface 的工具执行尝试 = 1 个 Tool Call。
同一 Turn 可以包含多个 Tool Call；Tool Call 不会自动增加 Turn。
"""

from __future__ import annotations

import math

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from usage import pricing as pricing_mod
from usage.pricing import estimate_cny, official_cost_cny
from engine.lifecycle import AgentLifecycle

_log = logging.getLogger("xeyo.budget")


DEFAULT_MAX_TURNS = 256
# 每回合允许进入工具接口的最大执行次数。真正的**并发**上限由编排层信号量
# (tools/orchestration._max_concurrency, 默认 10) 控制（即 maxParallelToolCalls）。
# 这里只是"总执行数"的高护栏：放宽到 64，避免误杀合法的大
# 并行批次；配合 MAX_TOOL_CAP_STREAK 的连续轮判断，不再把单轮爆发当失控。
DEFAULT_MAX_TOOL_CALLING = 64
MAX_GRACE_TURNS = 3
# 工具态共享收尾窗口的触发：先前只要单轮爆发(一个大并行批次)达到单轮工具
# 配额就立刻开启 3 轮倒计时，会把整个 submit 的剩余轮次烧光(grace-cliff)。
# 现改为"连续 MAX_TOOL_CAP_STREAK 轮持续顶满/超出单轮配额"才进入收尾，单轮
# 爆发只拒绝溢出调用、不影响整轮窗口；单轮配额依然按每回合重置。
MAX_TOOL_CAP_STREAK = 2
MAX_TURN_WARNING = "回合数已接近上限。"
MAX_TOOL_WARNING = "工具调用数已接近上限。"
# 墙钟硬停告警（R1'：仅在显式武装 wall_hard_stop 时才可能触发收尾窗口）。
WALL_STOP_NOTICE = "时间预算已到上限（已进入收尾窗）。"


def wall_hard_stop_from_env() -> bool:
	"""默认关（产品会话无墙钟武装 → 行为零变化）。

	评测/宿主显式要求"到点收尾"时置 ``XEYO_WALL_HARD_STOP=1``：
	墙钟走尽后引擎内优雅收尾（而非等外部硬杀在模型半句上掐断）。
	"""
	raw = os.environ.get("XEYO_WALL_HARD_STOP", "0").strip().lower()
	return raw in ("1", "true", "yes", "on")


def _positive_int_from_env(name: str, default: int) -> int:
	raw = os.environ.get(name, "").strip()
	if not raw:
		return default
	try:
		value = int(raw)
	except (TypeError, ValueError):
		return default
	return value if value > 0 else default


def max_turns_from_env(default: int = DEFAULT_MAX_TURNS) -> int:
	"""读取 XEYO_MAX_TURNS；未设置或非法时返回 default。"""
	return _positive_int_from_env("XEYO_MAX_TURNS", default)


def max_tool_calling_from_env(default: int = DEFAULT_MAX_TOOL_CALLING) -> int:
	"""读取 XEYO_MAX_TOOL_CALLING；未设置或非法时返回 default。"""
	return _positive_int_from_env("XEYO_MAX_TOOL_CALLING", default)


def default_budget_usd_from_env() -> float | None:
	"""读取旁路默认预算档 ``XEYO_BUDGET_DEFAULT_USD``（2026-09-09 Phase 1，默认关）。

	未设 → None → 行为零变化（兜底仍只有 max_turns，与历史完全一致）。
	设为正数后：当会话 config 与 ``XEYO_MAX_BUDGET_USD`` 均未限额时，以该值
	作为 per-submit USD 硬顶——超限走既有 ``over_budget → budget_usd`` 停止
	链，零新机制。注意：档位生效即 ``usd_limit is not None``，费用折算不再
	强制 local_only（与显式限额同一条价格链）。
	"""
	raw = os.environ.get("XEYO_BUDGET_DEFAULT_USD", "").strip()
	if not raw:
		return None
	try:
		v = float(raw)
	except (TypeError, ValueError):
		return None
	return v if math.isfinite(v) and v > 0 else None


def max_budget_usd_from_env() -> float | None:
	"""读取 ``XEYO_MAX_BUDGET_USD``；未设置/非法时回落默认档，均无则 None（不限额）。"""
	raw = os.environ.get("XEYO_MAX_BUDGET_USD", "").strip()
	if raw:
		try:
			v = float(raw)
		except (TypeError, ValueError):
			v = None
		if v is not None and math.isfinite(v) and v >= 0:
			return v
	return default_budget_usd_from_env()


@dataclass
class BudgetTracker:
	"""追踪一次 submit 内的 Turn、Tool Call、token 与 USD 预算。

	``max_turns`` 限制模型 API 请求次数；一次响应中的多个工具只属于一个
	Turn。``max_tool_calling`` 限制当前 Turn 中实际进入 Agent tool interface
	的执行尝试次数。成功、失败、重试（重新进入接口）和并行工具都分别计数；
	工具内部没有重新经过 Agent tool interface 的子操作不计数。

	任一软上限首次触发后建立共享的 ``MAX_GRACE_TURNS`` 模型 Turn 收尾窗口，
	只发送一次对应的临时提醒，不写入消息历史。两个上限不会各自再提供一组
	grace Turn；用户中断、token 和 USD 预算仍然优先硬停止。
	"""

	max_turns: int = DEFAULT_MAX_TURNS
	max_tool_calling: int = DEFAULT_MAX_TOOL_CALLING
	max_tokens: int | None = None
	turn_count: int = 0
	current_turn_tool_calls: int = 0
	grace_turns_used: int = 0
	grace_started: bool = False
	grace_reason: str | None = None
	# 连续"顶满/超出单轮工具配额"的回合数(用于工具态共享收尾窗口触发)。
	tool_cap_streak: int = 0
	_turn_hit_tool_cap: bool = field(default=False, init=False, repr=False)
	used_tokens: int = 0
	usd_limit: float | None = None
	used_usd: float = 0.0
	last_usage: dict[str, Any] | None = None
	last_usage_tokens: int = 0
	# 无权威价目时为 None（费用未知，不是 0）——见 ``usd_gate_note``。
	last_usage_usd: float | None = 0.0
	last_usage_cny: float | None = 0.0
	used_cny: float = 0.0
	# 价目来源三态：api / estimate / unpriced（与 usage.ledger.cost_source 同口径）。
	last_cost_source: str = "estimate"
	# 价目权威来源：usage / vendor / user / none（见 usage.pricing.price_authority）。
	last_price_authority: str = ""
	# 已计价 / 无价目的回合数。有任一回合无价目 ⇒ 已花费金额不可判定，
	# USD 闸对这些模型不生效（既不误拦，也不假装算得出「还剩多少额度」）。
	usd_priced_turns: int = 0
	usd_unpriced_turns: int = 0
	_usd_gate_logged: bool = field(default=False, init=False, repr=False)
	provider: str = "deepseek"
	model: str = "deepseek-v4-flash"
	prices: dict[str, float] | None = None
	_pending_notices: list[str] = field(default_factory=list, init=False, repr=False)
	_notified_reasons: set[str] = field(default_factory=set, init=False, repr=False)
	_hard_stop_reason: str | None = field(default=None, init=False, repr=False)
	# 墙钟死线（禀赋①：时间感来源）。由调用方（评测适配器/会话）在 submit 前设置；
	# prepare_next_turn 时检查 80%/90% 阈值，经既有 runtime notice 通道注入（一次性）。
	wall_deadline_ts: float | None = field(default=None, init=False, repr=False)
	wall_started_ts: float | None = field(default=None, init=False, repr=False)
	# R1'：墙钟硬停是否武装。默认 False（产品零变化）；宿主显式置 True 后，
	# 墙钟走尽 → 进入共享收尾窗口（与 max_turns 同一条 grace → wrap-up 链路）。
	wall_hard_stop: bool = field(default=False, init=False, repr=False)
	# submit 内部生命周期；执行层读取，模型不可见。
	lifecycle: AgentLifecycle = field(default_factory=AgentLifecycle, repr=False)

	def set_wall_deadline(self, deadline_ts: float | None, *, started_ts: float | None = None) -> None:
		"""设置墙钟死线与（可选）起始时刻；None 清除。reset_for_new_submit 不清除。"""
		self.wall_deadline_ts = deadline_ts
		if started_ts is not None:
			self.wall_started_ts = started_ts

	def wall_remaining_s(self, now: float | None = None) -> float | None:
		"""距墙钟死线的剩余秒数；未设置死线 → None（= 无时间感，不做时间相关决策）。"""
		if self.wall_deadline_ts is None:
			return None
		return max(0.0, self.wall_deadline_ts - (now if now is not None else time.time()))

	def arm_wall_stop(self, enabled: bool | None = None) -> None:
		"""武装/解除墙钟硬停。None → 跟随 XEYO_WALL_HARD_STOP 环境变量。

		默认不自动武装——产品会话即使设了死线（仅时间感播报）也不会被引擎
		硬停；只有宿主显式要求"到点收尾"（评测适配器/用户时间预算）才生效。
		"""
		self.wall_hard_stop = wall_hard_stop_from_env() if enabled is None else bool(enabled)

	def check_wall_deadline(self, now: float | None = None) -> str | None:
		"""按墙钟进度排队 80%/90% 收尾提醒（每阈值一次）。

		武装状态下走尽 100% → 进入共享收尾窗口（grace + wrap-up），
		返回硬停原因由调用方裁决；未武装 → 到点仅返回 None（只播报，不硬停）。
		"""
		if self.wall_deadline_ts is None:
			return None
		now = time.time() if now is None else now
		start = self.wall_started_ts
		if start is None or start >= self.wall_deadline_ts:
			return None
		total = self.wall_deadline_ts - start
		if total <= 0:
			return None
		elapsed = now - start
		pending_notice: str | None = None
		for threshold, label in ((0.9, "90%"), (0.8, "80%")):
			key = f"wall_{label}"
			if key in self._notified_reasons:
				continue
			if elapsed >= total * threshold:
				self._notified_reasons.add(key)
				remain_min = max(0, int((self.wall_deadline_ts - now) / 60))
				# C6 裁决：预算信息纯事实，不加行动指令。
				notice = f"时间预算已用 {label}，剩余约 {remain_min} 分钟。"
				# `_queue_notice` 只认 reason 名（max_turns / max_tool_calling / wall），
				# 传播报正文会落进它的 else 分支被静默丢弃 ⇒ 走自由文本通道。
				# ⚠️2026-10-03 实测更正：自由文本通道本身**当前不落到模型**——
				# `consume_runtime_notice()` 在 query_loop 取走后只塞进
				# ``InjectContext.runtime_notice``，而 prompt/ 下读该字段的点为 0
				# （``evals/changedetect/trace.py:134`` 记 wrap_up/runtime_notice
				# 两类块"已从模型可见面撤除"，本模块 docstring 却说"播报照旧"）。
				# ⇒ 这一行只是把文本放进**正确的**那条队列；队列末端要接回还是要
				# 删净，属对外可见文本的政策，待用户裁定。执行层（grace/硬停/配额）不受影响。
				self.queue_runtime_notice(notice)
				# 同一时刻可能既越 90% 又走尽 100%：先记下播报，不提前 return，
				# 让下方武装分支仍能在此次调用里启动收尾 grace。
				pending_notice = notice
				break
		# R1'：100% 走尽且武装 → 进入共享收尾窗口（grace → forced_wrap_up）。
		if self.wall_hard_stop and elapsed >= total and not self.grace_started:
			self._start_grace("wall")
		try:
			self.lifecycle.observe_wall(
				max(0.0, self.wall_deadline_ts - now),
				armed=self.wall_hard_stop,
			)
		except Exception:  # noqa: BLE001 — 生命周期只做旁路观测
			pass
		return pending_notice

	def _start_grace(self, reason: str) -> None:
		"""首次触发软上限时建立共享收尾窗口并排队临时提醒。"""
		if self.grace_started:
			return
		self.grace_started = True
		self.grace_reason = reason
		try:
			self.lifecycle.enter_finalizing(reason)
		except Exception:  # noqa: BLE001 — 生命周期旁路不能阻断预算闸
			pass
		self._queue_notice(reason)

	def _queue_notice(self, reason: str) -> None:
		"""按固定顺序排队一次性提醒，避免两个软上限重复或叠加 grace。"""
		if reason == "max_turns":
			notice = MAX_TURN_WARNING
		elif reason == "max_tool_calling":
			notice = MAX_TOOL_WARNING
		elif reason == "wall":
			notice = WALL_STOP_NOTICE
		else:
			return
		if reason in self._notified_reasons:
			return
		self._notified_reasons.add(reason)
		if notice not in self._pending_notices:
			self._pending_notices.append(notice)
		self._pending_notices.sort(
			key=lambda value: 0 if value == MAX_TURN_WARNING else 1
		)

	def check_usd_waterline(self) -> None:
		"""USD 预算 80%/90% 水位事实播报（每阈值一次，纯数字，无行动指令）。

		与墙钟 80%/90% 走同一 runtime notice 通道；仅 ``usd_limit`` 为正时
		武装。默认档/显式限额共用——模型在硬停前能看到水位事实，自行收敛。
		有任一回合无价目时整个播报关闭：此时 ``used_usd`` 只覆盖可计价部分，
		报出的百分比是假的（要么虚低要么虚高）。
		"""
		if not self.usd_limit or self.usd_limit <= 0 or self.used_usd <= 0:
			return
		if self.usd_unpriced_turns > 0:
			return
		for threshold, label in ((0.9, "90%"), (0.8, "80%")):
			key = f"usd_{label}"
			if key in self._notified_reasons:
				continue
			if self.used_usd >= self.usd_limit * threshold:
				self._notified_reasons.add(key)
				self.queue_runtime_notice(
					f"USD 预算已用 {label}"
					f"（已花费 ${self.used_usd:.4f} / 上限 ${self.usd_limit:.4f}）。"
				)
				break

	def prepare_next_turn(self) -> bool:
		"""判断下一次模型 API 请求是否允许，并在边界排队软提醒。

		该方法不增加 Turn。只有真正调用 ``begin_turn`` 时才会计入下一次
		模型响应，因此 Tool Call 达到上限不会凭空制造或消耗一个 Turn。
		"""
		# 墙钟死线检查（禀赋①）：80%/90% 阈值提醒走既有 runtime notice 通道。
		try:
			self.check_wall_deadline()
		except Exception:  # noqa: BLE001 — 墙钟提醒 best-effort：失败不阻断预算推进
			pass
		# USD 水位事实播报（默认档/显式限额共用，纯数字）。
		try:
			self.check_usd_waterline()
		except Exception:  # noqa: BLE001 — USD 播报 best-effort：失败不阻断预算推进
			pass
		if self.grace_started:
			if self.turn_count >= self.max_turns:
				self._queue_notice("max_turns")
			if self.grace_turns_used < MAX_GRACE_TURNS:
				return True
			self._hard_stop_reason = self.grace_reason or "max_turns"
			return False

		if self.turn_count < self.max_turns:
			return True

		self._start_grace("max_turns")
		return True

	def allow_next_turn(self) -> bool:
		"""兼容旧调用方的下一 Turn 判定入口。"""
		return self.prepare_next_turn()

	def begin_turn(self) -> None:
		"""进入一次真实模型 API 请求，并重置该 Turn 的 Tool Call 计数。"""
		if self.grace_started:
			self.grace_turns_used += 1
		# 工具态收尾(grace-cliff 修复)：只有"连续 MAX_TOOL_CAP_STREAK 轮持续
		# 顶满/超出单轮工具配额"才启动工具收尾窗口；单轮爆发仅拒绝溢出调用，
		# 不开启整轮倒计时。上一轮未满配额则清零连续计数。
		if self._turn_hit_tool_cap:
			self.tool_cap_streak += 1
		else:
			self.tool_cap_streak = 0
		self._turn_hit_tool_cap = False
		self.turn_count += 1
		self.current_turn_tool_calls = 0
		if not self.grace_started and self.tool_cap_streak >= MAX_TOOL_CAP_STREAK:
			self._start_grace("max_tool_calling")

	def begin_tool_call(self) -> bool:
		"""在实际进入 Agent tool interface 前尝试占用一个 Tool Call 配额。

		返回 False 表示本次请求被预算层跳过，调用方必须生成确定性的错误
		ToolResult，且不能进入工具实现。该方法无 await，在并发任务间保持
		单次事件循环内的原子计数。

		这里只排队一次性"工具使用过多"提醒并标记本轮顶满配额，**不**立即
		开启共享收尾窗口——单轮大并行批次只能靠提醒让模型收敛，不能把整个
		submit 的剩余轮次烧光(grace-cliff)。
		"""
		if self.current_turn_tool_calls >= self.max_tool_calling:
			self._queue_notice("max_tool_calling")
			return False
		self.current_turn_tool_calls += 1
		if self.current_turn_tool_calls >= self.max_tool_calling:
			self._turn_hit_tool_cap = True
			self._queue_notice("max_tool_calling")
		return True

	def consume_runtime_notice(self) -> str | None:
		"""取出仅用于下一次模型请求的临时提醒，不写入历史或 SSE。"""
		if not self._pending_notices:
			return None
		notice = "\n".join(self._pending_notices)
		self._pending_notices.clear()
		return notice

	def queue_runtime_notice(self, text: str) -> bool:
		"""排队一条一次性运行时提醒（按文本去重），返回是否新增。

		供引擎层（如重复调用守卫）注入"停止重复"类提示；与软上限提醒共用
		同一下一轮消费通道。空文本与完全相同的文本会被忽略。
		"""
		clean = str(text or "").strip()
		if not clean or clean in self._pending_notices:
			return False
		if clean in self._notified_reasons:
			return False
		self._notified_reasons.add(clean)
		self._pending_notices.append(clean)
		self._pending_notices.sort(
			key=lambda value: 0 if value == MAX_TURN_WARNING else 1
		)
		return True

	@property
	def hard_stop_reason(self) -> str | None:
		"""共享 grace 用尽后的结构化停止原因。"""
		return self._hard_stop_reason

	@property
	def grace_turns_remaining(self) -> int:
		return max(0, MAX_GRACE_TURNS - self.grace_turns_used) if self.grace_started else 0

	# 兼容旧代码可能使用的名称；语义仍然是当前 Turn 的实际 Tool Call 数。
	@property
	def tool_call_count(self) -> int:
		return self.current_turn_tool_calls

	def consume_tokens(self, n: int) -> None:
		"""消耗 n 个 token（兼容旧调用；新增逻辑请走 add_usage）。"""
		self.used_tokens += int(n or 0)

	def _usage_usd(
		self,
		usage: dict[str, Any],
		hit: int,
		miss: int,
		out: int,
		ts: float | None = None,
	) -> float | None:
		"""折算一轮 usage 的 USD；**没有权威价目时返回 None**（不编价）。

		厂商在 usage 里显式给出金额时原样采用；会话显式登记过价目（``prices``）按其折算；
		否则按「用户选择模型的实时价 → 本地登记价目」折算。三者都没有 ⇒ ``None``：
		历史行为是回落到通用默认价（2.0/8.0 USD 的保守上限），那是拿别家价算出
		「还剩多少额度」，2026-09-27 起不再允许（见 ``usd_gate_note``）。
		"""
		for key in ("usd", "cost_usd", "usage_usd", "total_cost_usd"):
			if key not in usage or usage[key] is None:
				continue
			try:
				n = float(usage[key])
			except (TypeError, ValueError):
				continue
			if math.isfinite(n) and n >= 0:
				self.last_price_authority = "usage"
				return n
		if self.prices is not None:
			table = self.prices
			self.last_price_authority = "user"
			return (
				hit * table.get("input_hit", 0.0)
				+ miss * table.get("input_miss", 0.0)
				+ out * table.get("output", 0.0)
			) / 1_000_000.0
		value, basis = pricing_mod.estimate_usd_checked(
			provider=self.provider,
			model=self.model,
			usage=usage,
			local_only=self.usd_limit is None,
			ts=ts,
		)
		self.last_price_authority = basis
		return value

	def _usage_cny(
		self,
		usage: dict[str, Any],
		ts: float | None = None,
	) -> float | None:
		"""返回本轮人民币费用；**没有权威价目时返回 None**。

		厂商金额优先，否则按与 USD 同源的权威价目估算。未设 USD 上限时不联网
		（与 ``_usage_usd`` 的 local_only 一致），只走本地价目；设了上限才拉厂商
		实时价，确保费用与预算来自同一条价格链。
		"""
		api_cost = official_cost_cny(usage)
		if api_cost is not None:
			return api_cost
		return estimate_cny(
			provider=self.provider,
			model=self.model,
			usage=usage,
			ts=ts if ts is not None else time.time(),
			local_only=self.usd_limit is None,
		)

	def add_usage(self, usage: dict[str, Any] | None, ts: float | None = None) -> None:
		"""以厂商响应 usage 累计本轮 token 与 USD；无价目的回合只计 token。"""
		if not isinstance(usage, dict) or not usage:
			return
		hit, miss, out = pricing_mod.split_usage(usage)
		prompt = miss + hit
		self.last_usage = dict(usage)
		official_total = 0
		try:
			official_total = max(0, int(usage.get("total_tokens") or 0))
		except (TypeError, ValueError):
			official_total = 0
		round_tokens = official_total or (prompt + out)
		self.last_usage_tokens = round_tokens
		self.last_usage_usd = self._usage_usd(usage, hit, miss, out, ts=ts)
		if self.last_usage_usd is not None and not math.isfinite(self.last_usage_usd):
			self.last_usage_usd = None
		api_cost = official_cost_cny(usage)
		if api_cost is not None:
			self.last_cost_source = "api"
			self.last_usage_cny = api_cost
		else:
			cny = self._usage_cny(usage, ts=ts)
			if cny is None:
				# 无价目：金额未知 —— 落 None（不是 0），也不进 used_usd / used_cny 合计。
				self.last_cost_source = "unpriced"
			else:
				self.last_cost_source = "estimate"
			self.last_usage_cny = cny
		if self.last_usage_cny is not None and not math.isfinite(self.last_usage_cny):
			self.last_usage_cny = None
		self.used_tokens += round_tokens
		if self.last_usage_usd is None:
			self.usd_unpriced_turns += 1
		else:
			self.usd_priced_turns += 1
			self.used_usd += self.last_usage_usd
		if self.last_usage_cny is not None:
			self.used_cny += self.last_usage_cny
		if self.usd_unpriced_turns:
			self._note_usd_gate_inactive()

	@property
	def usd_gate_note(self) -> str:
		"""部分费用未知的中文事实（供界面 / 日志，不进模型上下文）。

		空串 = 费用均可计价（或本来就没设上限）。无价目时说明已知小计
		仍受上限约束，但不能由它计算准确剩余额度。
		"""
		if not self.usd_limit:
			return ""
		if self.usd_unpriced_turns <= 0:
			return ""
		return (
			f"{self.provider}/{self.model} 有 {self.usd_unpriced_turns} 轮费用未知，"
			"总费用和剩余额度不可判定；预算闸按已知费用小计执行。"
		)

	def _note_usd_gate_inactive(self) -> None:
		"""日志留痕一次：部分费用未知，剩余额度不可判定。"""
		if self._usd_gate_logged:
			return
		self._usd_gate_logged = True
		try:
			_log.info("%s", self.usd_gate_note)
		except Exception:  # noqa: BLE001 — 日志通道不得影响预算闸
			pass

	@property
	def over_budget(self) -> bool:
		"""是否超过美元上限（>= 即停，与 token 超限口径一致）。

		无价目的回合不编价；``used_usd`` 仍是已知非负费用的下界。
		下界达到上限即可判定超限，即使部分回合费用未知。
		"""
		if self.usd_limit is None:
			return False
		return self.used_usd >= self.usd_limit

	def over_token_budget(self) -> bool:
		"""是否超过 token 预算。"""
		return self.max_tokens is not None and self.used_tokens > self.max_tokens

	def reset_for_new_submit(
		self,
		max_turns: int | None = None,
		max_tool_calling: int | None = None,
		usd_limit: float | None = None,
		provider: str | None = None,
		model: str | None = None,
		prices: dict[str, float] | None = None,
	) -> None:
		"""每次 submit 重置 Turn、Tool Call、grace 与本轮费用。"""
		self.turn_count = 0
		self.current_turn_tool_calls = 0
		self.grace_turns_used = 0
		self.grace_started = False
		self.grace_reason = None
		self.tool_cap_streak = 0
		self._turn_hit_tool_cap = False
		self._pending_notices.clear()
		self._notified_reasons.clear()
		self._hard_stop_reason = None
		self.lifecycle.reset()
		self.used_tokens = 0
		self.used_usd = 0.0
		self.last_usage = None
		self.last_usage_tokens = 0
		self.last_usage_usd = 0.0
		self.last_usage_cny = 0.0
		self.used_cny = 0.0
		self.last_cost_source = "estimate"
		self.last_price_authority = ""
		self.usd_priced_turns = 0
		self.usd_unpriced_turns = 0
		self._usd_gate_logged = False
		if max_turns is not None:
			self.max_turns = int(max_turns)
		if max_tool_calling is not None:
			self.max_tool_calling = int(max_tool_calling)
		self.usd_limit = usd_limit
		if provider is not None:
			self.provider = provider
		if model is not None:
			self.model = model
		if prices is not None:
			self.prices = prices

	def lifecycle_snapshot(self) -> dict[str, object]:
		"""返回 submit 生命周期的机器快照，不进入模型上下文。"""
		try:
			return self.lifecycle.snapshot().to_dict()
		except Exception:  # noqa: BLE001
			return {"phase": "running", "reason": "", "revision": 0}

	def mark_terminal(self, outcome: str, reason: str = "") -> None:
		"""在 QueryEngine 收尾时写入一次 submit 终态。"""
		if outcome not in {"succeeded", "failed", "stopped"}:
			outcome = "failed"
		try:
			self.lifecycle.finish(outcome, reason)
		except Exception:  # noqa: BLE001
			pass
