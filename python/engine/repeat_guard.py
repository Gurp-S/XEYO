"""重复工具调用检测（RepeatCallGuard）—— T6 递进建议制。

同一 submit 内，"(工具名, 签名)" 相同的调用按出现次数递进提醒：
- 阈值 ``[3, 5, 8]``（``XEYO_REPEAT_TOOL_ADVICE`` 逗号分隔覆盖）：
  第 1 阈短提示；后续阈值详细提醒（点名 tool / count / args 预览 ≤500 字符）；
  越过末档后**静默**（R2'：持续空转的逐字告知交给 ``engine.repeat_fold``
  的字节级折叠行——同签名且输出不变时每轮一行 ``[fold]``，此处不再刷长文）。
- **只提醒、永不拒执行**（旧版 block 语义移除；轮次/预算硬顶仍兜底死循环）。
- **denied 调用同样计数**——观察点在调用准入处，权限结果不影响计数。
- 提醒**不改写 ToolResult**：经 T_now 注入（``prompt/pre_llm_inject`` 的
  ``# Repeat guard（background only）`` 块），source-attributed。
- 每次 submit 新建 guard（用户输入即重置）；``clear_advice()`` 在轮首调用。
- 边界：签名重复但输出在变（合法轮询 / 进度推进）→ 不折叠也不长提醒——
  由 ``repeat_fold`` 的字节级判据天然豁免；此处只管"同签名计数"。

签名分两档：
- 检索型工具（Grep/Glob）：按"语义字段"归一——pattern 去成对包裹引号、
  path 统一分隔符（大小写不敏感平台词法折叠）。``output_mode`` 计入签名。
  显式 ``offset>0`` 分页续读视为刻意动作，不计入检测。
- 其余工具：回退到 "(工具名, 规范化参数)" 完全相等（canonical_input）。

豁免：AskUserQuestion 等交互工具（tools.meta.REPEAT_EXEMPT_TOOLS）；
合法轮询可在轮询方用相同签名 + 分页 offset，或经配置豁免（配置化留待 T16）。
该守卫只做计数与分类，不接触消息历史（投影字节稳定性不受影响）。
"""

from __future__ import annotations

import json
import os
import posixpath
from typing import Any

from tools.meta import REPEAT_EXEMPT_TOOLS

#: 交互 / 清单工具豁免集（源自 tools.meta）。
EXEMPT_TOOLS = frozenset(REPEAT_EXEMPT_TOOLS)

DEFAULT_ADVICE_LEVELS = (3, 5, 8)

ACTION_RUN = "run"
ACTION_ADVICE = "advice"
# 兼容旧名：T6 起不存在 block / hint 分离，两者统一为 advice。
ACTION_HINT = ACTION_ADVICE
ACTION_BLOCK = ACTION_ADVICE


def _threshold_from_env(name: str, default: int) -> int:
	raw = os.environ.get(name, "").strip()
	if not raw:
		return default
	try:
		value = int(raw)
	except (TypeError, ValueError):
		return default
	return value if value > 0 else default


def advice_thresholds_from_env() -> tuple[int, ...]:
	"""T6 递进阈值；``XEYO_REPEAT_TOOL_ADVICE="3,5,8"`` 覆盖。"""
	raw = os.environ.get("XEYO_REPEAT_TOOL_ADVICE", "").strip()
	if raw:
		try:
			vals = tuple(int(x) for x in raw.split(",") if x.strip())
			if vals and all(v > 0 for v in vals):
				return tuple(sorted(vals))
		except ValueError:
			pass
	return DEFAULT_ADVICE_LEVELS


# 旧环境变量名兼容：仍可读，映射到第一/末档（新代码建议用上面的覆盖项）。
def hint_threshold_from_env(default: int = DEFAULT_ADVICE_LEVELS[0]) -> int:
	return _threshold_from_env("XEYO_REPEAT_TOOL_HINT_AT", default)


def block_threshold_from_env(default: int = DEFAULT_ADVICE_LEVELS[-1]) -> int:
	return _threshold_from_env("XEYO_REPEAT_TOOL_BLOCK_AT", default)


# ── 模块级当前提醒（单进程单 loop；T_now 块消费）───────────────────

_CURRENT_ADVICE: str = ""


def publish_advice(text: str) -> None:
	global _CURRENT_ADVICE
	_CURRENT_ADVICE = (text or "").strip()


def current_advice() -> str:
	return _CURRENT_ADVICE


def clear_advice() -> None:
	global _CURRENT_ADVICE
	_CURRENT_ADVICE = ""


def canonical_input(input_data: Any) -> str:
	"""把工具输入规范化为稳定字符串；dict 键排序，其余 str()。"""
	if isinstance(input_data, dict):
		return json.dumps(input_data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
	return str(input_data)


#: 检索型工具：命中集合 + 输出模式决定"这次调用要什么"。
#: 路径/pattern 的书写风格折叠；分页字段不参与比较。
SEARCH_TOOLS = frozenset({"Grep", "Glob"})
_GREP_DEFAULT_OUTPUT_MODE = "files_with_matches"

#: Grep/Glob 的语义字段（大小写/多行开关会真实扩大命中集，计入）。
_SEARCH_SEMANTIC_FIELDS = (
	"pattern",
	"path",
	"glob",
	"type",
	"case_insensitive",
	"multiline",
	"output_mode",
)

#: 常见别名折叠（原始模型 JSON 可能用 -i / include 等写法）。
_PATTERN_WRAP_QUOTES = "\"'`“”‘’"


def _norm_pattern(value: Any) -> str:
	"""去首尾空白与成对包裹引号：消除书写风格造成的伪差异。"""
	s = str(value or "").strip()
	while len(s) >= 2 and s[0] in _PATTERN_WRAP_QUOTES and s[-1] == s[0]:
		s = s[1:-1].strip()
	return s


def _norm_path(value: Any) -> str:
	"""统一分隔符 + 词法折叠；空值/'.'/undefined/null 视为未指定。"""
	p = str(value or "").strip()
	if p.lower() in ("", "undefined", "null", ".", "./"):
		return ""
	p = p.replace("\\", "/")
	p = posixpath.normpath(p)
	# normcase 在大小写不敏感平台（Windows）折叠大小写；POSIX 上保持原样。
	return os.path.normcase(p)


def is_pagination_continuation(tool_name: str, input_data: Any) -> bool:
	"""offset>0 的检索是刻意分页续读，不参与重复计数。"""
	if tool_name not in SEARCH_TOOLS or not isinstance(input_data, dict):
		return False
	try:
		return float(input_data.get("offset") or 0) > 0
	except (TypeError, ValueError):
		return False


def _norm_output_mode(tool_name: str, input_data: dict[str, Any]) -> str:
	"""Grep 省略 output_mode 时按工具默认值折叠；其它检索工具保留原值。"""
	raw = input_data.get("output_mode")
	if tool_name == "Grep":
		mode = str(raw or "").strip()
		return mode or _GREP_DEFAULT_OUTPUT_MODE
	return str(raw or "").strip()


def semantic_key(tool_name: str, input_data: Any) -> str:
	"""守卫的去重键。

	Grep/Glob 用语义字段的归一化 JSON；其余工具回退 canonical_input 精确匹配。
	"""
	if tool_name in SEARCH_TOOLS and isinstance(input_data, dict):
		ci = input_data.get("case_insensitive")
		if ci is None:
			ci = input_data.get("-i")  # 常见别名
		sig = {
			"pattern": _norm_pattern(input_data.get("pattern")),
			"path": _norm_path(input_data.get("path")),
			"scope": _norm_path(input_data.get("glob") or input_data.get("include") or ""),
			"type": input_data.get("type"),
			"case_insensitive": bool(ci),
			"multiline": bool(input_data.get("multiline")),
			"output_mode": _norm_output_mode(tool_name, input_data),
		}
		return json.dumps(
			[tool_name, sig], sort_keys=True, ensure_ascii=False, separators=(",", ":")
		)
	return f"{tool_name}\x00{canonical_input(input_data)}"


class RepeatCallGuard:
	"""跟踪一次 submit 内每个 (tool, canonical_input) 的出现次数并递进提醒。

	T6：只建议、永不拒执行。阈值 [3,5,8]（可覆盖）；首次阈值给短提示，
	其后阈值给详细提醒（tool / count / args 预览）；越过末档后静默
	（R2'：持续空转告知移交 ``repeat_fold`` 的字节级折叠行）。
	denied 调用同样计数（观察点在调用准入处）。
	"""

	def __init__(
		self,
		*,
		advice_at: tuple[int, ...] | None = None,
		hint_at: int | None = None,  # 兼容旧签名：映射为首档阈值
		block_at: int | None = None,  # 兼容旧签名：忽略
	) -> None:
		if advice_at is not None and advice_at:
			self.advice_at = tuple(sorted(int(v) for v in advice_at if int(v) > 0))
		elif hint_at is not None:
			self.advice_at = (max(2, int(hint_at)),)
		else:
			self.advice_at = advice_thresholds_from_env()
		if not self.advice_at:
			self.advice_at = DEFAULT_ADVICE_LEVELS
		self._counts: dict[str, int] = {}
		self.last_advice: str = ""

	@staticmethod
	def _key(tool_name: str, input_data: Any) -> str:
		return semantic_key(tool_name, input_data)

	def observe(self, tool_name: str, input_data: Any) -> str:
		"""记录一次调用意图；返回 ACTION_RUN 或 ACTION_ADVICE。

		每次调用恰好计一次数（denied 同样计入）；命中阈值时产出提醒并发布到
		模块级 current_advice()（T_now 块消费），**不改写 ToolResult**。
		"""
		if tool_name in EXEMPT_TOOLS:
			return ACTION_RUN
		if is_pagination_continuation(tool_name, input_data):
			return ACTION_RUN
		key = self._key(tool_name, input_data)
		count = self._counts.get(key, 0) + 1
		self._counts[key] = count
		level_idx: int | None = None
		for i, th in enumerate(self.advice_at):
			if count == th:
				level_idx = i
				break
		if level_idx is None:
			if count > self.advice_at[-1]:
				# R2'：越过末档 → 静默。持续空转的逐字告知已移交 repeat_fold
				# 的字节级折叠行（同签名同输出每轮一行 [fold]）；此处再刷长文
				# 只会稀释 attention（P4 实测 advice 送达被无视）。
				return ACTION_RUN
			else:
				return ACTION_RUN
		self.last_advice = self.advice_text(
			tool_name, input_data, level_idx, count
		)
		publish_advice(self.last_advice)
		return ACTION_ADVICE

	def repeat_count(self, tool_name: str, input_data: Any) -> int:
		"""当前签名已观察到的总次数（含本次之前）；供错误文案引用。"""
		return self._counts.get(self._key(tool_name, input_data), 0)

	@staticmethod
	def advice_text(
		tool_name: str, input_data: Any, level_idx: int, count: int
	) -> str:
		"""第 1 阈短提示；后续阈值详细（点名工具/次数/参数预览 ≤500 字符）。"""
		base = f"'{tool_name}' 已用完全相同的参数连续调用 {count} 次。"
		if level_idx <= 0:
			return (
				f"[repeat] {base}若非有意，请基于已有结果直接作答，"
				"或更换参数 / 方法。"
			)
		preview = canonical_input(input_data)[:500]
		return (
			f"[repeat] {base}\n"
			f"tool: {tool_name}\n"
			f"args: {preview}\n"
			"若这是合法轮询 / 等待（如长任务状态检查），请改用带 offset 或"
			"状态参数的签名使其可区分；否则请基于已有结果直接作答，"
			"或更换参数 / 方法。"
		)

	def reset(self) -> None:
		"""清空计数与当前提醒（同一实例复用时的用户输入级重置）。"""
		self._counts.clear()
		self.last_advice = ""
		clear_advice()

	# ── 兼容旧 API（T6 前 block/hint 文案）；query_loop 不再调用。──

	@staticmethod
	def hint_notice() -> str:
		return (
			"你正在用完全相同的参数重复调用同一个工具。不要重复执行："
			"基于已有结果直接作答，或换一种参数 / 方法再试。"
		)

	@staticmethod
	def todo_hint_notice() -> str:
		return (
			"待办清单与上一次提交完全相同，这是一次无效写入。"
			"不要重复提交未变化的清单：直接继续执行下一项任务，"
			"仅在清单内容真正变化时再调用 TodoWrite。"
		)

	def block_or_hint_notice(self, tool_name: str) -> str:
		"""旧入口：保留给历史调用方；T6 主路径走 observe + current_advice。"""
		if tool_name == "TodoWrite":
			return self.todo_hint_notice()
		return self.hint_notice()


# ====== 零命中前提复核（多组不同查询全部空结果 → 建议回读原题） ======
#
# 与 RepeatCallGuard 分工：
# - RepeatCallGuard 管"同一签名反复跑"；
# - ZeroHitTracker 管"换着花样搜、次次空"——这通常意味着查找前提错了。
#
# 措辞约束：提示保持中立，只建议"回读用户原始请求 / 复核前提"，
# 不指向任何具体方向（例如不提"可能来自外部依赖"），避免把模型带偏。

ZERO_HIT_ADVICE_AT = 2


class ZeroHitTracker:
	"""跟踪一次 submit 内零命中检索的**不同语义签名**数量。"""

	def __init__(self) -> None:
		self._keys: set[str] = set()

	@staticmethod
	def is_zero_hit(tool_name: str, metadata: Any) -> bool:
		"""工具结果是否为"合法执行但零命中"（路径不存在等 error 不算）。"""
		if tool_name not in SEARCH_TOOLS:
			return False
		return bool(isinstance(metadata, dict) and metadata.get("no_match"))

	def record(self, tool_name: str, input_data: Any) -> int:
		"""登记一次零命中；返回当前**不同**签名的累计数量（重复签名不加增）。"""
		key = semantic_key(tool_name, input_data)
		self._keys.add(key)
		return len(self._keys)

	def __len__(self) -> int:
		return len(self._keys)

	@staticmethod
	def notice(count: int) -> str:
		return (
			f"[提示] 这是本次任务中第 {count} 个不同查询的空结果。"
			"你的查找前提可能有误——请先回读用户原始请求，"
			"确认目标确实存在于当前工作区后，再决定是否继续检索或更换方法。"
		)
