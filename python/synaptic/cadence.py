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

- **不折叠**：被折叠区继续留在上下文里，每轮按**命中价**计费 ⇒ 每轮省 `saved × p_hit`；
- **折叠**：本轮付一次**未命中价** `transition × p_miss`（前缀在头的追加点之后整段失效）；
- 剩 `R` 轮 ⇒ **折叠 ⟺ `R × saved × p_hit ≥ margin × transition × p_miss`**。

移项即本模块的判据形式：`R × saved ≥ price_ratio × margin × transition`，
`price_ratio = p_miss / p_hit = 1.5 / 0.05 = 30`（`usage/pricing.py`，deepseek-v4-flash 空闲档）。
`margin > 1` 表示要求「预期收益至少是过渡代价的 margin 倍」，是保守边际。

### 三项量怎么取（都是 O(1)，不需要渲染）

- `region_tokens`：**将离开上下文的那一段**的 token（区域 = 上次折叠边界到本次切点）；
- `head_delta_tokens`：折叠给头增加的量。**不许猜**——用本会话**上一次折叠实测到的
  压缩比**外推（`CadenceState.observed_ratio`），首折用保守默认
  `DEFAULT_HEAD_RATIO`。这是本模块唯一的经验项，且它自我校准。
- `tail_tokens`：折叠后仍逐字保留的尾部（= 折叠当轮 miss 的另一半）。

## 与生产 `try_extend_c2` 的关系（同源，但它偏保守两处）

`memory/runtime.py::try_extend_c2` 的第 4 条闸用的是
`remaining × saved < margin × price_ratio × transition`（margin=2、price_ratio=30）。
两处差异都会**抑制折叠**：
1. 它把 `price_ratio` 直接乘在 transition 上、**再乘 margin=2** ⇒ 有效门槛 60 倍；
   本模块的门槛是 `30 × margin`（默认 0.25 ⇒ 7.5 倍）；
2. 它的 transition 只算「新摘要 + **剩余**尾部」，没算「被折叠区整段退出前缀」的那一半。
两处叠加的后果实测可见：200 回合会话它只扩展 12 次，而成本最优需要 30+ 次。

## 零生产依赖

与 `textutil.node_token_len` 同策：需要生产链的**口径**（剩余轮次启发式、价目）
就在本层**内联实现 + 契约测试**比对，绝不 import（`tests/wsc/test_isolation.py`
静态执法算法层零生产依赖）。
"""

from __future__ import annotations

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
#: 要求它 ≤ 本常数。
#:
#: ⚠️ **8 是"深折"的门槛，不是活路径浅折的门槛**（09-22 实测，`_wsc_out/_cadence_after.py`）：
#: 影子账本里单次移出比例 r 中位 89.8% ⇒ 3.4 枪（用户"只贵 2~3 枪"的直觉成立）；但活路径
#: 的折叠由 `region ≥ journal_growth_tokens(9k)` 的尺寸保底线触发，被折区只占发射的
#: 15~65%，实测回本需求 **12~238 枪** ⇒ 三条 transcript 的 34 次判定**全部被本门槛拒**
#: （`_cadence_grid.py`：K=8 与"门常开"差 1.036 vs 1.311 倍）。所以取 8 的含义是
#: "只允许深折"，不是"折叠通常 8 枪回本"——把它当后者引用会算错一个数量级。
#: 折叠当枪的重填面实测 **71.1%**（`calibration_events.action=C2`，n=38），平枪 4%。
PAYBACK_SHOTS = 8
#: `MIN_GAP_SHOTS` —— 距上次折叠至少几枪。低于回本周期的连续折叠是纯亏（付两次重填、
#: 一次都还没收回）。旧实现靠"猜还剩几轮"表达这件事，猜错了方向就反（见 §22/§25）。
MIN_GAP_SHOTS = 4
#: 保守边际。**09-22 从 0.1 钉到 1.0**：0.1 把有效门槛压到 3 倍，而实测回本点是
#: 30~40 倍（`price_ratio` × transition/saved）——低了一个数量级，所以旧 C 档
#: 每 2~3 枪折一次、三条 transcript 上实测贵 2.2~2.4 倍。
DEFAULT_MARGIN = 1.0

#: 首折前对「头增量 / 区域」的保守估计（无观测时的先验）。
#: 偏大 = 更保守（更不容易折）。实测 Medium+ 长会话的头增量约为区域的 0.10–0.20。
DEFAULT_HEAD_RATIO = 0.20

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
) -> FoldDecision:
	"""纯函数判据（**不含任何预测**）：

	```
	回本枪数 = price_ratio × transition / saved
	折  ⟺  回本枪数 ≤ PAYBACK_SHOTS / margin   且   shots_since_fold ≥ MIN_GAP_SHOTS
	```

	`margin` 是**保守边际**（>1 更保守）：0.1 ⇒ 允许等 80 枪，1.0 ⇒ 8 枪，10 ⇒ 0.8 枪。两个量都是**已发生的事实**
	（尾巴攒了几枪、这次能移出多少）加一个价目常数——旧版的 `remaining_turns` 是猜的，
	猜错方向时判据整体反向（§22 实测：剩余寿命不随会话深度衰减，旧式却越猜越小）。
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
	payback = (float(price_ratio) * float(dec.transition) / float(saved)) if saved > 0 else float("inf")
	dec = _replace(dec, payback_shots=payback)
	if shots < MIN_GAP_SHOTS:
		return _with(dec, False, "cooldown")
	if saved <= 0:
		return _with(dec, False, "nothing_saved")
	ok = payback <= PAYBACK_SHOTS / max(0.01, float(margin))
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
	folds: int = 0
	skips: int = 0
	last_reason: str = ""

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
		)
		self.last_reason = dec.reason
		if dec.fold:
			self.folds += 1
			self.since_fold = 0
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
