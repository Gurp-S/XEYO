"""折叠节奏（`synaptic.cadence`）回归：判据单调性 + 生产口径契约。

两条纪律：
1. **零生产依赖，但口径必须同源**——剩余轮次启发式与价差倍率都在算法层**内联**实现
   （`tests/wsc/test_isolation.py` 静态执法算法层不许 import 生产链），
   所以必须有**契约测试**把它们钉在生产链的真值上（同 `node_token_len` 的做法）。
2. **判据的单调性要机器锁**——它是「节奏」这个已实测值 2.6 倍成本的主杠杆，
   一旦哪个参数方向反了，报告会给出方向错误的结论而看不出来。
"""

from __future__ import annotations

from synaptic.cadence import (
	DEFAULT_MARGIN,
	PRICE_RATIO_HIT_MISS,
	CadenceState,
	estimate_remaining,
	fold_economics,
)


# ---------------------------------------------------------------------------
# 契约：内联口径 == 生产口径
# ---------------------------------------------------------------------------

def test_remaining_estimator_matches_production_caliber():
	"""剩余轮次启发式必须与 `memory/simulator/replay.py` 逐值一致。"""
	from memory.simulator.replay import estimate_remaining as prod

	def user(text: str) -> dict:
		return {"role": "user", "content": text}

	def tool(text: str) -> dict:
		return {"role": "user", "content": [{"type": "tool_result", "content": text}]}

	for n_user in (1, 4, 8, 16, 32, 64, 200):
		msgs = [user(f"q{i}") for i in range(n_user)]
		assert estimate_remaining(msgs) == prod(msgs), f"n_user={n_user} 口径漂移"
	# 收尾语
	for word in ("就这样", "谢谢", "够了", "可以了", "结束"):
		msgs = [user("q0"), user(f"{word}吧")]
		assert estimate_remaining(msgs) == 1 == prod(msgs), f"{word} 未被识别为收尾"
	# tool_result 不算用户轮次
	mixed = [user("q0"), tool("x" * 100), user("q1")]
	assert estimate_remaining(mixed) == prod(mixed)


def test_price_ratio_matches_production_pricing():
	"""价差倍率（未命中/命中）必须等于 `usage/pricing.py` 的深寻 flash 空闲档。"""
	from memory.simulator.cache_model import CacheState, prices_for
	from memory.simulator.params import load_params

	p = load_params()
	prices = prices_for(CacheState(provider=p.provider, model=p.model, slot=p.price_slot), p)
	ratio = float(prices.p_u) / float(prices.p_r)
	assert abs(ratio - PRICE_RATIO_HIT_MISS) < 1e-9, f"价差倍率漂移: {ratio}"


# ---------------------------------------------------------------------------
# 判据单调性（每个参数一个方向）
# ---------------------------------------------------------------------------

def _dec(**kw):
	# ⚠️ 单调性断言必须**显式给 margin**：默认 margin 是策略旋钮（第十轮 0.25 →
	# 第十二轮 0.1），拿默认值当基线会让「默认一改测试就红」——而它红的原因不是
	# 判据坏了，是断言把策略固化进了测试。
	base = dict(
		region_tokens_=10_000,
		head_delta_tokens=1_000,
		tail_tokens_=1_000,
		remaining_turns=16,
		margin=1.0,
	)
	base.update(kw)
	return fold_economics(**base)


def test_decision_is_monotone_in_every_argument():
	# 区域越大越该折
	assert not _dec(region_tokens_=200).fold
	assert _dec(region_tokens_=100_000).fold
	# 剩余轮次越多越该折（margin=1.0 下 16 轮够、1 轮不够）
	assert not _dec(remaining_turns=1).fold
	assert _dec(remaining_turns=24).fold
	# 过渡代价（尾部）越大越不该折
	assert _dec(tail_tokens_=0).fold
	assert not _dec(tail_tokens_=200_000).fold
	# margin 越大越保守
	assert _dec(margin=0.1).fold
	assert not _dec(margin=50.0).fold


def test_default_margin_sits_in_the_evidence_backed_band():
	"""默认 margin 必须落在有实测支撑的区间（第十二轮：长会话子集 0.1–0.5 单调偏好小值）。

	这条断言的作用不是「锁死数值」，而是**挡住无声改动**：默认值换了必须有人来解释。
	"""
	from synaptic.types import WscParams

	assert 0.0 < DEFAULT_MARGIN <= 0.5, "默认 margin 超出实测支撑区间"
	assert WscParams().fold_margin == DEFAULT_MARGIN, "types 与 cadence 的默认值必须一致"


def test_saved_is_net_of_head_growth():
	"""`saved` 必须是**净**减少量（区域 − 头增量），不是区域本身。"""
	d = _dec(region_tokens_=5_000, head_delta_tokens=2_000)
	assert d.saved == 3_000
	assert d.transition == 3_000  # head_delta + tail


def test_empty_region_never_folds():
	d = _dec(region_tokens_=0)
	assert not d.fold
	assert d.reason == "empty_region"


def test_boundary_is_inclusive():
	"""边界取「≥」：恰好打平时折（否则 U 形的最优点会被判据自身挪走）。"""
	base = dict(head_delta_tokens=0, tail_tokens_=1_000, remaining_turns=10, margin=1.0)
	# 打平条件：R × saved == price_ratio × margin × transition（transition = 尾部 1000）
	need = int(PRICE_RATIO_HIT_MISS * 1.0 * 1_000 / 10)
	d = fold_economics(region_tokens_=need, **base)
	assert d.fold is True, "恰好打平必须折"
	assert d.lhs == d.rhs
	d2 = fold_economics(region_tokens_=need - 1, **base)
	assert d2.fold is False


# ---------------------------------------------------------------------------
# 自我校准
# ---------------------------------------------------------------------------

def test_cadence_state_learns_compression_ratio():
	st = CadenceState()
	first = st.estimate_head_delta(10_000)
	st.observe_fold(region_tokens_=10_000, head_delta_tokens=500, carried_over=True)  # 实测 5%
	second = st.estimate_head_delta(10_000)
	assert second < first, "实测比先验更省时，估计必须下调（否则会永久拒绝折叠）"
	assert 0 < second < first
	st.observe(region_tokens_=0, head_delta_tokens=999)  # 空区域不得污染
	assert st.estimate_head_delta(10_000) == second


def test_first_fold_must_not_poison_the_append_ratio():
	"""首折 / 重冻结（头从无到有或整层重写）**绝不能**喂进追加比估计。

	这是实测踩过的坑：首折的 `head_delta` = 整个新头（可能比区域还大），
	喂进去把 `observed_ratio` 抬到 1.0 量级 ⇒ `saved = region − head_delta ≈ 0`
	且 `transition ≈ region + tail` ⇒ **判据此后永久拒绝折叠**。
	官方 harness 上的代价：长会话折叠数 41 → 14、全语料 ΣL 6.7M → 21.8M。
	"""
	st = CadenceState()
	before = st.observed_ratio
	st.observe_fold(region_tokens_=6_000, head_delta_tokens=3_800, carried_over=False)
	assert st.observed_ratio == before, "首折不得改变追加比估计"
	# 反向断言（防断言空洞）：同样的数字在 carried_over=True 时必须被采纳
	st.observe_fold(region_tokens_=6_000, head_delta_tokens=3_800, carried_over=True)
	assert st.observed_ratio > before


def test_head_delta_estimate_is_capped_by_structure():
	"""头增量估计必须封顶在「紧凑渲染预算 + 重冻结阈值」——否则会自锁成死亡螺旋。

	实测（200 回合会话）：比值爬到 0.69 后 `headΔ_est = 0.69 × 区域`，
	`transition` 随之膨胀 ⇒ 判据**永久拒绝折叠** ⇒ 尾部涨到 20 万 token。
	封顶后有结构依据：头不可能因为区域大而无限大（超阈值就重冻结）。
	"""
	cap = 9_000
	st = CadenceState(observed_ratio=0.7, head_delta_cap=cap)
	assert st.estimate_head_delta(10_000) == 7_000, "未触顶时必须照实用估计"
	assert st.estimate_head_delta(1_000_000) == cap, "大区域必须被封顶"

	# 死亡螺旋场景：不封顶 ⇒ 拒折；封顶 ⇒ 折。
	big_region, tail = 109_857, 2_758
	uncapped = CadenceState(observed_ratio=0.69)
	capped = CadenceState(observed_ratio=0.69, head_delta_cap=cap)
	d_bad = uncapped.decide(region_tokens_=big_region, tail_tokens_=tail, remaining_turns=4)
	d_ok = capped.decide(region_tokens_=big_region, tail_tokens_=tail, remaining_turns=4)
	assert d_bad.fold is False, "无封顶时这正是那条自锁（留作反例，防回归）"
	assert d_ok.fold is True, "封顶后同一个回合必须折"


def test_implausible_ratio_is_rejected():
	"""比值 > 1 只可能来自「头从无到有 / 整层重写」，不得进追加比估计。"""
	st = CadenceState()
	before = st.observed_ratio
	st.observe(region_tokens_=1_000, head_delta_tokens=5_000)
	assert st.observed_ratio == before


def test_cadence_state_counts_and_reasons():
	st = CadenceState()
	st.decide(region_tokens_=0, tail_tokens_=0, remaining_turns=16)
	assert st.skips == 1 and st.folds == 0 and st.last_reason == "empty_region"
	st.decide(region_tokens_=10**6, tail_tokens_=10, remaining_turns=16)
	assert st.folds == 1 and st.last_reason == "worth_fold"
