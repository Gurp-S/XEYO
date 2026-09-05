"""工具输出老化（Aging）— 投影层存根规格。

设计见 docs/12（老化清除）。本模块只提供纯函数与开关，不碰存储：
- 开关 ``XEYO_TOOL_AGING``（**T27：默认关**；设 ``1/true/on`` 显式开启——
  toolout 占位的恢复机制落地前保持关闭，避免原文不可找回）
- 存根两档：近档富信息（工具名+id尾8位+净化摘要+中立指引），远档折叠短存根
- 豁免：is_error 结果、TodoWrite/AskUserQuestion 等结构化结果不老化
- 摘要行净化：单行、剥标签、限长（R20 注入面 / R26 字节稳定）

恢复语义（v1）：所有被老化工具均可重跑再生；但存根本身保持中性措辞
（"answer from remaining context"），不主动劝导重跑，避免 harness 诱发重复检索。
logs/toolout 文件级恢复为后续增强（见设计文档前置依赖①）。
"""

from __future__ import annotations

import os
import re

ENV_KEY = "XEYO_TOOL_AGING"
AGING_VERSION = 1

#: 远档折叠：距冻结边界超过该消息数的存根退化为短形式（确定性，增量投影一致）
FOLD_AFTER = 64
#: 富存根摘要上限字符数（净化后）
STUB_SUMMARY_MAX = 60
#: 结构化结果豁免集（UI dock / 挂起语义依赖其原文）
EXEMPT_TOOLS = frozenset({"TodoWrite", "AskUserQuestion"})

_TAG_RE = re.compile(r"</?\s*[^>]{0,64}>")
_WS_RE = re.compile(r"\s{2,}")

_stats: dict[str, int] = {
	"stubbed_blocks": 0,
	"chars_before": 0,
	"chars_after": 0,
	"folds": 0,
}


def aging_enabled() -> bool:
	"""T27：默认**关**；显式 ``1/true/on/yes`` 开启。

	toolout 占位的恢复机制未落地前保持默认关——老化即「原文从投影消失
	且无处找回」，与证据先行（T1/T27 spill）方向冲突。
	以 GUI settings.memory 为准（memory_switches.get_value），空/非法残留环境变量忽略。
	"""
	from memory.memory_switches import get_value

	raw = get_value(ENV_KEY).strip().lower()
	if not raw:
		return False
	return raw in ("1", "true", "on", "yes")


def reset_stats() -> None:
	for key in _stats:
		_stats[key] = 0


def stats() -> dict[str, int]:
	return dict(_stats)


def sanitize_summary(text: str, *, limit: int = STUB_SUMMARY_MAX) -> str:
	"""单行化 + 剥标签 + 压空白 + 限长。对任意输入确定性输出（R26）。"""
	t = str(text or "")
	t = t.replace("\r", " ").replace("\n", " ")
	t = _TAG_RE.sub(" ", t)
	t = _WS_RE.sub(" ", t).strip()
	if len(t) > limit:
		t = t[:limit].rstrip() + "…"
	return t


def should_exempt(is_error: bool, tool_name: str) -> bool:
	"""错误结果保真、结构化结果豁免（设计规则表）。"""
	return bool(is_error) or tool_name in EXEMPT_TOOLS


def build_stub(tool_name: str, use_id: str, summary: str, *, folded: bool) -> str:
	"""生成存根文本。folded=True 为远档短形式；两档均确定性、单行。

	总长约 ≤120 字符（≈30 token）：头部13 + id尾8 + 摘要≤60 + 尾部提示。
	"""
	if folded:
		_stats["folds"] += 1
		return f"[elided earlier {tool_name}]"
	uid8 = (use_id or "")[-8:]
	s = sanitize_summary(summary)
	return f"[elided {tool_name} {uid8}: {s}] (archived; answer from remaining context)"


def record_stub(chars_before: int, chars_after: int) -> None:
	_stats["stubbed_blocks"] += 1
	_stats["chars_before"] += chars_before
	_stats["chars_after"] += chars_after
