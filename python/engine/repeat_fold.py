"""同签名 · 字节级同输出折叠（R2'）——空转去噪，不做任何拦截。

判别（零误杀取向）
------------------
- 死循环 = 同签名（RepeatCallGuard.semantic_key 语义归一）且输出摘要**逐字节相同**；
- 合法轮询（后台 job 状态、长任务进度）输出通常含时间戳/进度 → 天然不命中；
- 只要求与**上一次**该签名输出相同，连续计数（``seq``）；输出一变即重置。

动作（不改历史语义）
-------------------
- 连续第 ``fold_after`` 次（默认 3）相同输出：把**该次**将写入 store / 送给模型
  的内容替换为一行解释性折叠行（首次完整输出仍在历史前部，信息无损）；
- 之后同签名持续相同：每轮只放一行**极短**计数占位（``[同前, 第 N 次]``），
  保持 tool_use ↔ tool_result 配对完整（崩溃恢复 / 投影不再重复展示整段原文）。
- **永不拒执行**：调用照常跑，只裁剪"与上次完全相同、无新增信息"的展示体积。

不变量
------
- 纯函数式状态机（每 submit 新建 → 用户输入级重置，与 RepeatCallGuard 同步）；
- 不触碰 MessageStore 的历史条目——只在结果**写入前**决定替换文本；
- 折叠行含 ``[fold]`` 前缀，与既有 [repeat] 提醒文案互不冲突（测试可精确匹配）。
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

from engine.repeat_guard import semantic_key

DEFAULT_FOLD_AFTER = 3

#: 结果等价档默认触发次数：同工具第 N 次出现相同内容（N=1 首次完整，
#: N≥2 为等价重复）。默认 3——与逐字节档同底线（R2' 契约：前两次原文
#: 保留，给足模型看清的机会）；``XEYO_FOLD_EQUIV_AT`` 可调激进档。
#: 属行为账本方案（engine/loop_ledger.py）的消费端之一，受总开关
#: XEYO_LOOP_LEDGER 管控。
DEFAULT_FOLD_EQUIV_AT = 3

#: 超短占位（seq > fold_after 时使用）：既保持配对又几乎零 token。
_REPEAT_SHORT = "[fold] 与上一条输出相同（第 {n} 次连续）；已有可见完整副本。"
#: 触发档的解释行：出现一次，点明引擎在做什么（C1 同精神：纯事实，
#: 不带"请继续/请换参数"类劝导）。
_FOLD_EXPLAIN = (
	"[fold] 同一签名的第 {n} 次连续相同输出；已有可见完整副本，"
	"引擎已折叠后续重复内容以节省上下文。"
)
#: 结果等价档（loop_ledger 方案）：同工具、**不同参数**但输出内容完全相同
#: ——"换着花样调但结果全是旧的"的瘦身档；纯事实措辞，同受措辞测试执法。
_FOLD_EQUIV = (
	"[fold] 本次输出与该工具既往某次输出完全相同（第 {n} 次等价结果）——"
	"引擎已折叠重复内容以节省上下文。"
)


def _fold_equiv_at() -> int:
	raw = os.environ.get("XEYO_FOLD_EQUIV_AT", "").strip()
	if raw:
		try:
			v = int(raw)
			if v >= 2:
				return v
		except ValueError:
			pass
	return DEFAULT_FOLD_EQUIV_AT

def _equiv_enabled() -> bool:
	"""等价档随行为账本总开关（XEYO_LOOP_LEDGER=0 → 只保留原逐字节档）。"""
	return os.environ.get("XEYO_LOOP_LEDGER", "").strip() != "0"


def _digest(content: Any) -> str:
	try:
		text = str(content or "")
		return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]
	except Exception:  # noqa: BLE001
		return ""


#: 折叠行尾部事实头的首行长度上限（超长即截断）。
_FACT_HEAD_CHARS = 80

#: **不计入折叠**的模板回执前缀：这些是引擎/宿主写给模型的"当下事实"
#: （审批超时、权限拒绝、工具异常、被中止），不是工具观测到的证据。
#: 折叠它们 = 把"这次审批又超时了"藏起来，模型会把"环境在拒"误读成"工具坏了"
#: ——2026-09-20 实测：本会话 6 次折叠全部落在 `Approval unavailable…` 上，
#: 且折叠提示不含被折内容 ⇒ 完全看不出命令到底跑没跑。
_NO_FOLD_RECEIPTS = (
	"Approval unavailable",
	"Permission denied",
	"tool error:",
	"[loop_break]",
	"aborted by user",
	"missing_read:",
)


def _is_receipt(text: str) -> bool:
	"""是否为引擎/宿主模板回执（不参与折叠计数，每次都必须可见）。"""
	body = str(text or "").lstrip()
	return any(body.startswith(prefix) for prefix in _NO_FOLD_RECEIPTS)


def _facts_line(original: str) -> str:
	"""被折内容的**结构性事实**头：首行 + 行数 + 字节数。

	折叠后信息必须无损：纯替换成一行提示会让模型连「这条到底是不是同一个
	结果」都要靠再跑一次确认（折叠行本身不携带被折内容的任何痕迹）。
	"""
	body = str(original or "").strip()
	if not body:
		return "（内容：空输出）"
	lines = body.splitlines()
	head = lines[0][:_FACT_HEAD_CHARS]
	if len(lines[0]) > _FACT_HEAD_CHARS:
		head += "…"
	return f"（内容：{head} · {len(lines)} 行 · {len(body.encode('utf-8'))} 字节）"


def _with_facts(fold_text: str, original: str) -> str:
	return fold_text + _facts_line(original)


class IdenticalResultFold:
	"""跟踪 submit 内每个 (tool, semantic_key) 相邻输出的字节级一致性。

	``process()`` 返回 ``(text_to_store, folded)``：未命中折叠返回原文 + False；
	命中返回折叠/占位文本 + True。输出变化即重置连续计数（合法轮询豁免）。
	"""

	def __init__(self, *, fold_after: int = DEFAULT_FOLD_AFTER) -> None:
		self.fold_after = max(2, int(fold_after))
		#: key → (last_digest, seq)
		self._state: dict[str, tuple[str, int]] = {}
		#: tool → 等价重复连续计数（新内容出现即清零）。
		self._equi_seq: dict[str, int] = {}
		#: (tool, 摘要) → 最近完整副本下标；同时承担已见内容集合。
		self._full_at: dict[tuple[str, str], int] = {}

	def process(
		self,
		tool_name: str,
		input_data: Any,
		content: Any,
		*,
		msg_index: int | None = None,
		visible_from: int = 0,
	) -> tuple[str, bool]:
		"""决定写入 store 的文本。返回 (text, folded)。未命中返回原文 + False。

		两档判定独立计数，逐字节档（同签名相邻相同）优先于等价档
		（同工具跨签名同内容）——前者文案更具体。均为纯替换：调用照常执行。

		三条准入（2026-09-20 事故后收窄，逐条对应实测）：
		1. **模板回执不折**：审批超时 / 权限拒绝 / 工具异常 / 被中止是引擎与宿主
		   写给模型的"当下事实"，不是工具观测到的证据——折掉它等于把"环境在拒"
		   藏起来（本会话 6 次折叠全部落在 `Approval unavailable…` 上）；
		2. **收益门**：折叠行（含事实头）必须真的比原文短，否则保持原文——
		   把 `ok` 换成一行提示是"更长且更少信息"；
		3. **可见性前提**：同内容旧副本必须仍在投影可见面内（``msg_index`` /
		   ``visible_from``：压缩游标、C1 冻结边界），否则折掉的是唯一一份。
		"""
		d = _digest(content)
		text = str(content or "")
		foldable = bool(d) and not _is_receipt(text)
		key = f"{tool_name}\x00{semantic_key(tool_name, input_data)}"

		# 等价档状态推进（先于逐字节档：seen 集合需登记本次摘要）。
		equi_n = 0
		if _equiv_enabled() and foldable:
			if (tool_name, d) in self._full_at:
				self._equi_seq[tool_name] = self._equi_seq.get(tool_name, 0) + 1
			else:
				self._equi_seq[tool_name] = 0
			# 该内容第 N 次出现（N≥2 为等价重复）
			equi_n = self._equi_seq[tool_name] + 1

		if not foldable:
			# 模板回执 / 空输出：不进"同签名相邻"档，每次原文可见。
			self._state.pop(key, None)
			return text, False

		last_digest, seq = self._state.get(key, ("", 0))
		if d == last_digest:
			seq += 1
		else:
			seq = 1
		self._state[key] = (d, seq)
		candidate = None
		if seq >= self.fold_after:
			candidate = (
				_FOLD_EXPLAIN.format(n=seq)
				if seq == self.fold_after
				else _REPEAT_SHORT.format(n=seq)
			)
		elif (
			_equiv_enabled()
			and equi_n >= _fold_equiv_at()
		):
			candidate = _FOLD_EQUIV.format(n=equi_n)
		if candidate and self._still_visible(tool_name, d, visible_from):
			projected, folded = self._maybe_fold(candidate, text)
			if folded:
				return projected, True
		# Only full copies can authorize later folding, including with ledger off.
		self._full_at[(tool_name, d)] = int(msg_index) if msg_index is not None else 0
		return text, False

	def _maybe_fold(self, fold_text: str, original: str) -> tuple[str, bool]:
		"""收益门：折叠行（含事实头）必须真的比原文短，否则保持原文。"""
		candidate = _with_facts(fold_text, original)
		if len(candidate) >= len(original):
			return original, False
		return candidate, True

	def _still_visible(self, tool_name: str, digest: str, visible_from: int) -> bool:
		"""同工具同内容的最近完整副本是否仍在当前投影可见面内。

		``visible_from<=0``（无压缩 / 调用方未提供）→ 视为可见（保持既有行为）。
		"""
		if int(visible_from or 0) <= 0:
			return True
		first = self._full_at.get((tool_name, digest))
		return first is not None and int(first) >= int(visible_from)

	def reset(self) -> None:
		self._state.clear()
		self._equi_seq.clear()
		self._full_at.clear()
