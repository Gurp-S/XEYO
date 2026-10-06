"""折叠节奏（cadence）：**什么时候值得把尾部折进头**。

## 为什么它必须在算法层

第八轮之前，「何时折叠」这件事在生产里由**水位**决定（`prompt ≥ 0.8 × context_limit`），
在评测台里由 `trigger_ratio` 复现。但实测（docs §15.9.2，同语料 736 回合）：

| 折叠判据 | cost ratio WSC/C2 |
|---|---:|
| 生产水位 0.8×131072 | 1.0128（打平） |
| 每回合都折 | 1.0546 |
| **成本驱动（本模块，margin 0.25）** | **0.9363** |

即**节奏比头值钱**：生产水位到成本最优之间差 **2.6 倍**总成本，而「WSC 头 vs C2 头」
只差 6%。所以这个判据不能只活在评测台的探针里——引擎必须能直接调用它。

## 经济学（一行公式，先写清口径再写代码）

- **不折叠**：被折叠区继续留在上下文里，每枪按**命中价**计费 ⇒ 每枪省 `saved × p_hit`；
- **折叠**：本枪付一次**未命中价** `transition × p_miss`（前缀在头的追加点之后整段失效）；
- 设还剩 `R` 枪，旧判据是 `R × saved × p_hit ≥ margin × transition × p_miss`。**这个 `R` 已删**
  （生产传进来的是"本轮预算剩余轮数"，不是"还会重用前缀几枪"⇒ 门槛随预算档位漂）。

移项后本模块的判据形式（`theta_required()`，生产链同一份实现）：

```
本次净省 saved ≥ θ × 本次重发面 transition，  θ = price_ratio × margin / PAYBACK_SHOTS
price_ratio = p_miss / p_hit = 1.5 / 0.05 = 30（usage/pricing.py，deepseek-v4-flash 空闲档）
```

默认 `θ = 30 × 1 / 30 = 1.0` ⇒ 估计回本周期不超过 30 次后续请求。
它不保证折叠当次便宜。`margin > 1` 缩短允许的回本周期。

### 三项量怎么取（都是 O(1)，不需要渲染）

- `region_tokens`：**将离开上下文的那一段**的 token（区域 = 上次折叠边界到本次切点）；
- `head_delta_tokens`：折叠给头增加的量。**不许猜**——用本会话**上一次折叠实测到的
  压缩比**外推（`CadenceState.observed_ratio`），首折用保守默认
  `DEFAULT_HEAD_RATIO`。这是本模块唯一的经验项，且它自我校准。
- `tail_tokens`：折叠后仍逐字保留的尾部（= 折叠当轮 miss 的另一半）。

## 与生产 `try_extend_c2` 的关系（同一个实现，不是"等价公式"）

`memory/runtime.py::try_extend_c2` 的经济闸**调用** `theta_required()`，不自己拼代数。
历史事故：两处各写一份"等价"公式——生产那边把 `price_ratio` 乘在 transition 上、再乘
`margin=2`，却除以一个来自会话预算的 `remaining_turns`，于是有效门槛 = `60 / remaining`
在生产（`r_cap=96` ⇒ 0.625 倍）与评测台（remaining=8 ⇒ 7.5 倍）之间漂 12 倍，
报出来的收益说的不是同一件事。
守卫：`tests/wsc/test_cadence.py::test_production_extend_gate_shares_the_theta_implementation`。

## 零生产依赖

与 `textutil.node_token_len` 同策：需要生产链的**口径**（剩余轮次启发式、价目）
就在本层**内联实现 + 契约测试**比对，绝不 import（`tests/wsc/test_isolation.py`
静态执法算法层零生产依赖）。
"""

from __future__ import annotations

import math
import os as _os
from dataclasses import dataclass
from typing import Any

from synaptic.textutil import node_token_len

#: 未命中价 / 命中价。deepseek-v4-flash 空闲档 1.5 / 0.05 = 30（高峰档同为 30）。
#: 契约测试 `test_cadence.py::test_price_ratio_matches_production_pricing` 比对
#: `usage/pricing.prices_for`，防止价目改了而这里没跟。
PRICE_RATIO_HIT_MISS = 30.0

#: 判据的两个**策略常数**（不是预测：都只依赖"已经发生的事实"和"价目"）。
#:
#: `PAYBACK_SHOTS` —— 最多等几枪回本。一次折叠的重填代价 `price_ratio × transition`
#: （未命中价），之后每枪省 `saved`（命中价）⇒ 回本枪数 = `price_ratio × transition / saved`，
#: 要求它 ≤ 本常数。**30 = price_ratio ⇒ θ=1 ⇒「本次净省 ≥ 本次重发面」**，也就是
#: `margin=1` 时允许最多 30 次后续请求回本，不是当次盈亏平衡。
#:
#: 取值依据（09-22 `_wsc_out/_b_plan.py`，四份转录重放，总成本 ÷ 同转录 θ=0）：
#:
#: | θ | TB attempt2 | TB attempt1 | GUI qawa1w | GUI tgbg36 |
#: |---|---:|---:|---:|---:|
#: | 0（攒一点就折）| 1.00 | 1.00 | 1.00 | 1.00 |
#: | 0.5 | 0.63 | 0.57 | 0.59 | 0.45 |
#: | **1（本常数）** | **0.59** | 0.61 | 0.70 | **0.41** |
#: | 2 | 0.66 | 0.54 | 0.61 | 0.43 |
#: | 4（合并折叠）| 0.72 | 0.78 | 0.75 | 0.46 |
#: | 无判据·每 8 枪 | 0.65 | 0.56 | 0.69 | 0.55 |
#:
#: θ=0 四份全最差 ⇒ 旧「攒一点就折」是纯亏；θ 再往上（2/4）不再省钱，且末枪 prompt 随
#: 推迟上涨（θ=4 在 attempt1 把末枪推到 52,883 ≈ 64k 档水位 52,428）⇒ 取 θ=1：它在
#: attempt2 / tgbg36 上就是最优，在 attempt1 / qawa1w 上比各自次优贵 13% / 18%，
#: 该档位的结构含义是允许的估计回本周期不超过 30 次后续请求。
#: （装上生产判据后重放 `_b_plan_live.py`：0.57 / 0.54 / 0.63 / 0.46，另加尺寸两道闸。）
#:
#: ⚠️ 旧值 8 的含义是「只允许深折」，不是「折叠通常 8 枪回本」：影子账本单次移出比例
#: r 中位 89.8% ⇒ 3.4 枪，但活路径被折区只占发射面的 15~65%，实测回本需求 **12~238 枪**
#: ⇒ 8 在 43 次判定里放行 0 次。折叠当枪的重填面实测 **71.1%**（n=38），平枪 4%。
PAYBACK_SHOTS = 30
#: `MIN_GAP_SHOTS` —— 距上次折叠至少几枪。低于回本周期的连续折叠是纯亏（付两次重填、
#: 一次都还没收回）。旧实现靠"猜还剩几轮"表达这件事，猜错了方向就反（见 §22/§25）。
MIN_GAP_SHOTS = 4
#: 保守边际。**09-22 从 0.1 钉到 1.0**：0.1 把有效门槛压到 3 倍，而实测回本点是
#: 30~40 倍（`price_ratio` × transition/saved）——低了一个数量级，所以旧 C 档
#: 每 2~3 枪折一次、三条 transcript 上实测贵 2.2~2.4 倍。
DEFAULT_MARGIN = 1.0

#: `MAX_GAP_SHOTS` —— 冷却的**结构上界**。不是第三个策略常数，是判据自身的不动点：
#: 任何通过 θ 门的折叠都满足 `saved ≥ θ·transition`，θ = `price_ratio·margin/PAYBACK_SHOTS`
#: ⇒ `回本枪数 = price_ratio·transition/saved ≤ PAYBACK_SHOTS/margin ≤ PAYBACK_SHOTS`。
#: 所以实测回本枪数**结构上不可能超过本常数**：封顶在这里不是"再拍一个数"，而是
#: "取判据自己允许的最长回本周期"。env `XEYO_C2_GAP_CAP` 可覆盖（标定用）。
MAX_GAP_SHOTS = PAYBACK_SHOTS

#: `CadenceState.gap_cap_shots` 的**出厂默认** = 结构上界（判据不动点）。
#:
#: 出厂值取 `MAX_GAP_SHOTS` 而不是某个更小的"调参档"，理由是冷却这条规则本身：
#: **折叠后要 N 枪回本 ⇒ 接下来至少 N 枪不得再折**。实测回本枪数在 `[4, 30]` 之间
#: 变动，任何小于 30 的 cap 都会把 `16 < N ≤ 30` 那批折叠的冷却截短到 cap
#: ⇒ 那批折叠的第二次折叠发生在它自己回本之前，规则被破坏。所以 cap 的同义物
#: 只能是判据的上界，不能是策略档位。
#:
#: 更小的 cap 是**可选标定档**（env `XEYO_C2_GAP_CAP`），代价/收益已离线量过：
#: 4 份真实转录 × 8 档 (4/6/8/10/12/16/20/30)，走生产代码路径（`_wsc_out/_cd_sweep_result_r*.jsonl`）：
#:   · cap=4：纯美元最优，但 4 会话合计折 60 次、冷层引用保留 `id_ret` 最低 0.215；
#:   · cap=16：成本 +1.05%（合计 +$0.078）、折叠 −33.3%（60→40）、`id_ret` +24%
#:     —— 但它是"拿规则换钱"：截短了 16~30 枪那一档；
#:   · cap=30（=出厂值）：成本 +4.61%，相对 16 只再 −6 次折叠 ⇒ 边际递减。
#: 即：省下的钱与折叠次数都来自同一处——让一部分折叠不被等到回本。用户已明确
#: 该规则优先（"折叠之后需要 N 枪回本，接下来至少 N 枪不能折"），故出厂 30。
DEFAULT_GAP_CAP_SHOTS = MAX_GAP_SHOTS


def effective_gap_cap(field_value: int = 0) -> int:
	"""冷却上界：字段 > env `XEYO_C2_GAP_CAP` > `DEFAULT_GAP_CAP_SHOTS`（出厂默认）。

	fail-open：任何解析失败（空/非数/负）都退回缺省，**绝不因为标定参数写错而放大折叠**。

	这是 `CadenceState.effective_gap_cap()` 与生产链（`memory.runtime.try_extend_c2`，
	只拿得到 working 快照、拿不到 CadenceState）**共用**的一份实现：两处各写一份优先级
	就是"同一个数在两处含义不同"那类事故的种子。
	"""
	try:
		cap = int(field_value)
	except (TypeError, ValueError):
		cap = 0
	if cap <= 0:
		raw = _os.environ.get("XEYO_C2_GAP_CAP", "").strip()
		if raw:
			try:
				cap = int(float(raw))
			except (TypeError, ValueError):
				cap = 0
	if cap <= 0:
		cap = DEFAULT_GAP_CAP_SHOTS
	return max(MIN_GAP_SHOTS, cap)


def gap_from_payback(
	payback_shots: float,
	*,
	floor: int = MIN_GAP_SHOTS,
	cap: int = DEFAULT_GAP_CAP_SHOTS,
) -> int:
	"""冷却枪数 = 上一次折叠的**实测回本枪数**（上取整），夹在 `[floor, cap]`。

	`floor` 恒为 `MIN_GAP_SHOTS` ⇒ 这个改动是**单向的**：任何路径的冷却都不可能比
	旧行为的 4 枪更短，只可能更长（折得更少）。所以它不需要"收益证明"来兜底——
	它只会收紧。

	fail-open 方向：拿不到可信实测（NaN / inf / 净省 ≤ 0）⇒ 取 `cap`（最保守），
	**绝不取 0**——"没有证据"必须是少折，不能是随便折。
	"""
	f = max(1, int(floor))
	c = max(f, int(cap))
	p = float(payback_shots)
	if math.isnan(p) or math.isinf(p):
		return c
	if p <= 0.0:
		# 「净省 ≤ 0」= 这次折叠没换到任何回本证据 ⇒ 按无证据处理，取 cap（少折）。
		# 上面那句 docstring 与 `test_gap_from_payback_never_guesses_zero` 都要求这个方向。
		return c
	return int(min(c, max(f, math.ceil(p))))


#: 首折前对「头增量 / 区域」的保守估计（无观测时的先验）。
#: 偏大 = 更保守（更不容易折）。实测 Medium+ 长会话的头增量约为区域的 0.10–0.20。
DEFAULT_HEAD_RATIO = 0.20


def theta_required(*, margin: float = DEFAULT_MARGIN,
                   price_ratio: float = PRICE_RATIO_HIT_MISS) -> float:
	"""本判据等价于一句话：**本次净省 ≥ θ × 本次重发面**，θ 由这里给。

	`回本枪数 ≤ PAYBACK_SHOTS / margin` 两边同乘 `saved / PAYBACK_SHOTS` 移项即得
	`θ = price_ratio × margin / PAYBACK_SHOTS`。默认 `30 × 1 / 30 = 1.0`。

	生产链（`memory.runtime.try_extend_c2` 的经济闸）**必须**走这里取阈值，不要在别处
	重算——两处各写一份代数，就是上次「θ=1 vs 60/remaining（0.625~7.5 倍）」那个分歧的来源。
	"""
	return float(price_ratio) * max(0.0, float(margin)) / float(PAYBACK_SHOTS)


#: 目标：长对话稳态命中率（给定值，非估计）。
TARGET_HIT_RATE = 0.99

#: 折叠水位：下一枪投影 prompt 低于「窗口 × 该比例」时不折（保底压缩）。
FOLD_WATERMARK_RATIO = 0.5


def watermark_tokens(window_tokens: int,
                     ratio: float = FOLD_WATERMARK_RATIO) -> int:
	"""折叠水位（token 数）：不到这条线不折。"""
	return int(max(0, int(window_tokens)) * max(0.0, float(ratio)))


def fold_gap_required(payback_shots: float,
                      transition: int,
                      prompt_tokens: int,
                      target_hit_rate: float = TARGET_HIT_RATE) -> int:
	"""折叠后至少等多少枪才允许再折：`max(回本枪数, 命中率约束枪数)`。

	命中率约束的来历：折叠每 `gap` 枪往上下文里注入 `transition` 个未命中 token，
	而这段时间读过的 prompt 总量约 `gap × prompt_tokens`，于是
	`transition / (gap × prompt) ≤ 1 - target_hit_rate` 移项即得
	`gap ≥ transition / ((1 - target_hit_rate) × prompt)`。
	两个约束都取上取整，取较严的一侧；prompt 越小越由命中率项主导。
	"""
	pb = int(math.ceil(max(0.0, float(payback_shots))))
	allow = max(1e-6, 1.0 - float(target_hit_rate))
	p = max(1, int(prompt_tokens))
	hit_term = int(math.ceil(max(0, int(transition)) / (allow * p)))
	return max(1, pb, hit_term)


def payback_from_economics(price_ratio: float, transition: float, saved: float) -> float:
	"""`回本枪数 = price_ratio × transition ÷ saved`（`saved ≤ 0` ⇒ `inf`）。

	这是**唯一**一份回本代数。两处都只认它：

	1. `fold_economics` 填 `FoldDecision.payback_shots`（判据自己算的账）；
	2. `memory.runtime.try_extend_c2` 算"这次折叠落地后要几枪回本"——它就是折叠后
	   冷却枪数的来源（`gap_from_payback`）。

	为什么必须同源：两处各写一份等价式子，改动只落一处时就会静默分叉（旧事故：
	判据 θ=1、活路径 `60/remaining`，实际门槛差 0.625~7.5 倍）。守卫测试
	`tests/wsc/test_cadence.py::test_production_extend_gate_shares_the_theta_implementation`
	会扫 `try_extend_c2` 源码里是否又长出第二份代数。
	"""
	try:
		s = float(saved)
	except (TypeError, ValueError):
		return float("inf")
	if s <= 0.0:
		return float("inf")
	return float(price_ratio) * float(transition) / s


def region_tokens(texts: list[str]) -> int:
	"""一段将要离开上下文的区域的 token 数（`node_token_len` 口径）。"""
	return sum(node_token_len(t) for t in texts if t)


@dataclass(frozen=True)
class FoldDecision:
	"""一次折叠判定的完整账目（可落报告，便于审计与回归）。"""

	fold: bool
	saved: int
	head_delta: int
	tail_tokens: int
	shots_since_fold: int
	margin: float
	price_ratio: float
	reason: str
	payback_shots: float = 0.0

	@property
	def transition(self) -> int:
		"""折叠当轮的一次性 miss ≈ 头新增 + 仍逐字保留的尾部。"""
		return self.head_delta + self.tail_tokens

	@property
	def gate(self) -> float:
		"""本枪允许的最大回本枪数（`PAYBACK_SHOTS / margin`）。"""
		return PAYBACK_SHOTS / max(0.01, self.margin)

	def as_dict(self) -> dict[str, Any]:
		return {
			"fold": self.fold,
			"region_saved": self.saved,
			"head_delta": self.head_delta,
			"tail_tokens": self.tail_tokens,
			"transition": self.transition,
			"shots_since_fold": self.shots_since_fold,
			"payback_shots": round(self.payback_shots, 2),
			"gate_shots": round(self.gate, 2),
			"margin": self.margin,
			"price_ratio": self.price_ratio,
			"reason": self.reason,
		}


def fold_economics(
	*,
	region_tokens_: int,
	head_delta_tokens: int,
	tail_tokens_: int,
	shots_since_fold: int,
	margin: float = DEFAULT_MARGIN,
	price_ratio: float = PRICE_RATIO_HIT_MISS,
	min_gap_shots: int = MIN_GAP_SHOTS,
) -> FoldDecision:
	"""纯函数判据（**不含任何预测**）：

	```
	回本枪数 = price_ratio × transition / saved
	折  ⟺  回本枪数 ≤ PAYBACK_SHOTS / margin   且   shots_since_fold ≥ min_gap_shots
	```

	第二条闸等价于 `saved ≥ theta_required(...) × transition`，即「本次净省 ≥ θ × 本次
	重发面」。`margin` 是**保守边际**（>1 更保守）：0.1 ⇒ 允许等 300 枪，1.0 ⇒ 30 枪
	（= θ=1，允许 30 枪回本），10 ⇒ 3 枪。两个量都是**已发生的事实**
	（尾巴攒了几枪、这次能移出多少）加一个价目常数——旧版的 `remaining_turns` 是猜的，
	猜错方向时判据整体反向（§22 实测：剩余寿命不随会话深度衰减，旧式却越猜越小）。

	`min_gap_shots` 默认 `MIN_GAP_SHOTS`（= 4，与旧行为逐字一致）；生产链传
	`gap_from_payback(上次实测回本枪数)`。语义：**折叠后第 `min_gap_shots` 枪起才允许
	再折**（`shots_since_fold` 从 1 起算）——即"需要 N 枪才回本，那 N 枪之内不许再折"。
	"""
	region = max(0, int(region_tokens_))
	head_delta = max(0, int(head_delta_tokens))
	tail = max(0, int(tail_tokens_))
	shots = max(0, int(shots_since_fold))
	saved = max(0, region - head_delta)
	dec = FoldDecision(
		fold=False,
		saved=saved,
		head_delta=head_delta,
		tail_tokens=tail,
		shots_since_fold=shots,
		margin=float(margin),
		price_ratio=float(price_ratio),
		reason="",
	)
	if region <= 0:
		return _with(dec, False, "empty_region")
	payback = payback_from_economics(price_ratio, dec.transition, saved)
	dec = _replace(dec, payback_shots=payback)
	if shots < max(1, int(min_gap_shots)):
		return _with(dec, False, "cooldown")
	if saved <= 0:
		return _with(dec, False, "nothing_saved")
	ok = float(saved) >= theta_required(margin=margin, price_ratio=price_ratio) * float(dec.transition)
	return _with(dec, ok, "worth_fold" if ok else "pays_back_too_slow")


def _replace(dec: FoldDecision, **over) -> FoldDecision:
	return FoldDecision(**{**asdict_shallow(dec), **over})


def asdict_shallow(dec: FoldDecision) -> dict:
	return {"fold": dec.fold, "saved": dec.saved, "head_delta": dec.head_delta,
	        "tail_tokens": dec.tail_tokens, "shots_since_fold": dec.shots_since_fold,
	        "margin": dec.margin, "price_ratio": dec.price_ratio,
	        "reason": dec.reason, "payback_shots": dec.payback_shots}


def _with(dec: FoldDecision, fold: bool, reason: str) -> FoldDecision:
	return _replace(dec, fold=fold, reason=reason)


@dataclass
class CadenceState:
	"""跨轮携带的折叠节奏状态（自我校准的压缩比估计）。

	`observed_ratio` = 上一次折叠实测的「头增量 / 区域 token」。
	它让判据在**没有渲染**的情况下也能拿到 `head_delta` 的估计（O(1)）。

	## 为什么必须给估计**封顶**（实测踩过的死亡螺旋）

	`head_delta/区域` 这个比值在真实语料上跨度极大（实测 0.03 → 0.7：
	小区域配一次大追加就接近 1）。若让它无上界地进判据，会出现自锁：

	```
	某次折叠的比值偏高 → head_delta_est 偏大 → saved=区域−headΔ 偏小、transition 偏大
	  → 判据拒绝折叠 → 区域越积越大 → 下一次比值更偏 → 永久拒绝
	```

	实测（200 回合会话）：比值爬到 **0.69** 后，`headΔ_est = 76053 / 区域 109857`
	⇒ `saved=33804`、`transition=78811` ⇒ 判据此后每轮都拒 ⇒ 尾部涨到 20 万 token。

	**封顶是有结构依据的**（不是拍脑袋）：头在 journal 布局下达到阈值时只记录逻辑换头，
	append-only 不再把头替换成紧凑渲染，因此该阈值不是热层长度上界。`head_delta_cap`
	仍作为判据的保守估计封顶，避免观测噪声把折叠节奏推入自锁；它不代表实际热层长度。
	"""

	observed_ratio: float = DEFAULT_HEAD_RATIO
	#: 距上一次真折叠过了几次请求。`decide()` 自己维护（一次调用 = 一个请求边界），
	#: 所以冷却条件不需要调用方传计数器——也传不了：调用方有 4 个，各自数法不同。
	since_fold: int = 0
	#: 头增量的结构上界（token）。0 = 不封顶（仅在调用方明确知道界时省略）。
	head_delta_cap: int = 0
	#: 当前生效的冷却下限（枪）：= 上一次折叠实测回本枪数，夹在 [MIN_GAP_SHOTS, gap_cap_shots]。
	#: 语义是「回本要 N 枪 ⇒ 这 N 枪之内不许再折」，所以是**跟随后果**的下界，
	#: 不是先验常数。初值 MIN_GAP_SHOTS = 与旧行为逐字一致。
	gap_shots: int = MIN_GAP_SHOTS
	#: `gap_shots` 的封顶。0 = 用 DEFAULT_GAP_CAP_SHOTS。
	gap_cap_shots: int = 0
	#: 上一次折叠实测的回本枪数（payback，仅诊断/回读用；∞ 记为 -1.0）。
	last_payback_shots: float = 0.0
	folds: int = 0
	skips: int = 0
	last_reason: str = ""

	def effective_gap_cap(self) -> int:
		"""冷却上界：字段 > env > 缺省。实现见模块级 `effective_gap_cap`（同一份）。"""
		return effective_gap_cap(self.gap_cap_shots)

	def adopt_gap(self, gap_shots: int) -> None:
		"""接收**外部（生产链）实测**的冷却枪数，只收紧不放宽（fail-open 方向固定）。

		活路径的折叠落点在 `memory.runtime.try_extend_c2`（它把实测回本枪数写进
		working.c2_gap_shots），而 WSC 发射侧的节奏由本状态维护——同一个会话里两条
		路径都会折叠，所以冷却必须是**一个数**：这里取两者的最大值，绝不取小。
		"""
		try:
			gap = int(gap_shots)
		except (TypeError, ValueError):
			return
		if gap > int(self.gap_shots):
			self.gap_shots = min(gap, self.effective_gap_cap())

	def estimate_head_delta(self, region_tokens_: int) -> int:
		est = int(max(0.0, self.observed_ratio) * max(0, int(region_tokens_)))
		if self.head_delta_cap > 0:
			# 头不可能因为「区域大」而无限变大：它有结构上界（见类文档）。
			est = min(est, int(self.head_delta_cap))
		return max(0, est)

	def decide(
		self,
		*,
		region_tokens_: int,
		tail_tokens_: int,
		shots_since_fold: int | None = None,
		margin: float = DEFAULT_MARGIN,
		price_ratio: float = PRICE_RATIO_HIT_MISS,
		prompt_tokens: int = 0,
	) -> FoldDecision:
		# 冷却量由状态自己数：调用方只要"每个请求边界问一次"，不必各自维护计数。
		self.since_fold += 1
		shots = int(shots_since_fold) if shots_since_fold is not None else self.since_fold
		dec = fold_economics(
			region_tokens_=region_tokens_,
			head_delta_tokens=self.estimate_head_delta(region_tokens_),
			tail_tokens_=tail_tokens_,
			shots_since_fold=shots,
			margin=margin,
			price_ratio=price_ratio,
			min_gap_shots=self.gap_shots,
		)
		self.last_reason = dec.reason
		if dec.fold:
			self.folds += 1
			self.since_fold = 0
			# 这次折叠要几枪回本 ⇒ 接下来这几枪不许再折（引擎自决的冷却）。判据用的是
			# `saved≥θ×transition` 的理想界，实测 payback 可能更大（头增量被估低时），
			# 所以用实测值而不是重算 θ——这正是"跟随后果"。
			self.last_payback_shots = float(dec.payback_shots)
			gap = gap_from_payback(self.last_payback_shots, cap=self.effective_gap_cap())
			if int(prompt_tokens) > 0:
				# 命中率约束（token 口径）：本次折叠往上下文里注入 `transition` 个未命中
				# token，而这段冷却期内读过的 prompt 总量约 `gap × prompt_tokens`，于是
				# 未命中占比 ≤ 1 − TARGET_HIT_RATE 要求 `gap ≥ transition / (0.01 × prompt)`。
				# prompt 越小这条越严 ⇒ 尾部/小上下文自动停止折叠，无需另一条规则。
				gap = min(
					max(gap, fold_gap_required(
						self.last_payback_shots, dec.transition, prompt_tokens
					)),
					self.effective_gap_cap(),
				)
			self.gap_shots = int(gap)
		else:
			self.skips += 1
		return dec

	def observe(self, *, region_tokens_: int, head_delta_tokens: int) -> None:
		"""回填实测追加比（滑动平均，优先近期）。**低层接口**，调用方见 `observe_fold`。"""
		if region_tokens_ <= 0:
			return
		r = max(0.0, float(head_delta_tokens) / float(region_tokens_))
		# 比值 > 1 只可能来自「头从无到有或整层重写」，不是追加比 —— 拒收。
		if r > 1.0:
			return
		# 0.5 权重：既不因为一次异常折叠把估计打飞，也不永远停在先验上。
		self.observed_ratio = 0.5 * self.observed_ratio + 0.5 * r

	def observe_fold(
		self, *, region_tokens_: int, head_delta_tokens: int, carried_over: bool
	) -> None:
		"""折叠落地后回填 —— **只有「头被沿用（追加）」的折叠才许喂进来**。

		⚠️ `carried_over=False`（首折 / 日志重冻结：头从无到有或整层重写）**必须不喂**：
		那时 `head_delta` 是「整个新头」，不是「追加量」，量级完全不同。
		喂进去会把追加比估计抬到 1.0 量级 ⇒ 此后 `saved = region − head_delta ≈ 0`、
		`transition ≈ region + tail` ⇒ **判据永久拒绝折叠**。

		实测代价（官方 harness，`--fold-cadence econ`，全语料 736 回合）：
		喂了首折 ⇒ 长会话折叠数 41 → **14**、全语料 ΣL 6.7M → **21.8M**、成本 ¥7.33 → ¥8.27。
		"""
		if not carried_over:
			return
		self.observe(region_tokens_=region_tokens_, head_delta_tokens=head_delta_tokens)
