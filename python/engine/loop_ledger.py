"""行为账本（LoopLedger）—— 循环信号计数器：只计数、只报数。

与既有机制分工
--------------
- ``RepeatCallGuard`` 管"同签名反复跑"（参数级递进提醒）；
- ``IdenticalResultFold`` 管"同签名同输出"的字节级折叠（替换写入文本）；
- ``ZeroHitTracker`` 管"换着花样搜、次次空"；
- ``LoopLedger`` 管**行为循环**的三个逐字节可判定信号，供两处消费：
  ① ``repeat_fold`` 的"结果等价档"折叠（瘦身，见 repeat_fold.py）；
  ② ``pre_llm_inject`` repeat_guard 块内的行为账本（≤3 行纯数据，每
     episode 一次，T_now）。

理念对齐（2026-09-08 红线 + 用户裁决 19:04）
-------------------------------------------
- 不拒执行、不触发收尾、不生成劝导文本——账本只报事实数字，措辞由
  ``tests/test_loop_ledger.py`` 机器执法（禁导演词正则）；
- 所有判定均为逐字节 / 集合运算，零启发式、零猜测（SWE-agent 教训：
  语义级"停滞"判断不得作为任何动作依据）；
- 有真增益即清零：读大文件不同段落、跑测试见新输出，都是新内容，不计数。

信号定义
--------
s1 结果等价：同工具的调用，本次结果 sha256 摘要与该工具既往某次**完全一致**
  （参数可以不同——"换着花样调但结果全是旧的"正是循环特征；不要求相邻，
  中途插入其他工具不重置，由"新内容清零"承担连续性。render 锚点化：报
  本次所属等价组的既往次数与参数变体种数，均为逐字节事实）；
s2 内容已见：本次结果全文 sha256 已在本回合出现过（跨工具）；
s3 首句重复：assistant 输出文本前 30 字符与上一轮逐字节相同（连续计数）。

开关与阈值
----------
- ``XEYO_LOOP_LEDGER=0`` 全关（应急回滚；同时关闭 repeat_fold 等价档）；
- ``XEYO_LOOP_LEDGER_AT="3,4,3"`` 覆盖账本渲染阈值（s1,s2,s3）；
- ``XEYO_FOLD_EQUIV_AT`` 覆盖 fold 等价档触发次数（默认 2）。

生命周期：每 submit 新建（与 RepeatCallGuard / IdenticalResultFold 同步的
用户输入级重置）；实例由 query_loop 持有，pre_llm_inject 经 InjectContext
直读当前计数（**不走** publish/clear 槽位）。注入节奏（用户裁决
2026-09-08 晚）：每个信号每个 episode 只 render 一次——达阈值首次注入后
静默，该信号被新内容清零（新 episode）时重新武装；只报"重复了什么"，
不报工具调用汇总。
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

#: 渲染阈值默认值（s1 结果等价 / s2 内容已见 / s3 首句重复）。
DEFAULT_LEDGER_AT = (3, 4, 3)

#: 首句比较长度（前 30 字符，与事故形态"重复开场白"对齐）。
_HEAD_LEN = 30


def ledger_enabled() -> bool:
	"""总开关：``XEYO_LOOP_LEDGER=0`` 关闭（信号采集、账本渲染、fold 等价档）。"""
	return os.environ.get("XEYO_LOOP_LEDGER", "").strip() != "0"


def ledger_thresholds_from_env() -> tuple[int, int, int]:
	raw = os.environ.get("XEYO_LOOP_LEDGER_AT", "").strip()
	if raw:
		try:
			vals = tuple(int(x) for x in raw.split(",") if x.strip())
			if len(vals) == 3 and all(v > 0 for v in vals):
				return vals  # type: ignore[return-value]
		except ValueError:
			pass
	return DEFAULT_LEDGER_AT


def content_digest(content: Any) -> str:
	"""结果内容的稳定摘要（16 hex）；空内容返回空串（跳过计数）。"""
	try:
		text = str(content or "")
		if not text.strip():
			return ""
		return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]
	except Exception:  # noqa: BLE001
		return ""


def params_digest(params: Any) -> str:
	"""调用参数的稳定摘要（16 hex）；只存摘要不存原文，序列化失败回退 str()。"""
	try:
		try:
			text = json.dumps(params, ensure_ascii=False, sort_keys=True, default=str)
		except Exception:  # noqa: BLE001
			text = str(params)
		return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]
	except Exception:  # noqa: BLE001
		return ""


#: 内部别名：``observe_tool`` 的形参 ``params_digest`` 会遮蔽模块级同名函数，
#: 这里留一份引用供 callee 侧契约收敛使用。
_params_digest_of = params_digest


def assistant_head(text: Any) -> str:
	"""assistant 输出文本的首句比较键（前 30 字符，strip 后取）。"""
	try:
		return str(text or "").strip()[:_HEAD_LEN]
	except Exception:  # noqa: BLE001
		return ""


class LoopLedger:
	"""一次 submit 内的循环信号计数器（纯内存，零 IO）。

	``observe_tool`` 在工具结果写入 store 前调用；``observe_assistant`` 在
	assistant 消息写入 store 前调用；``render`` 由 pre_llm_inject 每轮请求
	组装时调用——未达任何阈值返回空串（常态零字节）。
	"""

	def __init__(
		self,
		*,
		at: tuple[int, int, int] | None = None,
		exempt_tools: frozenset[str] | None = None,
	) -> None:
		self._at = at or ledger_thresholds_from_env()
		self._exempt = exempt_tools if exempt_tools is not None else frozenset()
		# s1：tool → 结果摘要 → 等价组（组内次数 + 参数摘要集合）。
		# 锚点化（2026-09-08 晚）：render 报"本次调用所属等价组"的既往次数
		# 与参数变体种数——只报逐字节事实关系，不下"循环"类结论。
		self._tool_groups: dict[str, dict[str, dict[str, Any]]] = {}
		self._s1 = 0
		self._last_equiv: tuple[str, int, int] | None = None
		# s2：本回合出现过的全部结果摘要。
		self._seen: set[str] = set()
		self._s2 = 0
		# s3：连续相同首句轮数。
		self._last_head = ""
		self._s3 = 0
		# 工具调用总数（内部统计；render 不输出——用户裁决 2026-09-08 晚：
		# 只注入"重复了什么"，汇总行是噪音）。
		self._tool_calls = 0
		# 每 episode 一次性注入状态（用户裁决 2026-09-08 晚）：达阈值后只
		# render 一次；对应信号被新内容清零即重新武装（新的循环 episode）。
		self._notified = [False, False, False]  # [s1, s2, s3]

	@property
	def s1(self) -> int:
		return self._s1

	@property
	def s2(self) -> int:
		return self._s2

	@property
	def s3(self) -> int:
		return self._s3

	@property
	def tool_calls(self) -> int:
		return self._tool_calls

	def observe_tool(
		self, tool_name: str, content: Any, params_digest: str | None = None
	) -> None:
		"""工具结果写入 store 前登记（豁免工具 / 空内容 / 总开关关 → 跳过）。

		``params_digest`` 可选（``params_digest(tu.input)``）；缺省时等价组
		不记参数变体，render 省略变体段——旧调用方零破坏。**非 str 入参
		（误传原始 params）当场归一为摘要，不抛异常**：本方法属诊断采集，
		永不因契约违反影响调用方主链路。
		"""
		if not ledger_enabled() or tool_name in self._exempt:
			return
		d = content_digest(content)
		if not d:
			return
		self._tool_calls += 1
		# s2：全文摘要跨工具查重（新内容清零 → 重新武装）。
		if d in self._seen:
			self._s2 += 1
		else:
			self._s2 = 0
			self._notified[1] = False
			self._seen.add(d)
		# s1：同工具等价组查重（换参数同结果同样计数；新内容清零）。
		groups = self._tool_groups.setdefault(tool_name, {})
		group = groups.get(d)
		if group is None:
			group = {"n": 0, "params": set()}
			groups[d] = group
			self._s1 = 0
			self._notified[0] = False  # 新 episode → 重新武装
		else:
			self._s1 += 1
		group["n"] += 1
		if params_digest:
			# callee 侧契约收敛：本参数语义是"可哈希短串摘要"，不是原始参数。
			# 调用方误传原始 params（dict/list）时当场归一为摘要，而不是抛
			# TypeError——契约违反不得把同 try 块内的防护动作连带打死
			# （2026-09-14 事故：传 dict → unhashable → [fold] 全域失效）。
			group["params"].add(
				params_digest
				if isinstance(params_digest, str)
				else _params_digest_of(params_digest)
			)
		self._last_equiv = (tool_name, group["n"], len(group["params"]))

	def observe_assistant(self, text: Any) -> None:
		"""assistant 消息写入 store 前登记首句重复（s3）。"""
		if not ledger_enabled():
			return
		head = assistant_head(text)
		if not head:
			return
		if head == self._last_head:
			self._s3 += 1
		else:
			self._s3 = 1
			self._notified[2] = False  # 新 episode → 重新武装
			self._last_head = head

	def render(self) -> str:
		"""账本数据行（纯事实，≤3 行）；未达任何阈值返回空串。

		一次性语义（用户裁决 2026-09-08 晚）：每个信号每个 episode 只
		render 一次——达阈值首次渲染后即静默，直至该信号被新内容清零
		（新 episode）重新武装。避免命中期每轮注入的 token 与注意力税。
		只报"重复了什么"（信号行），不报汇总（工具累计行已删）。

		措辞红线（测试执法）：不出现 应该/建议/请/勿/优先/推荐 等导演词，
		不带褒贬评价——只有计数与事实。
		"""
		if not ledger_enabled():
			return ""
		at1, at2, at3 = self._at
		lines: list[str] = []
		if self._s1 >= at1 and self._last_equiv and not self._notified[0]:
			tool, n, k = self._last_equiv
			line = f"- {tool}:本次结果与既往 {n - 1} 次调用结果逐字节相同"
			if k:
				line += f"(参数变体 {k} 种)"
			lines.append(line)
			self._notified[0] = True
		if self._s2 >= at2 and not self._notified[1]:
			lines.append(f"- 返回本回合已见内容的调用:{self._s2} 次")
			self._notified[1] = True
		if self._s3 >= at3 and not self._notified[2]:
			lines.append(f"- 输出首句与上一轮逐字节相同:连续 {self._s3} 轮")
			self._notified[2] = True
		if not lines:
			return ""
		return "\n".join(lines)

	def reset(self) -> None:
		"""用户输入级重置（同一实例复用时）。"""
		self._tool_groups.clear()
		self._seen.clear()
		self._s1 = self._s2 = self._s3 = 0
		self._tool_calls = 0
		self._last_equiv = None
		self._last_head = ""
		self._notified = [False, False, False]
