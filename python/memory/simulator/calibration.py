"""Single-parameter calibration. Writes overlay only; does not change formulas."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Sequence

from memory.simulator.metrics import HitRecord, cache_errors, summarize_values
from memory.simulator.params import Params, load_params, write_overlay

RHO_GRID_ALPHA = (0.70, 0.80, 0.90, 0.95, 1.00)
KAPPA_GRID = (0.2, 0.4, 0.6, 0.8, 1.0)
THETA_GRID = (0.25, 0.30, 0.35, 0.40, 0.50)
TAU_GRID = (0.90, 0.85, 0.80, 0.75)
ALPHA_WIN_GRID = (0.45, 0.50, 0.55, 0.60, 0.65)
BETA_GRID = (4, 6, 8, 12, 16)
T_K_GRID = (1, 2, 3, 4, 6)
R_CAP_GRID = (12, 16, 24, 32)
LAMBDA_Q_GRID = (0.5, 1.0, 2.0, 4.0, 8.0)


@dataclass(frozen=True)
class ScanPoint:
	value: float
	metrics: dict[str, Any]


def _quantiles(xs: Sequence[float]) -> dict[str, float]:
	return summarize_values(xs)


def scan_rho(
	rows: Sequence[HitRecord],
	base: Params | None = None,
	grid: Sequence[float] = RHO_GRID_ALPHA,
) -> list[ScanPoint]:
	"""Fit α_hit (ρ = s α_hit). Recompute Ĥ = (H_pred / old_alpha) * new_alpha if H used P0."""
	p = base or load_params()
	out: list[ScanPoint] = []
	old = p.alpha_hit if p.alpha_hit else 1.0
	for a in grid:
		scaled = []
		for r in rows:
			ratio = a / old
			pred = r.predicted_hit * ratio
			scaled.append(
				HitRecord(
					request_id=r.request_id,
					provider=r.provider,
					cache_age=r.cache_age,
					action=r.action,
					LCP=r.LCP,
					predicted_hit=pred,
					observed_hit=r.observed_hit,
					prompt_tokens=r.prompt_tokens,
					output_tokens=r.output_tokens,
					predicted_cost=r.predicted_cost,
					actual_cost=r.actual_cost,
					context_length=r.context_length,
					conversation_length=r.conversation_length,
					tool_result_size=r.tool_result_size,
				)
			)
		err = cache_errors(scaled)
		abs_err = [abs(x.predicted_hit - x.observed_hit) for x in scaled]
		err.update(_quantiles(abs_err))
		out.append(ScanPoint(value=float(a), metrics=err))
	return out


def best_rho(points: Sequence[ScanPoint]) -> float:
	if not points:
		return 0.95
	# prefer lowest MAE, then |Bias|
	return min(points, key=lambda p: (p.metrics.get("MAE", 1e9), abs(p.metrics.get("Bias", 1e9)))).value


def scan_numeric(
	grid: Sequence[float],
	evaluate: Callable[[float], dict[str, Any]],
) -> list[ScanPoint]:
	return [ScanPoint(value=float(v), metrics=evaluate(v)) for v in grid]


def apply_overlay(
	param: str,
	value: float,
	path: Path | None = None,
) -> Path:
	key = {
		"rho": "alpha_hit",
		"alpha_hit": "alpha_hit",
		"kappa": "kappa",
		"theta": "theta",
		"tau_switch": "tau_switch",
		"tau": "tau_switch",
		"alpha_win": "alpha_win",
		"beta": "beta",
		"t_k": "t_k_count",
		"t_k_count": "t_k_count",
		"r_cap": "r_cap",
		"lambda_q": "lambda_q",
	}.get(param)
	if not key:
		raise ValueError(f"unknown calibration param: {param}")
	return write_overlay({key: value}, path)


def evaluate_action_mix(params: Params) -> dict[str, Any]:
	from collections import Counter

	from memory.simulator.decision import decide
	from memory.simulator.scenarios import list_scenarios

	c = Counter()
	success_proxy = 0
	n = 0
	loops = 0
	wanted = {"empty_m", "short:2", "short:5"}
	for sc in list_scenarios(smoke=True):
		if sc.id not in wanted and sc.kind not in ("F", "B"):
			continue
		if sc.tool_size_class not in ("T1", "T2"):
			continue
		if sc.length_class not in ("S1", "S2"):
			continue
		n += 1
		d = decide(
			sc.state(),
			sc.cache(params),
			remaining_turns=sc.remaining_turns,
			params=params,
			delta_text=sc.delta_text,
			forecast="p0",
		)
		c[d.a_star] += 1
		if d.a_star != "L4":
			success_proxy += 1
		if sc.kind == "F" and d.a_star == "keep":
			loops += 1
		if n >= 8:
			break
	return {
		"n": n,
		"keep_rate": c["keep"] / max(n, 1),
		"C1_rate": c["C1"] / max(n, 1),
		"C2_rate": c["C2"] / max(n, 1),
		"HardTop_rate": 0.0,
		"success_proxy": success_proxy / max(n, 1),
		"repeat_tool_keep_rate": loops / max(n, 1),
		"counts": dict(c),
	}


def scan_kappa(base: Params | None = None) -> list[ScanPoint]:
	p0 = base or load_params()
	return scan_numeric(KAPPA_GRID, lambda k: evaluate_action_mix(replace(p0, kappa=k)))


def scan_theta(base: Params | None = None) -> list[ScanPoint]:
	p0 = base or load_params()
	return scan_numeric(THETA_GRID, lambda t: evaluate_action_mix(replace(p0, theta=t)))


def scan_tau(base: Params | None = None) -> list[ScanPoint]:
	p0 = base or load_params()
	return scan_numeric(TAU_GRID, lambda t: evaluate_action_mix(replace(p0, tau_switch=t)))


def scan_alpha_win(base: Params | None = None) -> list[ScanPoint]:
	"""α_win 软顶占窗口：影响 l_max → HardTop 触发率与 keep 合法面。"""
	p0 = base or load_params()
	return scan_numeric(ALPHA_WIN_GRID, lambda v: evaluate_action_mix(replace(p0, alpha_win=v)))


def _evaluate_gbeta(params: Params, beta: int) -> dict[str, Any]:
	"""G_β 只做健康信号不进 F_R/J：扫描它的指标是「触发率」，不是动作选择。"""
	from memory.simulator.decision import decide
	from memory.simulator.scenarios import list_scenarios

	n = 0
	flagged = 0
	for sc in list_scenarios(smoke=True):
		if sc.id not in {"empty_m", "short:2", "short:5"} and sc.kind not in ("F", "B"):
			continue
		if sc.tool_size_class not in ("T1", "T2") or sc.length_class not in ("S1", "S2"):
			continue
		n += 1
		d = decide(
			sc.state(),
			sc.cache(params),
			remaining_turns=sc.remaining_turns,
			params=replace(params, beta=beta),
			delta_text=sc.delta_text,
			forecast="p0",
		)
		flagged += int(d.G_beta)
		if n >= 8:
			break
	return {
		"n": n,
		"gbeta_rate": flagged / max(n, 1),
		"flagged": flagged,
	}


def scan_beta(base: Params | None = None) -> list[ScanPoint]:
	"""β 健康阈值：只统计 G_β 触发率（信号频率），不改动作选择。"""
	p0 = base or load_params()
	return scan_numeric(BETA_GRID, lambda v: _evaluate_gbeta(p0, int(v)))


def scan_t_k(base: Params | None = None) -> list[ScanPoint]:
	"""T_k 尾部保留条数：影响近因保真（Q/D）与体积，扫描动作混合与质量。"""
	p0 = base or load_params()
	return scan_numeric(T_K_GRID, lambda v: evaluate_action_mix(replace(p0, t_k_count=int(v))))


def scan_r_cap(base: Params | None = None) -> list[ScanPoint]:
	"""R 封顶：投票固定 {4,8,16}，r_cap 只封剩余轮数估计，扫描动作混合。"""
	p0 = base or load_params()
	return scan_numeric(R_CAP_GRID, lambda v: evaluate_action_mix(replace(p0, r_cap=int(v))))


def scan_lambda_q(base: Params | None = None) -> list[ScanPoint]:
	"""λ_q 丢信息换成钱（补救轮数）：进 C_action，影响 C1/C2 的经济门槛。"""
	p0 = base or load_params()
	return scan_numeric(LAMBDA_Q_GRID, lambda v: evaluate_action_mix(replace(p0, lambda_q=v)))


def hit_records_from_events(rows: Sequence[dict[str, Any]] | None = None) -> list[HitRecord]:
	"""把逐枪校准观测（usage/calibration_events.jsonl）转成 HitRecord，喂 scan_rho。

	predicted_cost / actual_cost 不落盘（计费在 usage ledger），这里给 0 占位。
	"""
	if rows is None:
		from usage.ledger import read_calibration_events

		rows = read_calibration_events()
	out: list[HitRecord] = []
	for r in rows:
		if not isinstance(r, dict):
			continue
		out.append(
			HitRecord(
				request_id=str(r.get("request_id") or r.get("session_id") or "shot"),
				provider=str(r.get("provider") or "deepseek"),
				cache_age=float(r.get("cache_age") or 0.0),
				action=str(r.get("action") or "keep"),
				LCP=int(r.get("LCP") or 0),
				predicted_hit=float(r.get("predicted_hit") or 0.0),
				observed_hit=float(r.get("observed_hit") or 0.0),
				prompt_tokens=int(r.get("prompt_tokens") or 0),
				output_tokens=int(r.get("output_tokens") or 0),
				predicted_cost=0.0,
				actual_cost=0.0,
				context_length=int(r.get("context_length") or 0),
				conversation_length=int(r.get("conversation_length") or 0),
				tool_result_size=int(r.get("tool_result_size") or 0),
			)
		)
	return out
