"""折叠节奏（`synaptic.cadence`）回归：判据单调性 + 生产口径契约。

两条纪律：
1. **判据里不许出现"预测未来"**（2026-09-22 裁定并落地）：旧判据 `R × saved ≥ 30 × margin × transition`
   里的 `R` 是猜的，而实测**剩余寿命不随会话深度衰减**（猜值在深处给 4、真值 49）⇒ 猜错时判据方向整个反。
   现在换成两个只依赖已发生事实的量：`回本枪数 ≤ PAYBACK_SHOTS / margin` 与
   `shots_since_fold ≥ MIN_GAP_SHOTS`。下面的 `test_cadence_carries_no_future_prediction` 是这条的守卫。
   价差倍率仍在算法层内联，由契约测试钉在 `usage/pricing.py` 上（不许 import 生产链）。
2. **判据的单调性要机器锁**——它是「节奏」这个已实测值 2.6 倍成本的主杠杆，
   一旦哪个参数方向反了，报告会给出方向错误的结论而看不出来。
"""

from __future__ import annotations

import inspect
import pathlib

from synaptic.cadence import (
	DEFAULT_MARGIN,
	MIN_GAP_SHOTS,
	PAYBACK_SHOTS,
	PRICE_RATIO_HIT_MISS,
	CadenceState,
	fold_economics,
)


# ---------------------------------------------------------------------------
# 契约：内联口径 == 生产口径
# ---------------------------------------------------------------------------

def test_cadence_carries_no_future_prediction() -> None:
	"""判据里不许再有"还剩几轮"这类预测（用户裁定：引擎猜不到，删）。

	扫的是**代码**不是措辞 —— 模块文档要解释旧版为什么被删，必然提到旧名字。
	"""
	import synaptic.cadence as C

	names = {n for n in dir(C) if not n.startswith("__")}
	for n in list(names):
		assert "remaining" not in n and "residual" not in n, f"cadence 又导出预测量 {n!r}"
	for fn in (fold_economics, CadenceState.decide):
		params = inspect.signature(fn).parameters
		for p in params:
			assert "remaining" not in p and "residual" not in p, f"{fn.__name__} 又收预测参数 {p!r}"
	# 判据的两个常数必须是"已发生的事实 + 价目"，不是对未来的估计
	assert PAYBACK_SHOTS > 0 and MIN_GAP_SHOTS > 0


def test_cooldown_blocks_an_otherwise_profitable_fold() -> None:
	"""刚折过就再折 = 付两次重填、一次都没收回 ⇒ 冷却优先于强度。"""
	d = _dec(region_tokens_=1_000_000, shots_since_fold=MIN_GAP_SHOTS - 1)
	assert not d.fold and d.reason == "cooldown"
	assert _dec(region_tokens_=1_000_000, shots_since_fold=MIN_GAP_SHOTS).fold


def test_state_counts_the_gap_itself() -> None:
	"""冷却量由 `CadenceState` 自己数：调用方不必（也不该）各自维护计数器。"""
	st = CadenceState()
	st.decide(region_tokens_=100, tail_tokens_=10 ** 6, shots_since_fold=None)
	st.decide(region_tokens_=100, tail_tokens_=10 ** 6, shots_since_fold=None)
	assert st.since_fold == 2, "未折叠时冷却计数不推进 ⇒ 永远等不到折叠"
	st2 = CadenceState()
	d = st2.decide(region_tokens_=10 ** 6, tail_tokens_=1_000, shots_since_fold=MIN_GAP_SHOTS)
	assert d.fold and st2.since_fold == 0, "折过之后没归零 ⇒ 下一枪立刻又能折，冷却形同虚设"


def test_price_ratio_loosens_or_tightens_the_gate() -> None:
	"""价目变了判据要自动跟上（这是保留判据而不是删掉它的唯一理由）。"""
	# 命中价相对未命中价越贵（price_ratio 越小）⇒ 越该折
	assert _dec(price_ratio=PRICE_RATIO_HIT_MISS).fold
	assert not _dec(price_ratio=PRICE_RATIO_HIT_MISS * 40).fold


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
		shots_since_fold=MIN_GAP_SHOTS,
		margin=1.0,
	)
	base.update(kw)
	return fold_economics(**base)


def test_decision_is_monotone_in_every_argument():
	# 区域越大越该折
	assert not _dec(region_tokens_=200).fold
	assert _dec(region_tokens_=100_000).fold
	# 等得越久越该折（冷却）
	assert not _dec(shots_since_fold=1).fold
	assert _dec(shots_since_fold=MIN_GAP_SHOTS).fold
	# 过渡代价（尾部）越大越不该折
	assert _dec(tail_tokens_=0).fold
	assert not _dec(tail_tokens_=200_000).fold
	# margin 越大越保守
	assert _dec(margin=0.1).fold
	assert not _dec(margin=50.0).fold


def test_default_margin_sits_in_the_evidence_backed_band():
	"""默认 margin 与两个策略常数必须落在有实测支撑的区间。

	这条断言的作用不是「锁死数值」，而是**挡住无声改动**：默认值换了必须有人来解释。
	"""
	from synaptic.types import WscParams

	assert DEFAULT_MARGIN >= 1.0, (
		"margin < 1 会把门槛压到回本点以下（0.1 ⇒ 允许等 300 枪）。"
		"实测旧 C 档因此每 2~3 枪折一次、三条 transcript 上贵 2.2~2.4 倍。")
	assert PAYBACK_SHOTS >= MIN_GAP_SHOTS, "回本窗口比冷却还短 ⇒ 冷却形同虚设"
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
	base = dict(head_delta_tokens=0, tail_tokens_=1_000, shots_since_fold=MIN_GAP_SHOTS,
	           margin=1.0)
	# 打平条件：price_ratio × transition / saved == PAYBACK_SHOTS / margin
	need = int(PRICE_RATIO_HIT_MISS * 1_000 * 1.0 / PAYBACK_SHOTS)
	d = fold_economics(region_tokens_=need, **base)
	assert d.fold is True, "恰好打平必须折"
	d2 = fold_economics(region_tokens_=need - 1, **base)
	assert d2.fold is False, "差一点就够也必须拒（边界是 ≤）"


def test_payback_constant_buys_exactly_theta_one() -> None:
	"""对外口径只有一句话：**本次净省 ≥ 1 × 本次重发面**。它的机器锁在这里。

	`PAYBACK_SHOTS` 与 `PRICE_RATIO_HIT_MISS` 相等 ⇒ θ=1 ⇒「折叠当枪就不亏，不必相信
	未来任何一枪」。09-22 四份转录重放（θ=0 归一）：θ=1 是 0.41~0.70，θ=0 全是 1.00。
	改这个常数等于改对外承诺，必须同时改 docs §17 与本注释。
	"""
	from synaptic.cadence import theta_required

	assert PAYBACK_SHOTS == PRICE_RATIO_HIT_MISS, "θ 不再是 1 ⇒ 对外口径要重写"
	assert theta_required() == 1.0
	# 净省恰好等于重发面 ⇒ 折；少 1 token ⇒ 拒
	edge = _dec(region_tokens_=2_000, head_delta_tokens=0, tail_tokens_=2_000)
	assert edge.fold is True and edge.reason == "worth_fold"
	assert _dec(region_tokens_=1_999, head_delta_tokens=0, tail_tokens_=2_000).fold is False


def test_production_extend_gate_shares_the_theta_implementation() -> None:
	"""生产链的扩展闸必须**调用**这里的 θ，而不是自己再算一遍代数。

	上次的事故形状：cadence 与 `try_extend_c2` 各写一份等价公式，一边 θ=1、一边有效
	门槛 0.25 倍，报出来的收益说的不是同一件事。守卫扫源码：出现本地乘法式子即红。
	"""
	import memory.runtime as R
	import synaptic.cadence as C

	src = pathlib.Path(R.__file__).read_text(encoding="utf-8").replace("\r\n", "\n")
	body = src.split("def try_extend_c2(", 1)[1].split("\ndef ", 1)[0]
	assert "theta_required(" in body, "扩展闸不再走 cadence 的 θ 单点"
	for forbidden in ("margin * price_ratio", "price_ratio * transition", "remaining_turns *"):
		assert forbidden not in body, f"扩展闸又自己拼判据：{forbidden!r}"
	assert C.theta_required() == 1.0

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
	d_bad = uncapped.decide(region_tokens_=big_region, tail_tokens_=tail,
	                     shots_since_fold=MIN_GAP_SHOTS)
	d_ok = capped.decide(region_tokens_=big_region, tail_tokens_=tail,
	                    shots_since_fold=MIN_GAP_SHOTS)
	assert d_bad.fold is False, "无封顶时这正是那条自锁（留作反例，防回归）"
	assert d_ok.fold is True, "封顶后同一个回合必须折"


def test_implausible_ratio_is_rejected():
	"""比值 > 1 只可能来自「头从无到有 / 整层重写」，不得进追加比估计。"""
	st = CadenceState()
	before = st.observed_ratio
	st.observe(region_tokens_=1_000, head_delta_tokens=5_000)
	assert st.observed_ratio == before


def test_cadence_state_counts_and_reasons():
	"""状态自己数冷却，并给出可审计的 reason —— 三条 reason 都要被走到。"""
	st = CadenceState(observed_ratio=0.05)
	st.decide(region_tokens_=0, tail_tokens_=0)
	assert st.skips == 1 and st.folds == 0 and st.last_reason == "empty_region"

	st.decide(region_tokens_=10 ** 6, tail_tokens_=10)
	assert st.folds == 0 and st.last_reason == "cooldown", "冷却没攒够就折 ⇒ 计数白搭"
	assert st.since_fold == 2

	for _ in range(MIN_GAP_SHOTS - 2):  # 补满冷却
		st.decide(region_tokens_=0, tail_tokens_=0)
	st.decide(region_tokens_=10 ** 6, tail_tokens_=10)
	assert st.folds == 1 and st.last_reason == "worth_fold" and st.since_fold == 0

	st.decide(region_tokens_=10 ** 6, tail_tokens_=10 ** 7)
	assert st.last_reason == "cooldown"
	st.decide(region_tokens_=200, tail_tokens_=10 ** 5, shots_since_fold=MIN_GAP_SHOTS)
	assert st.last_reason == "pays_back_too_slow", "攒不够回本也必须给出可审计的理由"
