"""ρ̂(C) TTL buckets and provider stub."""

from __future__ import annotations

import pytest

from memory.simulator.cache_model import CacheState, get_profile, rho_hat
from memory.simulator.params import load_params
from memory.simulator.probe import TTL_SLEEP


def test_rho_decays_with_age():
	p = load_params()
	r0 = rho_hat(CacheState(age_seconds=0), p)
	r5 = rho_hat(CacheState(age_seconds=300), p)
	r10 = rho_hat(CacheState(age_seconds=600), p)
	r1h = rho_hat(CacheState(age_seconds=3600), p)
	r2h = rho_hat(CacheState(age_seconds=8000), p)
	assert abs(r0 - p.alpha_hit) < 1e-12
	assert abs(r5 - p.alpha_hit) < 1e-12  # 温缓存：表值 1.0 × α（ω≈0.99 取 max 仍=α）
	assert r10 < r5
	assert r1h < r10
	# ω 冷却平滑（已固化开启）：长挂机 = α × ω_floor 下包络，不再打到 0
	assert r2h == pytest.approx(p.alpha_hit * p.omega_floor)


def test_provider_abstraction():
	assert get_profile("deepseek").name == "deepseek"
	assert get_profile("openai").name == "openai"
	assert get_profile("deepseek").invoice_w_phys_zero


def test_ttl_matrix_keys():
	assert set(TTL_SLEEP) >= {"continuous", "5min", "10min", "30min", "1h", "2h"}


def test_ttl_grid_rho():
	from memory.simulator.probe import ttl_grid_rho

	rows = ttl_grid_rho()
	assert [r["ttl"] for r in rows][0] == "continuous"
	assert rows[0]["rho"] > rows[-1]["rho"]
