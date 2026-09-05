"""Calibration scans write overlay only; one param at a time."""

from __future__ import annotations

from pathlib import Path

from memory.simulator.calibration import (
	apply_overlay,
	best_rho,
	hit_records_from_events,
	scan_alpha_win,
	scan_beta,
	scan_kappa,
	scan_lambda_q,
	scan_r_cap,
	scan_rho,
	scan_t_k,
	scan_tau,
	scan_theta,
)
from memory.simulator.metrics import HitRecord
from memory.simulator.params import load_params


def _row(pred: float, obs: float) -> HitRecord:
	return HitRecord(
		request_id="r",
		provider="deepseek",
		cache_age=0.0,
		action="keep",
		LCP=64,
		predicted_hit=pred,
		observed_hit=obs,
		prompt_tokens=1000,
		output_tokens=10,
		predicted_cost=0.0,
		actual_cost=0.0,
		context_length=1000,
	)


def test_rho_scan_picks_closer_alpha(tmp_path: Path):
	# predicted 按 alpha=0.95 计算；observed 约为其 0.80/0.95
	base = load_params()
	pred = 950.0
	obs = 800.0  # would match alpha ~ 0.80
	points = scan_rho([_row(pred, obs)], base)
	assert [p.value for p in points] == [0.7, 0.8, 0.9, 0.95, 1.0]
	best = best_rho(points)
	assert best in (0.7, 0.8, 0.9)


def test_overlay_write_does_not_touch_formula(tmp_path: Path):
	path = tmp_path / "ov.json"
	apply_overlay("kappa", 0.4, path)
	text = path.read_text(encoding="utf-8")
	assert "0.4" in text
	p = load_params(path)
	assert p.kappa == 0.4
	fresh = load_params()
	assert abs(fresh.kappa - 0.8) < 1e-12


def test_kappa_theta_tau_scans_run():
	p = load_params()
	k = scan_kappa(p)
	th = scan_theta(p)
	tau = scan_tau(p)
	assert len(k) == 5
	assert len(th) == 5
	assert len(tau) == 4
	assert "success_proxy" in k[0].metrics


def test_new_param_scans_run():
	p = load_params()
	aw = scan_alpha_win(p)
	beta = scan_beta(p)
	tk = scan_t_k(p)
	rc = scan_r_cap(p)
	lq = scan_lambda_q(p)
	assert len(aw) == 5
	assert len(beta) == 5
	assert len(tk) == 5
	assert len(rc) == 4
	assert len(lq) == 5
	# β 只做健康信号：扫描指标是 G_β 触发率，不是动作选择
	assert "gbeta_rate" in beta[0].metrics


def test_overlay_new_keys(tmp_path: Path):
	apply_overlay("alpha_win", 0.6, tmp_path / "o1.json")
	apply_overlay("t_k", 4, tmp_path / "o2.json")
	apply_overlay("r_cap", 16, tmp_path / "o3.json")
	apply_overlay("lambda_q", 4.0, tmp_path / "o4.json")
	apply_overlay("beta", 12, tmp_path / "o5.json")
	assert load_params(tmp_path / "o1.json").alpha_win == 0.6
	assert load_params(tmp_path / "o2.json").t_k_count == 4
	assert load_params(tmp_path / "o3.json").r_cap == 16
	assert load_params(tmp_path / "o4.json").lambda_q == 4.0
	assert load_params(tmp_path / "o5.json").beta == 12


def test_lambda_q_changes_action_cost():
	from memory.simulator.cache_model import prices_for
	from memory.simulator.cost_model import c_action_yuan
	from memory.simulator.params import Params
	from memory.simulator.scenarios import list_scenarios
	from memory.simulator.state_model import apply as apply_action

	p = load_params()
	sc = next(
		s
		for s in list_scenarios(smoke=True)
		if s.kind == "F" and s.length_class == "S3" and s.tool_size_class == "T1"
	)
	s0 = sc.state()
	sa = apply_action("C1", s0, p)
	prices = prices_for(sc.cache(p), p)
	cheap = c_action_yuan("C1", s0, sa, prices, Params(lambda_q=0.5))
	dear = c_action_yuan("C1", s0, sa, prices, Params(lambda_q=8.0))
	assert dear > cheap


def test_hit_records_from_events_roundtrip(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	from usage.ledger import record_calibration_shot

	record_calibration_shot(
		session_id="s",
		action="C2",
		lcp=0,
		predicted_hit=0.0,
		observed_hit=64.0,
		prompt_tokens=1000,
		output_tokens=5,
		conversation_length=4,
	)
	rows = hit_records_from_events()
	assert len(rows) == 1
	assert rows[0].action == "C2"
	assert rows[0].observed_hit == 64.0
	assert rows[0].conversation_length == 4
