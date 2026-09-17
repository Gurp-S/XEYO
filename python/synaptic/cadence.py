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

#: 默认保守边际。1.0 = 只要期望收益为正就折。
#:
#: ⚠️ **第十二轮复扫更正**：第十轮那张「最优 0.25」的 U 形表（0.1→0.9583、
#: 0.25→0.9363、0.5→0.9452、3.0→1.0817、每回合折→1.0546）是在**带自锁的系统**上
#: 扫出来的——那时 `estimate_head_delta` 无上界，估计一旦偏高就永久拒折
#: （见 `CadenceState` 的死亡螺旋说明）。**参数扫描在带自锁的系统上会给出错的极值。**
#: 修掉自锁后，长会话子集（405 回合）单调偏好小 margin：0.1 → ¥4.5877、
#: 0.25 → ¥4.6654、0.5 → ¥4.6716。故默认值改为 **0.1**（越小越爱折，
#: 但 `margin=0` 会退化成「只要 saved>0 就折」，实测更贵 —— 仍需要一个正边际）。
DEFAULT_MARGIN = 0.1

#: 首折前对「头增量 / 区域」的保守估计（无观测时的先验）。
#: 偏大 = 更保守（更不容易折）。实测 Medium+ 长会话的头增量约为区域的 0.10–0.20。
DEFAULT_HEAD_RATIO = 0.20

#: 剩余轮次启发式的上下限（与 `memory/simulator/replay.py::estimate_remaining` 同口径）。
REMAINING_CAP = 24
REMAINING_FLOOR = 4

#: 收尾信号：用户明确表示结束时，剩余轮次按 1 计（不值得为最后一轮付过渡代价）。
_WRAP_UP = ("就这样", "谢谢", "够了", "可以了", "结束")


def estimate_remaining(messages: list[dict[str, Any]]) -> int:
	"""剩余用户轮次估计（生产同口径的内联实现）。

	口径（与 `memory/simulator/replay.py::estimate_remaining` 逐值一致，有契约测试）：
	收尾语 ⇒ 1；否则 `min(cap, max(floor, 16 − n_user // 8))`，即会话越深越保守。
	"""
	texts: list[str] = []
	for m in messages:
		if not isinstance(m, dict) or m.get("role") != "user":
			continue
		c = m.get("content")
		if isinstance(c, str):
			texts.append(c)
		elif isinstance(c, list) and not any(
			isinstance(b, dict) and b.get("type") == "tool_result" for b in c
		):
			texts.append("")
	if texts:
		last = texts[-1]
		if any(x in last for x in _WRAP_UP):
			return 1
	n_user = max(1, len(texts))
	return min(REMAINING_CAP, max(REMAINING_FLOOR, 16 - n_user // 8))


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
	remaining: int
	margin: float
	price_ratio: float
	reason: str

	@property
	def transition(self) -> int:
		"""折叠当轮的一次性 miss ≈ 头新增 + 仍逐字保留的尾部。"""
		return self.head_delta + self.tail_tokens

	@property
	def lhs(self) -> float:
		"""左边 = 预期省下的钱（相对单位）。"""
		return self.remaining * self.saved

	@property
	def rhs(self) -> float:
		"""右边 = 需要摊平的过渡代价（已含 margin 与价差倍率）。"""
		return self.price_ratio * self.margin * self.transition

	def as_dict(self) -> dict[str, Any]:
		return {
			"fold": self.fold,
			"region_saved": self.saved,
			"head_delta": self.head_delta,
			"tail_tokens": self.tail_tokens,
			"transition": self.transition,
			"remaining": self.remaining,
			"margin": self.margin,
			"price_ratio": self.price_ratio,
			"lhs": round(self.lhs, 3),
			"rhs": round(self.rhs, 3),
			"reason": self.reason,
		}


def fold_economics(
	*,
	region_tokens_: int,
	head_delta_tokens: int,
	tail_tokens_: int,
	remaining_turns: int,
	margin: float = DEFAULT_MARGIN,
	price_ratio: float = PRICE_RATIO_HIT_MISS,
) -> FoldDecision:
	"""纯函数判据：`R × saved ≥ price_ratio × margin × transition`。

	`margin = 0` 退化为「只要期望收益为正就折」；`margin → ∞` 退化为「永不折」。
	"""
	region = max(0, int(region_tokens_))
	head_delta = max(0, int(head_delta_tokens))
	tail = max(0, int(tail_tokens_))
	remaining = max(1, int(remaining_turns))
	saved = max(0, region - head_delta)
	dec = FoldDecision(
		fold=False,
		saved=saved,
		head_delta=head_delta,
		tail_tokens=tail,
		remaining=remaining,
		margin=float(margin),
		price_ratio=float(price_ratio),
		reason="",
	)
	if region <= 0:
		return _with(dec, False, "empty_region")
	ok = dec.lhs >= dec.rhs
	return _with(dec, ok, "worth_fold" if ok else "not_amortized")


def _with(dec: FoldDecision, fold: bool, reason: str) -> FoldDecision:
	return FoldDecision(
		fold=fold,
		saved=dec.saved,
		head_delta=dec.head_delta,
		tail_tokens=dec.tail_tokens,
		remaining=dec.remaining,
		margin=dec.margin,
		price_ratio=dec.price_ratio,
		reason=reason,
	)


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
		remaining_turns: int,
		margin: float = DEFAULT_MARGIN,
		price_ratio: float = PRICE_RATIO_HIT_MISS,
	) -> FoldDecision:
		dec = fold_economics(
			region_tokens_=region_tokens_,
			head_delta_tokens=self.estimate_head_delta(region_tokens_),
			tail_tokens_=tail_tokens_,
			remaining_turns=remaining_turns,
			margin=margin,
			price_ratio=price_ratio,
		)
		self.last_reason = dec.reason
		if dec.fold:
			self.folds += 1
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
