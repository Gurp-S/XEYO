"""发射面 prompt 的**唯一口径与来源标签**（只做取值与标注，不动任何判定）。

同一根因的事故在本仓已出现两次，形态都是"同一个量、多个定义、字段不带来源"：

1. ``_region_tokens(messages)``：全部未压历史，实测为实发 prompt 的 **2.5~5 倍**
   （``XEYO_WSC_GATE_EMITTED_BASIS`` 口径档就是为它加的，见 ``memory/memory_switches``）。
2. ``token_len(json.dumps(messages))``：**投影前原史**，实测同一会话同一时刻账上
   ``input_tokens`` 265k、厂商 receipt ``prompt_tokens`` 27k，差 **10 倍**。

本模块给出权威口径与标签，沿用 ``memory/memory_switches`` 的既有权约定
（``head_basis`` / ``prompt_basis`` 分行，"两把尺不许并成一个数"）：

**有厂商实发就用实发；拿不到才退回估算，且必须带 ``prompt_basis``。**

取不到 receipt 绝不抛错、绝不阻塞折叠（fail-open）。
"""

from __future__ import annotations

#: 权威口径：``working.last_prompt_tokens``（上一枪厂商实发的 prompt token）。
LAST_PROMPT_TOKENS = "last_prompt_tokens"

#: 回退口径：调用方给的估算（多为投影前原史）。与实发**不同源**，读侧必须按标签区分，
#: 不得与 :data:`LAST_PROMPT_TOKENS` 的值并成一个数比较。
ESTIMATE_MESSAGES = "estimate_messages"

#: 第三种口径：本次**发射面估算**（``wsc_timing.measure``：当前发射面 + 匹配 receipt 的
#: overhead）。既不是厂商实发，也不是投影前原史——同样是估算，但它描述"这一枪将要发出去的
#: 东西"，不描述"磁盘上的原史"。细分取法见账行 ``basis`` 字段。
ESTIMATE_EMISSION = "estimate_emission"

#: 无来源标签：历史账行形态，或新增调用点漏标时由 ``runtime._note_fold_attempt`` 静默补上
#: （不拒绝、不改数值）。读侧见到它只能当"来源未知"，不得当权威量。
UNLABELLED = "unlabelled"


def provider_prompt_tokens(working) -> int:
	"""厂商实发的上一枪 prompt token；0 = 本进程还没有 receipt（首枪 / 离线重放）。"""
	return max(0, int(getattr(working, "last_prompt_tokens", 0) or 0))


def prompt_tokens_with_basis(
	working, *, fallback_tokens: int, fallback_basis: str = ESTIMATE_MESSAGES
) -> tuple[int, str]:
	"""返回 ``(tokens, prompt_basis)``。

	有 receipt ⇒ ``(实发, LAST_PROMPT_TOKENS)``；否则 ⇒ ``(fallback, fallback_basis)``。
	"""
	last = provider_prompt_tokens(working)
	if last > 0:
		return last, LAST_PROMPT_TOKENS
	return max(0, int(fallback_tokens or 0)), fallback_basis
