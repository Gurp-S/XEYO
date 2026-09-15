"""报告口径测试：分子分母必须同源，且冷启动不能被当成稳态。

这个文件存在的理由是两个**已踩过**的坑：

1. `hot_share_of_base` 曾写成 ``zip(compressed_turns, base)`` —— 左边是过滤后的子集、
   右边是未过滤的全量列表，只要有一个回合被收益门跳过，后面每一对都错行，报出
   物理上不可能的值（实测 198.9，而 热层 ≤ 区域基线 ≤ 整段基线 ⇒ 该比值必然 < 1）。
2. 每个会话的首个可比回合没有「上一轮投影」，命中必然为 0。本语料 235 会话 / 651 回合
   ⇒ 首回合约占 1/3，`hit_rate_wsc` 的中位数被压成 0，均值不具解释力。
   故必须额外出「跳首回合」的 steady 口径，且**不能**把原口径删掉（原口径才是含冷启动的真实平均）。
"""

from __future__ import annotations

from synaptic.replay import TurnRecord
from synaptic.report import Aggregate


def _turn(
	session: str,
	turn: int,
	*,
	hot: int,
	base: int,
	wsc: int | None = None,
	wsc_hit: float = 0.0,
	v61_hit: float = 0.0,
	skipped: bool = False,
	baseline_missing: bool = False,
) -> TurnRecord:
	"""造一条最小可用的 TurnRecord（其余字段取不会干扰断言的值）。"""
	return TurnRecord(
		session=session,
		turn=turn,
		mode="closure",
		level="Medium+",
		region_end=100,
		n_messages=120,
		base_tokens=base,
		v61_tokens=base,
		wsc_tokens=wsc if wsc is not None else base,
		v61_cost=1.0,
		v61_hit=v61_hit,
		wsc_cost=1.0,
		wsc_hit=wsc_hit,
		hot_tokens=hot,
		tail_tokens=0,
		kept=1,
		pruned=0,
		cards=0,
		rebuilt=False,
		lcp_prev=0,
		latency_ms=1.0,
		gain_gate_skipped=skipped,
		baseline_missing=baseline_missing,
	)


def test_hot_share_pairs_within_turn_not_by_position():
	"""收益门跳过一个回合后，hot_share 不得错行对到别的回合的 base。"""
	turns = [
		# 被收益门跳过：hot 极小、base 极小
		_turn("s1", 0, hot=1, base=1_000, skipped=True),
		# 正常回合：hot = 5000 / base = 10000 ⇒ 真实比值 0.5
		_turn("s1", 1, hot=5_000, base=10_000),
		_turn("s1", 2, hot=5_000, base=10_000),
		_turn("s1", 3, hot=5_000, base=10_000),
	]
	rep = Aggregate(label="t", level="Medium+", mode="closure", turns=turns).summary()
	share = rep["hot_share_of_base"]
	# 错行写法会把 t1 的 5000 对到 t0 的 base=1000 ⇒ 5.0
	assert share["max"] == 0.5, f"hot_share 错行：max={share['max']}"
	assert share["n"] == 3.0


def test_hot_share_never_exceeds_one_when_gate_respected():
	"""热层 ≤ 区域基线 ≤ 整段基线 ⇒ 该比值在合法输入下必然 < 1。"""
	turns = [
		_turn("s1", 0, hot=10, base=1_000, skipped=True),
		_turn("s1", 1, hot=999, base=1_000),
		_turn("s1", 2, hot=1, base=1_000),
	]
	share = Aggregate(label="t", level="Medium+", mode="closure", turns=turns).summary()[
		"hot_share_of_base"
	]
	assert share["max"] <= 1.0, f"越界值 {share['max']} 说明分子分母不同源"


def test_steady_variant_drops_first_turn_of_each_session():
	"""steady 口径必须排除每个会话的首个可比回合，且原口径保留。"""
	turns = [
		_turn("s1", 0, hot=1, base=1_000, wsc_hit=0.0),  # 冷启动 → 应被 steady 排除
		_turn("s1", 1, hot=1, base=1_000, wsc_hit=0.6),
		_turn("s1", 2, hot=1, base=1_000, wsc_hit=0.8),
		_turn("s2", 0, hot=1, base=1_000, wsc_hit=0.0),  # 冷启动 → 排除
		_turn("s2", 1, hot=1, base=1_000, wsc_hit=0.4),
		_turn("s2", 2, hot=1, base=1_000, wsc_hit=0.2),
	]
	rep = Aggregate(label="t", level="Medium+", mode="closure", turns=turns).summary()

	assert rep["compared_turns"] == 6
	assert rep["steady_turns"] == 4, "steady 应只剩 2 会话 × 2 回合"
	# 原口径（含冷启动）均值 = (0+0.6+0.8+0+0.4+0.2)/6 = 1/3
	assert abs(rep["hit_rate_wsc"]["mean"] - (2.0 / 6.0)) < 1e-9
	# steady 均值 = (0.6+0.8+0.4+0.2)/4 = 0.5
	assert abs(rep["hit_rate_wsc_steady"]["mean"] - 0.5) < 1e-9
	# 原口径不许被删——它是「含冷启动的真实平均」
	assert rep["hit_rate_wsc"]["n"] == 6.0


def test_steady_ignores_turn_order_of_input():
	"""steady 认的是 turn 序号，不是列表位置（回放可能乱序或跳号）。"""
	turns = [
		_turn("s1", 5, hot=1, base=1_000, wsc_hit=0.9),
		_turn("s1", 2, hot=1, base=1_000, wsc_hit=0.0),  # 最小 turn → 首回合
		_turn("s1", 9, hot=1, base=1_000, wsc_hit=0.9),
	]
	rep = Aggregate(label="t", level="Medium+", mode="closure", turns=turns).summary()
	assert rep["steady_turns"] == 2
	assert abs(rep["hit_rate_wsc_steady"]["mean"] - 0.9) < 1e-9


def test_user_requests_coverage_is_reported():
	"""节点级用户原话覆盖率必须进报告（防「用信息留存换命中率」）。"""
	turns = [
		_turn("s1", 0, hot=1, base=1_000),
		_turn("s1", 1, hot=1, base=1_000),
	]
	turns[0].req_total = 4
	turns[0].req_rendered = 4
	turns[1].req_total = 6
	turns[1].req_rendered = 3
	rep = Aggregate(label="t", level="Medium+", mode="closure", turns=turns).summary()
	ur = rep["user_requests"]
	assert ur["total"] == 10
	assert ur["rendered"] == 7
	assert abs(ur["coverage"] - 0.7) < 1e-9
