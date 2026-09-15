"""循环熔断（LoopBreaker）—— 工具准入层的"无进展路径持续报错"（铁律 #3 的执行层形态）。

缘起（2026-09-14 事故）
----------------------
``sess_mu0mkitk_5aehjt.jsonl`` 里同一条 Bash 命令**连续重复 166 次**：``repeat_guard``
越阈即静默（只在第 3/5/8 次报过），``repeat_fold`` 又要求输出**逐字节相同**（那条命令
尾挂第二个 rg，166 次无一命中）⇒ 执行层与注意力层**同时归零**，止损只剩 max_turns /
墙钟。上游同源实现（DSH ``packages/guard/repeat-tool-reminder``）把"越过末档即静默"
写成了已知局限，并明确**拒绝**做阻断（理由是合法轮询会被误杀）。

本模块的答案：**判定放到工具准入层，且永不静默**——同路径持续无进展时该次调用不执行，
每次回同一条中性结果型 ToolResult，直到签名或结果变化。误杀由四条豁免 + 半开探针兜住。

判据（全部逐字节可判定，零启发式）
----------------------------------
L1 同签名连续：``(tool, semantic_key)`` 连续 ≥ N（默认 6）。
L2 周期重复：最近 ``k·C`` 个签名构成周期 k（k=2,3）的重复——抓"换个近邻签名接着转"。
L3 结果等价：同签名**且结果摘要与上次相同**连续 ≥ K（默认 3）——真正零进展。
L4 同工具无新内容：同工具连续 ≥ M（默认 4）次结果都是**本回合已见过的摘要**——
   抓"换着花样调但结果全是旧的"（参数可不同，逐字节判据）。

不要踩的坑（2026-09-14 实测的误判风险）
--------------------------------------
- **结果变化不得清零 L1/L2**：166 次事故每次输出都不同（尾挂第二个 rg），若把"有新结果
  即清零"用在 L1 上，该形态直接逃逸。L1/L2 只由**换签名**重置（调用级判据）；"结果
  等价"只属于 L3。
- **成本闸门不落地为拒执行**：按签名归属的 token 占比会误伤"整回合 bash 密集"的正常工作
  （不同命令=不同签名，但同一工具占比高）。本模块只**记录**占比作为证据（``note_turn_tokens``
  + 取证行里的 ``tok_share``），等有数据再决定是否升级为拒执行（AGENTS 硬规矩 4）。
- 合法轮询（后台 job 状态）即使被命中，也有半开探针放行；分页续读（offset 递增）与交互
  工具（``tools.meta.REPEAT_EXEMPT_TOOLS``）**transparent**（既不计数也不重置，与 DSH 的
  ``exclude`` 同语义）。

动作（唯一动作：该次调用不执行）
--------------------------------
返回一条 ``ToolResult(content="[loop_break] …", is_error=True, metadata={...})``，同形于既有
``[max_tool_calling reached; tool call was not executed]``：措辞只含事实（工具 / 次数 / 形态），
零劝导（受 ``tests/test_loop_ledger.py`` 的禁导演词执法），**每次都报**（拒绝不更新"上次
签名"，同签名再来一次继续拒——goose ``RepetitionInspector`` 同构）。

开关与阈值（``XEYO_LOOP_BREAK=0`` 全关，默认开）
-----------------------------------------------
``XEYO_LOOP_BREAK_AT``（L1，默认 6）· ``XEYO_LOOP_BREAK_CYCLE_AT``（L2 周期重复次数，默认 5）
· ``XEYO_LOOP_BREAK_EQUIV_AT``（L3，默认 3）· ``XEYO_LOOP_BREAK_FAMILY_AT``（L4，默认 4）
· ``XEYO_LOOP_BREAK_PROBE_AFTER``（半开探针，默认 3）。显式配置非法**当场报错**，
不静默回退默认（对齐 DSH 的 fail-loud 立场：``thresholds`` 空 / 非整数 / 低于下限即抛）。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

from engine.repeat_guard import (
	EXEMPT_TOOLS,
	canonical_input,
	is_pagination_continuation,
	semantic_key,
)

#: L1 同签名连续阈值（DSH 上游用 [3,5,8] 递进提醒；本模块取"明确病态"的连续档）。
DEFAULT_SAME_AT = 6
#: L2 周期重复次数（周期 k 重复 C 次才判）。
DEFAULT_CYCLE_AT = 5
#: L3 同签名同结果连续阈值。
DEFAULT_EQUIV_AT = 3
#: L4 同工具"无新内容"连续阈值。
DEFAULT_FAMILY_AT = 4
#: 半开探针：连续拒绝 R 次后放行一次（合法长轮询的自愈出口）。
DEFAULT_PROBE_AFTER = 3
#: L2 检测的周期长度（k=1 归 L1）。
CYCLE_LENGTHS = (2, 3)
#: 拒绝文案里的参数预览上限（DSH 同款 argumentsPreviewChars；只截预览，不截判据）。
ARGS_PREVIEW_CHARS = 300
#: 签名历史窗口（L2 只需 k·C ≤ 15，留足余量）。
_MAX_HISTORY = 64
#: 取证文件名（落 ``usage_dir()``，尊重 ``XEYO_USAGE_DIR``）。
LEDGER_NAME = "loop_break.jsonl"


def loop_break_enabled() -> bool:
	"""总开关：``XEYO_LOOP_BREAK=0/false/no/off`` 关闭（零行为变化）。"""
	raw = (os.environ.get("XEYO_LOOP_BREAK", "1") or "1").strip().lower()
	return raw not in ("0", "false", "no", "off")


def _env_int(name: str, default: int, minimum: int = 1) -> int:
	"""读阈值；显式配置非法**当场报错**（不静默回退默认）。"""
	raw = (os.environ.get(name, "") or "").strip()
	if not raw:
		return default
	try:
		value = int(raw)
	except (TypeError, ValueError):
		raise ValueError(f"{name}={raw!r} 不是整数（循环熔断阈值）") from None
	if value < minimum:
		raise ValueError(f"{name}={value} 小于下限 {minimum}（循环熔断阈值）")
	return value


def _digest(text: Any) -> str:
	"""结果/签名的稳定短摘要（空内容返回空串 → 跳过计数）。"""
	try:
		body = str(text or "")
		if not body.strip():
			return ""
		return hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()[:16]
	except Exception:  # noqa: BLE001 — 摘要失败只跳过本次计数
		return ""


@dataclass(frozen=True)
class Refusal:
	"""一次被拒执行的调用（事实包：形态 / 次数 / 签名摘要 / 模型可见文本）。"""

	kind: str
	count: int
	sig_digest: str
	text: str

	def metadata(self) -> dict[str, Any]:
		"""ToolResult.metadata 载荷（与 wrap_up_rejected / budget_rejected 同族）。"""
		return {
			"loop_refused": True,
			"loop_kind": self.kind,
			"loop_count": self.count,
			"loop_sig": self.sig_digest,
		}


class LoopBreaker:
	"""一次 submit 内的循环熔断器（纯内存状态 + 可选 JSONL 取证）。

	生命周期与 ``RepeatCallGuard`` / ``IdenticalResultFold`` 同步：每 submit 新建
	（用户输入级重置）。**不写 MessageStore 历史**——只在准入处产出 ToolResult。
	"""

	def __init__(
		self,
		*,
		exempt: frozenset[str] | None = None,
		same_at: int | None = None,
		cycle_at: int | None = None,
		equiv_at: int | None = None,
		family_at: int | None = None,
		probe_after: int | None = None,
		enabled: bool | None = None,
	) -> None:
		self.enabled = loop_break_enabled() if enabled is None else bool(enabled)
		self.exempt = frozenset(EXEMPT_TOOLS) if exempt is None else frozenset(exempt)
		self.same_at = (
			same_at
			if same_at is not None
			else _env_int("XEYO_LOOP_BREAK_AT", DEFAULT_SAME_AT, 2)
		)
		self.cycle_at = (
			cycle_at
			if cycle_at is not None
			else _env_int("XEYO_LOOP_BREAK_CYCLE_AT", DEFAULT_CYCLE_AT, 2)
		)
		self.equiv_at = (
			equiv_at
			if equiv_at is not None
			else _env_int("XEYO_LOOP_BREAK_EQUIV_AT", DEFAULT_EQUIV_AT, 2)
		)
		self.family_at = (
			family_at
			if family_at is not None
			else _env_int("XEYO_LOOP_BREAK_FAMILY_AT", DEFAULT_FAMILY_AT, 2)
		)
		self.probe_after = (
			probe_after
			if probe_after is not None
			else _env_int("XEYO_LOOP_BREAK_PROBE_AFTER", DEFAULT_PROBE_AFTER, 1)
		)
		# L1/L2：调用级链状态（只由"换签名"重置）。
		self._last_key: str | None = None
		self._same_count = 0
		self._history: list[str] = []
		# L3：同签名结果等价（结果变化即回到 1）。
		self._equiv_count: dict[str, int] = {}
		self._last_digest: dict[str, str] = {}
		# L4：同工具"结果摘要本回合是否已见"（新内容即清零）。
		self._seen_by_tool: dict[str, set[str]] = {}
		self._no_new_streak: dict[str, int] = {}
		# 熔断阀：连续拒绝计数 + 待放行的探针。
		self._denied: dict[str, int] = {}
		self._probe: set[str] = set()
		# 取证：token 归属（近似：记到"该轮前最后一次放行的签名"上）。
		self._tokens_by_key: dict[str, int] = {}
		self._tokens_total = 0

	# ── 准入判定 ──────────────────────────────────────────────────

	def admit(self, tool_name: str, input_data: Any) -> Refusal | None:
		"""准入判定：返回 ``Refusal`` = 该次调用不执行；``None`` = 放行。

		计数在这里发生，**含被拒的尝试**（拒绝不更新"上次签名"），所以同签名再来
		一次仍然命中：这是"永不静默"的实现方式。
		"""
		if not self.enabled:
			return None
		if tool_name in self.exempt:
			return None
		if is_pagination_continuation(tool_name, input_data):
			return None
		key = semantic_key(tool_name, input_data)
		if key == self._last_key:
			self._same_count += 1
		else:
			self._same_count = 1
			self._last_key = key
		self._history.append(key)
		if len(self._history) > _MAX_HISTORY:
			del self._history[: len(self._history) - _MAX_HISTORY]

		kind, count = self._verdict(tool_name, key)
		if kind is None:
			self._denied.pop(key, None)
			return None
		if self._denied.get(key, 0) >= self.probe_after:
			# 半开探针：连续拒 R 次后放行一次。合法长轮询（后台 job 状态）据此
			# 以 1/(R+1) 的速率继续；探针取到新结果即清零，仍同结果则继续拒。
			self._denied[key] = 0
			self._probe.add(key)
			return None
		self._denied[key] = self._denied.get(key, 0) + 1
		refusal = Refusal(
			kind=kind,
			count=count,
			sig_digest=_digest(key),
			text=self._text(kind, tool_name, count, input_data),
		)
		self._log(refusal, tool_name, key)
		return refusal

	def _verdict(self, tool_name: str, key: str) -> tuple[str | None, int]:
		"""四档判据的优先级裁决（L1 最具体，L4 最泛）。"""
		if self._same_count >= self.same_at:
			return "L1", self._same_count
		period = self._cycle_period()
		if period:
			return "L2", period
		equiv = self._equiv_count.get(key, 0)
		if equiv >= self.equiv_at:
			return "L3", equiv
		streak = self._no_new_streak.get(tool_name, 0)
		if streak >= self.family_at:
			return "L4", streak
		return None, 0

	def _cycle_period(self) -> int:
		"""尾部窗口是否构成周期 k 的重复（k ∈ CYCLE_LENGTHS）；返回 k 或 0。"""
		for k in CYCLE_LENGTHS:
			need = k * self.cycle_at
			if len(self._history) < need:
				continue
			tail = self._history[-need:]
			period = tail[-k:]
			if all(tail[i] == period[i % k] for i in range(need)):
				return k
		return 0

	@staticmethod
	def _text(kind: str, tool_name: str, count: int, input_data: Any) -> str:
		"""中性结果型文案（纯事实，零劝导；禁导演词执法见 tests/test_loop_ledger.py）。"""
		if kind == "L2":
			return (
				f"[loop_break] call not executed (tool={tool_name}; "
				f"period-{count} cycle of identical calls)"
			)
		preview = canonical_input(input_data)[:ARGS_PREVIEW_CHARS]
		if kind == "L3":
			return (
				f"[loop_break] identical call not executed (tool={tool_name}; "
				f"{count} identical results in a row; args={preview})"
			)
		if kind == "L4":
			return (
				f"[loop_break] call not executed (tool={tool_name}; "
				f"{count} calls in a row returned only previously-seen results; args={preview})"
			)
		return (
			f"[loop_break] identical call not executed (tool={tool_name}; "
			f"{count} identical calls in a row; args={preview})"
		)

	# ── 结果登记 ──────────────────────────────────────────────────

	def observe_result(self, tool_name: str, input_data: Any, content: Any) -> None:
		"""工具结果写入 store 前登记（L3 等价 / L4 无新内容 / 探针自愈）。"""
		if not self.enabled or tool_name in self.exempt:
			return
		key = semantic_key(tool_name, input_data)
		digest = _digest(content)
		if not digest:
			return
		prev = self._last_digest.get(key)
		if digest == prev:
			self._equiv_count[key] = self._equiv_count.get(key, 0) + 1
		else:
			self._equiv_count[key] = 1
		self._last_digest[key] = digest

		seen = self._seen_by_tool.setdefault(tool_name, set())
		if digest in seen:
			self._no_new_streak[tool_name] = self._no_new_streak.get(tool_name, 0) + 1
		else:
			seen.add(digest)
			self._no_new_streak[tool_name] = 0

		if key in self._probe:
			self._probe.discard(key)
			if digest != prev:
				# 探针拿到新结果 = 有进展：该签名状态清零，熔断解除。
				self._equiv_count[key] = 1
				self._denied.pop(key, None)

	def note_turn_tokens(self, tokens: Any) -> None:
		"""把本回模型调用的 token 记到"该轮前最后一次放行的签名"上（L4 证据用）。

		归属是近似（一次模型调用可能产出多个工具调用），只用于**取证**，不驱动判据。
		"""
		if not self.enabled or not self._last_key:
			return
		try:
			count = int(tokens or 0)
		except (TypeError, ValueError):
			return
		if count <= 0:
			return
		self._tokens_by_key[self._last_key] = (
			self._tokens_by_key.get(self._last_key, 0) + count
		)
		self._tokens_total += count

	# ── 取证 ──────────────────────────────────────────────────────

	def token_share(self, key: str) -> float:
		"""某签名的 token 占比（0–1；无数据返回 0.0）。"""
		if self._tokens_total <= 0:
			return 0.0
		return self._tokens_by_key.get(key, 0) / self._tokens_total

	def _log(self, refusal: Refusal, tool_name: str, key: str) -> None:
		"""拒绝落一行 JSONL（``usage_dir()/loop_break.jsonl``）；失败只留痕。"""
		if (os.environ.get("XEYO_LOOP_BREAK_LEDGER", "1") or "1").strip() == "0":
			return
		try:
			import time

			from usage.ledger import usage_dir

			row = {
				"ts": time.time(),
				"kind": refusal.kind,
				"tool": tool_name,
				"sig": refusal.sig_digest,
				"count": refusal.count,
				"denied_n": self._denied.get(key, 0),
				"tok_share": round(self.token_share(key), 4),
				"enabled": True,
			}
			path = usage_dir() / LEDGER_NAME
			path.parent.mkdir(parents=True, exist_ok=True)
			with path.open("a", encoding="utf-8") as handle:
				handle.write(json.dumps(row, ensure_ascii=False) + "\n")
		except Exception:  # noqa: BLE001 — 取证失败不得影响主链路
			import logging

			logging.getLogger(__name__).debug(
				"loop_break ledger write failed", exc_info=True
			)

	def reset(self) -> None:
		"""用户输入级重置（同一实例复用时）。"""
		self._last_key = None
		self._same_count = 0
		self._history.clear()
		self._equiv_count.clear()
		self._last_digest.clear()
		self._seen_by_tool.clear()
		self._no_new_streak.clear()
		self._denied.clear()
		self._probe.clear()
		self._tokens_by_key.clear()
		self._tokens_total = 0