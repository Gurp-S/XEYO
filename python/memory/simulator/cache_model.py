"""Cache state C orthogonal to S. ρ̂(C). Provider abstraction; DeepSeek filled."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, replace
from typing import Protocol

from memory.simulator.params import Params, load_params
from usage.pricing import unit_prices_cny_per_mtoken

# A1（优化4）冷却平滑：**已固化开启**（收益明确过验收，不再是开关）。
# 原开关 XEYO_CACHE_COOLDOWN_OMEGA 已移出 memory_switches 注册表；
# 回退只能改 cooldown_enabled() 源码。


@dataclass(frozen=True)
class Prices:
	p_r: float
	p_u: float
	p_o: float
	p_w: float = 0.0


@dataclass(frozen=True)
class CacheState:
	provider: str = "deepseek"
	age_seconds: float = 0.0
	cache_history: tuple[str, ...] = ()
	cache_mode: str = "implicit"
	x_prev: str = ""
	# P1 缺失2：上一枪投影的冻结前缀 token 长度（可重入计量，重启用它估 lcp_keep；
	# 0 表示未知，调用方保守取 0）。见 memory.working.ProjectionDigest。
	x_prev_frozen_len: int = 0
	model: str = "deepseek-v4-flash"
	slot: str = "offpeak"
	ts: float = 0.0


class ProviderProfile(Protocol):
	name: str
	g: int
	invoice_w_phys_zero: bool

	def survival(self, age_seconds: float, params: Params) -> float: ...

	def prices(self, cache: CacheState, params: Params) -> Prices: ...


def survival_from_table(age_seconds: float, params: Params) -> float:
	age = max(0.0, float(age_seconds))
	s = 0.0
	for max_age, surv in params.rho_age_table:
		s = surv
		if age <= max_age:
			break
	return min(1.0, max(0.0, s))


def cooldown_enabled() -> bool:
	"""A1 ω 冷却平滑：**恒 True**（已固化开启；原 XEYO_CACHE_COOLDOWN_OMEGA 键已删）。"""
	return True


def cooldown_omega(age_seconds: float, params: Params) -> float:
	"""ω(Δt) = max(ω_floor, e^(−Δt/T½))。挂机 1 分钟 ≈0.99；4 小时 = floor（默认 0.4）。"""
	t_half = max(1.0, float(getattr(params, "omega_half_life_min", 60.0)) * 60.0)
	w = math.exp(-max(0.0, float(age_seconds or 0.0)) / t_half)
	floor = min(1.0, max(0.0, float(getattr(params, "omega_floor", 0.4))))
	return max(floor, w)


def rho_hat(cache: CacheState, params: Params | None = None) -> float:
	p = params or load_params()
	s = survival_from_table(cache.age_seconds, p)
	rho = min(1.0, max(0.0, s * p.alpha_hit))
	if cooldown_enabled():
		# A1：age 衰减交给 ω 的平滑下包络——TTL 桶打到 0 时预测不再「反正 miss」，
		# 而是 max(表值, age0 存活 × ω)。短挂机几乎不变（ω≈1），长挂机温和打折不归零。
		base = survival_from_table(0.0, p) * p.alpha_hit
		smooth = min(1.0, max(0.0, base * cooldown_omega(cache.age_seconds, p)))
		rho = max(rho, smooth)
	return min(1.0, max(0.0, rho))


def prices_for(cache: CacheState, params: Params | None = None) -> Prices:
	p = params or load_params()
	ts = cache.ts or p.default_ts
	p_r, p_u, p_o, p_w = unit_prices_cny_per_mtoken(
		provider=cache.provider or p.provider,
		model=cache.model or p.model,
		ts=ts,
		slot=cache.slot or p.price_slot,
	)
	return Prices(p_r=p_r, p_u=p_u, p_o=p_o, p_w=p_w)


@dataclass(frozen=True)
class DeepSeekProfile:
	name: str = "deepseek"
	g: int = 64
	invoice_w_phys_zero: bool = True

	def survival(self, age_seconds: float, params: Params) -> float:
		return survival_from_table(age_seconds, params)

	def prices(self, cache: CacheState, params: Params) -> Prices:
		return prices_for(cache, params)


@dataclass(frozen=True)
class OpenAIProfile:
	"""Stub for a future provider. P2 does not calibrate OpenAI."""

	name: str = "openai"
	g: int = 128
	invoice_w_phys_zero: bool = True

	def survival(self, age_seconds: float, params: Params) -> float:
		return survival_from_table(age_seconds, params)

	def prices(self, cache: CacheState, params: Params) -> Prices:
		return prices_for(replace(cache, provider="openai"), params)


def get_profile(provider: str) -> ProviderProfile:
	if (provider or "").lower() == "openai":
		return OpenAIProfile()
	return DeepSeekProfile()


def after_request(cache: CacheState, *, x_sent: str, action: str) -> CacheState:
	"""Warm cache after a shot: age=0, remember X, append history."""
	return replace(
		cache,
		age_seconds=0.0,
		x_prev=x_sent,
		cache_history=cache.cache_history + (action,),
	)
