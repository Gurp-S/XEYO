"""C_biz, Ĥ clip, exclusive H+U+W_phys=|X|, C_action at h=0 only."""

from __future__ import annotations

import math
from dataclasses import dataclass

from memory.simulator.cache_model import CacheState, Prices, prices_for, rho_hat
from memory.simulator.params import Params, load_params
from memory.simulator.projection import Projected, lcp_tokens, project
from memory.simulator.quality_model import QualityResult, evaluate_quality
from memory.simulator.state_model import ContextState, apply


@dataclass(frozen=True)
class Split:
	H: float
	U: float
	W_phys: float  # invoice partition
	W_fill: float  # simulator physical fill, not billed on DeepSeek
	L: int
	lcp: int
	rho: float

	@property
	def ok(self) -> bool:
		return abs(self.H + self.U + self.W_phys - self.L) <= 1e-6


def hat_H(
	*,
	x_a: str,
	x_prev: str,
	L: int,
	action: str,
	rho: float,
	g: int,
	x_prev_frozen_len: int = 0,
) -> tuple[float, int]:
	"""Return (Ĥ, LCP tokens). C2 保留左段 P（实现与模拟器投影一致）→ 按 LCP 正常算；
	只有真正从头重建（x_prev 无共同前缀）才自然为 0。

	P1 缺失2：若已知上一枪投影的冻结前缀长度（``x_prev_frozen_len``，来自
	``ProjectionDigest.frozen_len``），用它作 lcp_keep——可重入、无需重放全文，
	重启后仍能估出 keep 的命中。未知（=0）时回退字符串 LCP（行为不变）。
	"""
	_ = action
	if x_prev_frozen_len > 0:
		lcp = min(int(x_prev_frozen_len), int(L))
	else:
		lcp = lcp_tokens(x_a, x_prev)
	blk = g * math.floor(lcp / g) if g > 0 else 0
	h = rho * blk
	h = min(float(L), max(0.0, h))
	return h, lcp


def split_tokens(
	*,
	s_a: ContextState,
	cache: CacheState,
	action: str,
	params: Params,
	proj: Projected | None = None,
) -> tuple[Projected, Split]:
	pr = proj or project(s_a)
	rho = rho_hat(cache, params)
	h, lcp = hat_H(
		x_a=pr.x,
		x_prev=cache.x_prev,
		L=pr.length,
		action=action,
		rho=rho,
		g=params.g,
		x_prev_frozen_len=getattr(cache, "x_prev_frozen_len", 0),
	)
	w_inv = 0.0 if params.invoice_w_phys_zero else 0.0
	u = float(pr.length) - h - w_inv
	if u < -1e-9:
		raise RuntimeError("U negative: Ĥ clip failed")
	u = max(0.0, u)
	# Physical fill (not billed): new aligned blocks beyond hit.
	w_fill = max(float(pr.length) - h, 0.0)
	return pr, Split(H=h, U=u, W_phys=w_inv, W_fill=w_fill, L=pr.length, lcp=lcp, rho=rho)


def expected_output(Q: float, params: Params) -> float:
	if Q <= 0:
		return params.o_mean * 2.0
	if Q < params.theta:
		return params.o_mean * min(2.0, params.theta / Q)
	return params.o_mean


def c_biz_yuan(split: Split, o: float, prices: Prices) -> float:
	return (
		prices.p_r * split.H
		+ prices.p_u * split.U
		+ prices.p_w * split.W_phys
		+ prices.p_o * max(o, 0.0)
	) / 1_000_000.0


def c_qual_yuan(D: float, s0: ContextState, prices: Prices, params: Params) -> float:
	m_tok = max(sum(v for _i, v in s0.frozen_v), 1)
	round_cost = prices.p_o * params.o_mean / 1_000_000.0
	return params.lambda_q * round_cost * (D / m_tok)


def c_action_yuan(
	action: str,
	s0: ContextState,
	s_a: ContextState,
	prices: Prices,
	params: Params,
	qual: QualityResult | None = None,
) -> float:
	if action == "keep":
		return 0.0
	q = qual or evaluate_quality(s_a, s0, params)
	return params.c_cmp + c_qual_yuan(q.D, s0, prices, params)


@dataclass(frozen=True)
class ShotCost:
	action: str
	L: int
	H: float
	U: float
	W_phys: float
	W_fill: float
	lcp: int
	rho: float
	Q: float
	D: float
	O: float
	c_biz: float
	c_action: float
	alarms: tuple[str, ...]
	x: str
	G_beta: int


def shot_cost(
	s0: ContextState,
	action: str,
	cache: CacheState,
	params: Params | None = None,
	*,
	charge_action: bool = True,
) -> tuple[ContextState, ShotCost]:
	p = params or load_params()
	s_a = apply(action, s0, p) if action in ("keep", "C1", "C2") else s0
	qual = evaluate_quality(s_a, s0, p)
	proj, spl = split_tokens(s_a=s_a, cache=cache, action=action, params=p)
	prices = prices_for(cache, p)
	o = expected_output(qual.Q, p)
	biz = c_biz_yuan(spl, o, prices)
	act = c_action_yuan(action, s0, s_a, prices, p, qual) if charge_action else 0.0
	return s_a, ShotCost(
		action=action,
		L=spl.L,
		H=spl.H,
		U=spl.U,
		W_phys=spl.W_phys,
		W_fill=spl.W_fill,
		lcp=spl.lcp,
		rho=spl.rho,
		Q=qual.Q,
		D=qual.D,
		O=o,
		c_biz=biz,
		c_action=act,
		alarms=qual.alarms,
		x=proj.x,
		G_beta=qual.G_beta,
	)
