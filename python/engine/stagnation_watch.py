"""停滞监测（StagnationWatch）—— todo 工作契约的执行侧信号源。

与 repeat_guard 分工：
- RepeatCallGuard 管"同一签名反复跑"；
- ZeroHitTracker 管"换着花样搜、次次空"；
- StagnationWatch 管"todo 状态机层面的停滞"，四类信号：
  1) 无契约启动：预算过半仍没有任何 TodoWrite（完成定义/最小交付路径缺失）；
  2) 卡死：清单长时间无真实状态变化（工具调用数 + 墙钟进度双条件，宁漏勿误）；
  3) 震荡：同一项 completed→重开 反复（验收标准或方法可能有误）；
  4) 走过场：条目"创建即完成"批量出现（completed 缺乏中间验证动作）。

安全语义（与 repeat_guard 同源）：
- 只提醒、永不拒执行；advice 走模块级槽位，由 pre_llm_inject 在既有
  repeat_guard 块内消费（T_now，不新增注册条目、不动 T_NOW_BLOCK_HARD_CAP）；
- 每类信号每次 submit 至多触发一次（防提醒噪音）；
- 默认仅在基准评测最小档案（XEYO_BENCH_MINIMAL=1）启用；
  XEYO_TODO_CONTRACT=0 一键关闭（应急回滚开关）；常规 GUI 会话零影响；
- watch 本体零 I/O、零 LLM 调用；observe 只做计数与集合运算。
"""

from __future__ import annotations

import os
import time as _time_mod
from typing import Any

from tools.todo_write_tool.constants import TODO_WRITE_TOOL_NAME

#: 可替换时钟（测试 monkeypatch 点；生产即 time.time）。
_now = _time_mod.time

# ── 开关 ────────────────────────────────────────────────────────────

#: 契约与停滞监测总开关：仅 bench 档案默认启用；"0" 显式关闭。
STALL_ENV_KILL = "XEYO_TODO_CONTRACT"


def stagnation_enabled() -> bool:
	if os.environ.get(STALL_ENV_KILL, "").strip() == "0":
		return False
	return os.environ.get("XEYO_BENCH_MINIMAL", "").strip() == "1"


# ── 阈值（保守档；宁漏勿误）─────────────────────────────────────────

def _env_int(name: str, default: int) -> int:
	raw = os.environ.get(name, "").strip()
	if not raw:
		return default
	try:
		value = int(raw)
	except (TypeError, ValueError):
		return default
	return value if value > 0 else default


def _env_float(name: str, default: float) -> float:
	raw = os.environ.get(name, "").strip()
	if not raw:
		return default
	try:
		value = float(raw)
	except (TypeError, ValueError):
		return default
	return value if value > 0 else default


#: 无契约启动：墙钟进度阈值（有死线时）；无死线回退工具调用数阈值。
NO_CONTRACT_WALL_FRAC = _env_float("XEYO_STALL_NO_CONTRACT_FRAC", 0.5)
NO_CONTRACT_CALLS = _env_int("XEYO_STALL_NO_CONTRACT_CALLS", 30)
#: 卡死：自上次清单真实状态变化以来的工具调用数 + 墙钟进度（双条件）。
STUCK_CALLS = _env_int("XEYO_STALL_STUCK_CALLS", 15)
STUCK_WALL_FRAC = _env_float("XEYO_STALL_STUCK_FRAC", 0.30)
#: 震荡：同一项 completed→重开 次数。
THRASH_TIMES = _env_int("XEYO_STALL_THRASH_TIMES", 2)
#: 走过场："创建即完成"条目数。
RUBBER_STAMP_ITEMS = _env_int("XEYO_STALL_RUBBER_STAMP", 3)
#: 契约 nudge（recency 提醒）：前 N 次工具调用且尚无清单时，每轮注入。
#: 一次性长提醒对弱模型无效（p4 raman 实测：50% advice 送达被无视）——
#: 改为早期窗口每轮短促命令，趁注意力未被数据输出淹没前建立契约。
NUDGE_TURNS = _env_int("XEYO_STALL_NUDGE_TURNS", 4)

NUDGE_TEXT = (
	"[契约] 工作契约尚未建立。下一步必须先用 TodoWrite 写："
	"2-4 条「验收:」开头的可检验验收项 + 首批构成最小端到端交付路径的"
	"执行项；在此之前不要开始新的探索。"
)


# ── 模块级当前提醒（单进程单 loop；与 repeat_guard 同型）────────────

_CURRENT_STALL_ADVICE: str = ""


def publish_stall_advice(text: str) -> None:
	global _CURRENT_STALL_ADVICE
	_CURRENT_STALL_ADVICE = (text or "").strip()


def current_stall_advice() -> str:
	return _CURRENT_STALL_ADVICE


def clear_stall_advice() -> None:
	global _CURRENT_STALL_ADVICE
	_CURRENT_STALL_ADVICE = ""


class StagnationWatch:
	"""跟踪一次 submit 内 todo 状态机的停滞信号；只产出提醒文本。

	observe 在工具准入处调用（与 RepeatCallGuard.observe 同点）；
	TodoWrite 全量替换/按 id 合并都携带完整清单，此处统一按"提交快照"解析。
	"""

	def __init__(self, budget: Any = None) -> None:
		self._budget = budget
		self._calls = 0
		self._todo_seen = False
		self._last_change_calls = 0
		self._status: dict[str, str] = {}
		self._reopens: dict[str, int] = {}
		self._instant_complete = 0
		self._fired: set[str] = set()

	# ── 内部 ──

	def _wall_frac(self) -> float | None:
		"""墙钟进度 0..1；无死线返回 None。"""
		b = self._budget
		if b is None:
			return None
		deadline = getattr(b, "wall_deadline_ts", None)
		start = getattr(b, "wall_started_ts", None)
		if deadline is None or start is None or start >= deadline:
			return None

		total = deadline - start
		if total <= 0:
			return None
		return min(1.0, max(0.0, (_now() - start) / total))

	def _fire(self, key: str, text: str) -> None:
		if key in self._fired:
			return
		self._fired.add(key)
		publish_stall_advice(text)

	# ── 对外 ──

	def observe(self, tool_name: str, input_data: Any) -> None:
		"""工具准入点观察；禁用或非关注信号时立即返回（零开销路径）。"""
		if not stagnation_enabled():
			return
		self._calls += 1

		if tool_name == TODO_WRITE_TOOL_NAME:
			self._observe_todo(input_data)
		else:
			self._check_stuck()

		if not self._todo_seen:
			# 契约 nudge（recency 窗口）：前 N 次工具调用内开始注入短促命令。
			# 槽位单值持久 → 之后每轮模型请求都注入（即每轮重复），直到契约
			# 建立被清或被更强信号替换；已有真信号（_fired 非空）时不抢位。
			# 窗口过后无清单 → no_contract（50% 墙钟/30 调用）会接管更强话术。
			if self._calls <= NUDGE_TURNS and not self._fired:
				publish_stall_advice(NUDGE_TEXT)
			self._check_no_contract()

	def _observe_todo(self, input_data: Any) -> None:
		todos = None
		if isinstance(input_data, dict):
			todos = input_data.get("todos")
		if not isinstance(todos, list):
			return
		# 契约首次建立：清掉残留的 nudge 文本（过期提醒不再挂在槽里）。
		if not self._todo_seen:
			clear_stall_advice()
		self._todo_seen = True
		changed = False
		seen_ids: set[str] = set()
		for raw in todos:
			if not isinstance(raw, dict):
				continue
			item_id = str(raw.get("id") or "").strip()
			status = str(raw.get("status") or "").strip()
			if not item_id or status not in ("pending", "in_progress", "completed"):
				continue
			seen_ids.add(item_id)
			prev = self._status.get(item_id)
			if prev is None:
				# 首次出现即 completed：无中间验证动作的走过场候选。
				if status == "completed":
					self._instant_complete += 1
					if self._instant_complete >= RUBBER_STAMP_ITEMS:
						self._fire(
							"rubber_stamp",
							"[停滞] 检测到多项「创建即完成」（无中间验证动作）。"
							"completed 必须有真实证据：先跑验证命令/读文件核对，"
							"再标完成并在条目后附一行证据。",
						)
				changed = True
			elif prev != status:
				changed = True
				if prev == "completed" and status in ("pending", "in_progress"):
					self._reopens[item_id] = self._reopens.get(item_id, 0) + 1
					if self._reopens[item_id] >= THRASH_TIMES:
						self._fire(
							"thrash",
							"[停滞] 同一项已反复完成又重开 2 次：该项的验收标准或"
							"方法可能有误。停下重新核对真实要求，再决定继续或换法。",
						)
			self._status[item_id] = status
		# 消失的条目（全量替换删项）也视为变化。
		if set(self._status) - seen_ids:
			changed = True
			for gone in set(self._status) - seen_ids:
				self._status.pop(gone, None)
		if changed:
			self._last_change_calls = self._calls
		self._check_stuck()

	def _check_no_contract(self) -> None:
		frac = self._wall_frac()
		if frac is not None:
			if frac >= NO_CONTRACT_WALL_FRAC:
				self._fire(
					"no_contract",
					f"[停滞] 任务预算已用 {int(frac*100)}% 仍无 todo 清单。立即用 "
					"TodoWrite 产出：2-4 条可检验验收项（文件存在/命令 exit 0/指标"
					"阈值，禁止空泛表述）+ 首批构成最小端到端交付路径的执行项，再继续。",
				)
			return
		if self._calls >= NO_CONTRACT_CALLS:
			self._fire(
				"no_contract",
				"[停滞] 已累计 30+ 次工具调用仍无 todo 清单。立即用 TodoWrite 产出："
				"2-4 条可检验验收项 + 首批构成最小端到端交付路径的执行项，再继续。",
			)

	def _check_stuck(self) -> None:
		if not self._todo_seen:
			return
		idle = self._calls - self._last_change_calls
		if idle < STUCK_CALLS:
			return
		frac = self._wall_frac()
		if frac is not None and frac < STUCK_WALL_FRAC:
			return
		self._fire(
			"stuck",
			f"[停滞] 清单已 {idle} 次工具调用无任何状态变化，当前项疑似卡死。"
			"考虑：拆小该步骤 / 换方法 / 先推进最小交付路径并落盘成果。",
		)

	def reset(self) -> None:
		"""同一实例复用时的 submit 级重置。"""
		self._calls = 0
		self._todo_seen = False
		self._last_change_calls = 0
		self._status.clear()
		self._reopens.clear()
		self._instant_complete = 0
		self._fired.clear()
		clear_stall_advice()
