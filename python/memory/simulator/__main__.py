"""CLI: python -m memory.simulator <unit|scenarios|determinism|replay|probe|calibrate|report|ab>"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from memory.simulator.params import load_params, overlay_path


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(prog="memory.simulator", description="XEYO Memory P2 v6.1 simulator")
	sub = parser.add_subparsers(dest="cmd", required=True)

	sub.add_parser("unit", help="run pytest tests/simulator (no live)")
	p_sc = sub.add_parser("scenarios", help="run synthetic matrix")
	p_sc.add_argument("--smoke", action="store_true")
	p_sc.add_argument("--forecast", default="p0", choices=("p0", "p1"))
	sub.add_parser("determinism", help="run determinism tests")
	p_rp = sub.add_parser("replay", help="replay ~/.xeyo/sessions JSONL")
	p_rp.add_argument("--sessions-dir", default=None)
	p_pr = sub.add_parser("probe", help="live DeepSeek Ĥ vs prompt_cache_hit_tokens")
	p_pr.add_argument("--live", action="store_true")
	p_pr.add_argument("--idle", type=float, default=60.0, help="seconds to wait for a second pair (TTL sample)")
	p_cal = sub.add_parser("calibrate", help="scan one param; write overlay")
	p_cal.add_argument(
		"--param",
		required=True,
		choices=(
			"rho", "kappa", "theta", "tau_switch",
			"alpha_win", "beta", "t_k", "r_cap", "lambda_q",
		),
	)
	p_cal.add_argument("--write", action="store_true", help="write best value to overlay")
	p_cal.add_argument("--hits", default=None, help="probe_hits.json for rho")
	p_rep = sub.add_parser("report", help="write P2 Calibration Report")
	p_rep.add_argument("--smoke", action="store_true")
	p_rep.add_argument("--no-replay", action="store_true")
	p_ab = sub.add_parser("ab", help="baseline vs v6.1 on synthetic matrix")
	p_ab.add_argument("--smoke", action="store_true")

	args = parser.parse_args(argv)
	if args.cmd == "unit":
		return _pytest(["tests/simulator", "-q", "-m", "not live"])
	if args.cmd == "determinism":
		return _pytest(["tests/simulator/test_determinism.py", "-q"])
	if args.cmd == "scenarios":
		from memory.simulator.report import run_synthetic

		rows = run_synthetic(load_params(), smoke=args.smoke, forecast=args.forecast)
		from collections import Counter

		c = Counter(r.a_star for r in rows)
		print(json.dumps({"n": len(rows), "actions": dict(c)}, ensure_ascii=False, indent=2))
		return 0
	if args.cmd == "replay":
		from memory.simulator.replay import replay_all

		root = Path(args.sessions_dir) if args.sessions_dir else None
		sessions = replay_all(root, load_params())
		print(
			json.dumps(
				{
					"sessions": len(sessions),
					"turns": sum(len(s.turns) for s in sessions),
					"files": [s.session for s in sessions],
				},
				ensure_ascii=False,
				indent=2,
			)
		)
		return 0
	if args.cmd == "probe":
		if not args.live:
			print("refusing: pass --live to hit DeepSeek")
			return 2
		return _run_probe(idle=args.idle)
	if args.cmd == "calibrate":
		return _run_calibrate(args.param, args.write, hits_file=args.hits)
	if args.cmd == "report":
		from memory.simulator.report import build_report, write_report

		rep = build_report(
			smoke=args.smoke,
			include_replay=not args.no_replay,
		)
		jp, mp = write_report(rep)
		print(jp)
		print(mp)
		return 0
	if args.cmd == "ab":
		from memory.simulator.report import ab_success, build_report

		rep = build_report(smoke=args.smoke, include_replay=False)
		print(json.dumps({"business": rep["business"], "gate": rep["ab_gate"]}, indent=2))
		return 0 if rep["ab_gate"]["passed"] else 1
	return 2


def _pytest(args: list[str]) -> int:
	import pytest

	root = Path(__file__).resolve().parents[2]
	return int(pytest.main([str(root / a) if a.startswith("tests/") else a for a in args]))


def _run_probe(*, idle: float) -> int:
	import asyncio

	from memory.simulator.metrics import cache_errors, cache_errors_by_bucket
	from memory.simulator.probe import have_api_key, probe_keep_pair, save_hits

	if not have_api_key():
		print("missing DEEPSEEK_API_KEY")
		return 2

	prefix = "XEYO P2 cache probe. " + ("填充上下文。" * 180)

	async def _go():
		rows = []
		rows.extend(await probe_keep_pair(prefix, idle_seconds=0.0, label="continuous"))
		if idle and idle > 0:
			rows.extend(await probe_keep_pair(prefix + " TTL", idle_seconds=idle, label=f"idle_{idle}"))
		return rows

	rows = asyncio.run(_go())
	path = save_hits(rows)
	err = cache_errors(rows)
	print(json.dumps({
		"saved": str(path),
		"n": len(rows),
		"errors": err,
		"buckets": cache_errors_by_bucket(rows),
		"rows": [r.__dict__ for r in rows],
	}, ensure_ascii=False, indent=2, default=str))
	return 0 if rows else 1


def _run_calibrate(param: str, write: bool, hits_file: str | None = None) -> int:
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
	from memory.simulator.probe import load_hits

	p = load_params()
	if param == "rho":
		rows = load_hits(Path(hits_file) if hits_file else None)
		if not rows:
			# 热路径逐枪观测优先：无 probe_hits.json 时用 calibration_events.jsonl
			rows = hit_records_from_events()
		# second shot of a pair carries the ρ signal
		fit = [r for r in rows if r.conversation_length >= 2] or rows
		points = scan_rho(fit, p)
		payload = [{"value": x.value, "metrics": x.metrics} for x in points]
		print(json.dumps({"n_hits": len(fit), "scan": payload}, indent=2))
		if write and fit:
			best = best_rho(points)
			path = apply_overlay("rho", best)
			print(f"wrote alpha_hit={best} -> {path}")
		elif not fit:
			print("no probe hits; run: python -m memory.simulator probe --live")
			return 2
		else:
			print(f"overlay not written (pass --write). current file: {overlay_path()}")
		return 0
	fn = {
		"kappa": scan_kappa,
		"theta": scan_theta,
		"tau_switch": scan_tau,
		"alpha_win": scan_alpha_win,
		"beta": scan_beta,
		"t_k": scan_t_k,
		"r_cap": scan_r_cap,
		"lambda_q": scan_lambda_q,
	}[param]
	points = fn(p)
	payload = [{"value": x.value, "metrics": x.metrics} for x in points]
	print(json.dumps(payload, indent=2))
	if write and points:
		best = max(points, key=lambda x: (x.metrics.get("success_proxy", 0), -abs(x.metrics.get("C2_rate", 0) - 0.1)))
		path = apply_overlay(param, best.value)
		print(f"wrote {param}={best.value} -> {path}")
	else:
		print(f"overlay not written (pass --write). current file: {overlay_path()}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
