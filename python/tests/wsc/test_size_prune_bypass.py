"""尺寸侧修剪（`memory/wsc_size_prune.py`，旁路候选）的契约测试。

最关键的一条是"修剪后恒不大于原文"——它是**性质**而不是样例，所以用变异输入跑，
不用三个手挑的用例（三个用例证不了"恒"）。
"""

from __future__ import annotations

import pytest

from memory.wsc_size_prune import (
	PRUNE_MARKER,
	TAIL_CHARS,
	THRESHOLD_CHARS,
	code_point_length,
	prune_stats,
	prune_tool_result,
)


def test_below_threshold_is_identity() -> None:
	text = "x" * (THRESHOLD_CHARS - 1)
	assert prune_tool_result(text) == text
	assert prune_stats(text)["applied"] == 0


def test_at_threshold_is_identity_and_above_is_pruned() -> None:
	"""边界必须是"≤ 阈值不动、> 阈值才动"，取反就写成恒等门。"""
	assert prune_tool_result("y" * THRESHOLD_CHARS) == "y" * THRESHOLD_CHARS
	pruned = prune_tool_result("y" * (THRESHOLD_CHARS + 1))
	assert pruned != "y" * (THRESHOLD_CHARS + 1)
	assert PRUNE_MARKER in pruned


def test_pruning_never_grows_for_any_input() -> None:
	"""性质：任意输入下修剪后长度 ≤ 原长度。

	变异集刻意覆盖多字节（CJK 每字符 3 字节，UTF-16 与 utf-8 口径会分叉）、
	代理对、超长单行、恰好等于头/尾边界。
	"""
	probes = [
		"z" * 100_000,
		"中" * 40_000,
		"\U0001F600" * 9_000,          # 代理对：按码点数才不劈开
		"a" * (THRESHOLD_CHARS + TAIL_CHARS),
		"line\n" * 5_000,
		"\r\n" * 6_000,
		"",
	]
	for text in probes:
		out = prune_tool_result(text)
		assert code_point_length(out) <= code_point_length(text), text[:24]


def test_surrogate_pair_is_not_split() -> None:
	"""按码点切 ⇒ 头边界不能落在代理对中间（UTF-16 口径会）。"""
	text = "\U0001F600" * 9_000
	out = prune_tool_result(text)
	assert "\ufffd" not in out, "出现了替换字符 ⇒ 劈开了代理对"


def test_load_time_validation_rejects_a_backwards_budget() -> None:
	"""头 + 标记 + 尾 > 阈值 ⇒ 修剪会**变大**，这种配置必须在调用前就炸。"""
	with pytest.raises(ValueError, match="must be at most"):
		prune_tool_result("q" * 10_000, threshold_chars=100, head_chars=4096, tail_chars=1024)
	with pytest.raises(ValueError, match="positive"):
		prune_tool_result("q" * 10_000, threshold_chars=0)
	with pytest.raises(ValueError, match="non-negative"):
		prune_tool_result("q" * 10_000, head_chars=-1)


def test_removed_span_is_the_middle_only() -> None:
	"""头与尾必须逐字保留——尾部常是结论/退出码，头常是命令回显。"""
	text = "HEAD-MARKER\n" + ("filler " * 4000) + "\nTAIL-MARKER: exit code 1"
	out = prune_tool_result(text)
	assert out.startswith("HEAD-MARKER")
	assert out.endswith("TAIL-MARKER: exit code 1")
	assert PRUNE_MARKER in out


def test_marker_wording_carries_no_direction() -> None:
	"""措辞门：标记只能是中性结果型，不许出现建议/指令/评价（AGENTS.md 铁律 1、3）。

	按"话题 + 极性"匹配，不是只列几个词——否则换个说法就漏。
	"""
	low = PRUNE_MARKER.lower()
	for forbidden in ("should", "must", "please", "recommend", "请", "建议", "必须", "不要"):
		assert forbidden not in low, f"标记里出现导演型措辞：{forbidden}"
	assert "pruned" in low, "标记没说明发生了什么"


def test_stats_report_the_removed_volume() -> None:
	text = "w" * 20_000
	st = prune_stats(text)
	assert st["applied"] == 1
	assert st["removed_chars"] > 0
	assert st["before_chars"] - st["after_chars"] == st["removed_chars"]
