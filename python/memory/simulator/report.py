"""P2 Calibration Report: synthetic + replay + optional probe/A/B."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory.simulator.cache_model import CacheState
from memory.simulator.cost_model import c_biz_yuan, hat_H, prices_for, rho_hat
from memory.simulator.decision import decide
from memory.simulator.metrics import (
	ActionCounts,
	HitRecord,
	bias_flags,
	cache_errors,
	cache_errors_by_bucket,
	compact_stats,
	summarize_values,
)
from memory.simulator.params import Params, load_params, params_dict
from memory.simulator.replay import ReplaySession, baseline_tokens, replay_all
from memory.simulator.scenarios import Scenario, list_scenarios

OUT_DIR = Path(__file__).with_name("out")


@dataclass
class SuiteRow:
	scenario_id: str
	kind: str
	length_class: str
	a_star: str
	a4: str
	a8: str
	a16: str
	hardtop: bool
	G_beta: int
	L: int
	Q: float
	D: float
	H: float
	cost: float
	baseline_tokens: int
	v61_tokens: int
	baseline_cost: float
	notes: str = ""


def _baseline_cost(messages: list, cache: CacheState, params: Params) -> tuple[int, float]:
	L = baseline_tokens(messages)
	# Reconstruct a stand-in X of length L for Ĥ (P0 tokenizer).
	x = "B" * max(0, L * 4)
	h, _lcp = hat_H(
		x_a=x,
		x_prev=cache.x_prev,
		L=L,
		action="C1",
		rho=rho_hat(cache, params),
		g=params.g,
	)
	u = max(float(L) - h, 0.0)
	prices = prices_for(cache, params)
	from memory.simulator.cost_model import Split

	spl = Split(H=h, U=u, W_phys=0.0, W_fill=float(L) - h, L=L, lcp=_lcp, rho=rho_hat(cache, params))
	return L, c_biz_yuan(spl, params.o_mean, prices)


def run_scenario(sc: Scenario, params: Params, *, forecast: str = "p0") -> SuiteRow:
	s0 = sc.state()
	cache = sc.cache(params)
	d = decide(
		s0,
		cache,
		remaining_turns=sc.remaining_turns,
		params=params,
		delta_text=sc.delta_text,
		forecast=forecast,
	)
	action = d.a_star if d.a_star in ("keep", "C1", "C2") else "keep"
	from memory.simulator.cost_model import shot_cost

	_s_a, shot = shot_cost(s0, action, cache, params, charge_action=True)
	b_tok, b_cost = _baseline_cost(sc.messages, cache, params)
	return SuiteRow(
		scenario_id=sc.id,
		kind=sc.kind,
		length_class=sc.length_class,
		a_star=d.a_star,
		a4=d.a4,
		a8=d.a8,
		a16=d.a16,
		hardtop=d.hardtop,
		G_beta=d.G_beta,
		L=shot.L,
		Q=shot.Q,
		D=shot.D,
		H=shot.H,
		cost=shot.c_biz + shot.c_action,
		baseline_tokens=b_tok,
		v61_tokens=shot.L,
		baseline_cost=b_cost,
		notes=sc.notes or ",".join(d.notes),
	)


def run_synthetic(params: Params | None = None, *, smoke: bool = False, forecast: str = "p0") -> list[SuiteRow]:
	p = params or load_params()
	return [run_scenario(sc, p, forecast=forecast) for sc in list_scenarios(smoke=smoke)]


def _ab_from_rows(rows: list[SuiteRow]) -> dict[str, Any]:
	base = [r.baseline_cost for r in rows]
	cand = [r.cost for r in rows]
	base_tok = [float(r.baseline_tokens) for r in rows]
	cand_tok = [float(r.v61_tokens) for r in rows]
	l4 = sum(1 for r in rows if r.a_star == "L4")
	n = max(len(rows), 1)
	base_sum = sum(base) or 1e-15
	savings = (sum(base) - sum(cand)) / base_sum
	# synthetic: success = not L4; correction unknown=0; tool-loop proxy = keep on kind F
	f_keep = sum(1 for r in rows if r.kind == "F" and r.a_star == "keep")
	f_n = sum(1 for r in rows if r.kind == "F") or 1
	return {
		"n": len(rows),
		"baseline_cost": summarize_values(base),
		"v6.1_cost": summarize_values(cand),
		"baseline_tokens": summarize_values(base_tok),
		"v6.1_tokens": summarize_values(cand_tok),
		"savings_frac": savings,
		"task_success_baseline": 1.0,
		"task_success_v61": 1.0 - l4 / n,
		"user_correction_baseline": 0.0,
		"user_correction_v61": 0.0,
		"tool_loop_v61": f_keep / f_n,
		"l4_rate": l4 / n,
		"verdict_ready": False,  # Phase 11 flag; caller sets after checks
	}


def ab_success(ab: dict[str, Any], *, cost_eps: float = 0.0) -> dict[str, Any]:
	"""Cost ↓ AND success ≈ baseline AND correction ≈ baseline AND loop not worse.

	Synthetic suites have no labeled corrections (both 0). Loop proxy is kind-F keep rate;
	baseline always C1 so loop proxy for baseline is 0. A keep-heavy F is not an auto-fail
	here — recorded, not a selector input.
	"""
	cost_ok = ab.get("savings_frac", 0) >= -cost_eps
	# require candidate cost <= baseline (savings >= 0) to claim cost ↓
	cost_down = ab.get("savings_frac", 0) > 0
	succ_b = ab.get("task_success_baseline", 1.0)
	succ_c = ab.get("task_success_v61", 1.0)
	succ_ok = abs(succ_c - succ_b) <= 0.01 or succ_c >= succ_b
	corr_ok = abs(ab.get("user_correction_v61", 0) - ab.get("user_correction_baseline", 0)) <= 0.01
	ok = cost_down and succ_ok and corr_ok
	reason = []
	if not cost_down:
		reason.append("cost_not_down")
	if not succ_ok:
		reason.append("success_drop")
	if not corr_ok:
		reason.append("correction_up")
	return {"passed": ok, "reasons": reason, "cost_ok": cost_ok}


def replay_quality(sessions: list[ReplaySession]) -> dict[str, Any]:
	if not sessions:
		return {
			"sessions": 0,
			"turns": 0,
			"corrections": 0,
			"reverts": 0,
			"loops": {},
			"task_success": "unknown",
		}
	turns = sum(len(s.turns) for s in sessions)
	corr = sum(s.corrections for s in sessions)
	rev = sum(s.reverts for s in sessions)
	loops = Counter()
	for s in sessions:
		for k, v in s.loops.items():
			loops[k] += v
	return {
		"sessions": len(sessions),
		"turns": turns,
		"corrections": corr,
		"reverts": rev,
		"correction_rate": corr / max(turns, 1),
		"loops": dict(loops),
		"task_success": "unknown",
	}


def build_report(
	*,
	params: Params | None = None,
	smoke: bool = False,
	sessions_dir: Path | None = None,
	hit_rows: list[HitRecord] | None = None,
	include_replay: bool = True,
	forecast: str = "p0",
) -> dict[str, Any]:
	p = params or load_params()
	rows = run_synthetic(p, smoke=smoke, forecast=forecast)
	counts = ActionCounts()
	for r in rows:
		scene = f"{r.length_class}:{r.kind}"
		counts.add(
			r.a_star,
			hardtop=r.hardtop,
			scene=scene,
			a4=r.a4,
			a8=r.a8,
			a16=r.a16,
			vote=r.a_star,
		)
	ab = _ab_from_rows(rows)
	ab["gate"] = ab_success(ab)
	hits = hit_rows or []
	cache = cache_errors(hits) if hits else {"n": 0, "MAE": None, "Bias": None, "MAPE": None}
	replay_sessions = replay_all(sessions_dir, p) if include_replay else []
	rq = replay_quality(replay_sessions)
	turns = [t for s in replay_sessions for t in s.turns]
	return {
		"title": "P2 Calibration Report",
		"generated_at": datetime.now(timezone.utc).isoformat(),
		"params": params_dict(p),
		"dataset": {
			"synthetic_scenarios": len(rows),
			"sessions": rq["sessions"],
			"turns": rq["turns"],
			"tool_calls": rq.get("loops", {}).get("read_calls", 0)
			+ rq.get("loops", {}).get("grep_calls", 0),
		},
		"cache_prediction": cache,
		"cache_by_bucket": cache_errors_by_bucket(hits) if hits else {},
		"cache_bias_flags": bias_flags(hits) if hits else [],
		"action_distribution": counts.as_dict(),
		"quality_invariants": {
			"Q_range": [min((r.Q for r in rows), default=0), max((r.Q for r in rows), default=1)],
			"D_negative": sum(1 for r in rows if r.D < -1e-12),
			"monotonicity_failures": "see unit tests",
		},
		"determinism": "see tests/simulator/test_determinism.py",
		"business": {
			"baseline_cost": ab["baseline_cost"],
			"v6.1_cost": ab["v6.1_cost"],
			"savings_frac": ab["savings_frac"],
		},
		"task_quality": {
			"baseline_success": ab["task_success_baseline"],
			"v6.1_success": ab["task_success_v61"],
			"replay_success": rq["task_success"],
		},
		"user_correction": {
			"baseline": ab["user_correction_baseline"],
			"v6.1": ab["user_correction_v61"],
			"replay_corrections": rq["corrections"],
			"replay_correction_rate": rq.get("correction_rate"),
		},
		"tool_loop": {
			"v6.1_kind_F_keep_rate": ab["tool_loop_v61"],
			"replay": rq.get("loops"),
		},
		"compact": compact_stats(rows),
		"ab_gate": ab["gate"],
		"rows": [asdict(r) for r in rows],
		"note": "Do not declare cost-optimization success before Phase 11. Overlay-only calibration.",
	}


def render_markdown(report: dict[str, Any]) -> str:
	ds = report["dataset"]
	cache = report["cache_prediction"]
	ad = report["action_distribution"]
	biz = report["business"]
	tq = report["task_quality"]
	uc = report["user_correction"]
	tl = report["tool_loop"]
	qi = report["quality_invariants"]
	gate = report["ab_gate"]
	lines = [
		"# P2 Calibration Report",
		"",
		f"Generated: {report['generated_at']}",
		"",
		"## Dataset",
		"",
		f"- sessions: {ds['sessions']}",
		f"- turns: {ds['turns']}",
		f"- tool calls: {ds['tool_calls']}",
		f"- synthetic scenarios: {ds['synthetic_scenarios']}",
		"",
		"## Cache prediction",
		"",
		f"- MAE: {cache.get('MAE')}",
		f"- Bias: {cache.get('Bias')}",
		f"- MAPE: {cache.get('MAPE')}",
		f"- n: {cache.get('n')}",
		"",
		"## Action distribution",
		"",
		f"- keep: {ad['keep_count']}",
		f"- C1: {ad['C1_count']}",
		f"- C2: {ad['C2_count']}",
		f"- HardTop: {ad['hardtop_count']}",
		f"- anomalies: {ad.get('anomalies')}",
		"",
		"## Quality invariants",
		"",
		f"- Q range: {qi['Q_range']}",
		f"- D negative: {qi['D_negative']}",
		f"- monotonicity failures: {qi['monotonicity_failures']}",
		"",
		"## Determinism",
		"",
		f"- {report['determinism']}",
		"",
		"## Business",
		"",
		f"- baseline cost: {biz['baseline_cost']}",
		f"- v6.1 cost: {biz['v6.1_cost']}",
		f"- savings: {biz['savings_frac']}",
		"",
		"## Task quality",
		"",
		f"- baseline success: {tq['baseline_success']}",
		f"- v6.1 success: {tq['v6.1_success']}",
		"",
		"## User correction",
		"",
		f"- baseline: {uc['baseline']}",
		f"- v6.1: {uc['v6.1']}",
		f"- replay corrections: {uc['replay_corrections']}",
		"",
		"## Tool loop",
		"",
		f"- v6.1: {tl}",
		"",
		"## Phase 11 gate",
		"",
		f"- passed: {gate.get('passed')}",
		f"- reasons: {gate.get('reasons')}",
		"",
		report.get("note", ""),
		"",
	]
	return "\n".join(lines)


def write_report(report: dict[str, Any], out_dir: Path | None = None) -> tuple[Path, Path]:
	d = out_dir or OUT_DIR
	d.mkdir(parents=True, exist_ok=True)
	jp = d / "p2_report.json"
	mp = d / "p2_report.md"
	jp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	mp.write_text(render_markdown(report), encoding="utf-8")
	return jp, mp
