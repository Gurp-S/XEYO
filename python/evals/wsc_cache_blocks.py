"""Hypothetical block-rounded cache sensitivity, never a vendor usage meter."""
import argparse
import hashlib
import json
from pathlib import Path

from evals.wsc_cache_price_sensitivity import analyze, load_points


def rounded_points(rows, *, block, minimum):
    if type(block) is not int or block < 1 or type(minimum) is not int or minimum < 0:
        raise ValueError("invalid cache block scenario")
    result = []
    for row in rows:
        hit = row["hit"] // block * block
        if hit < minimum:
            hit = 0
        result.append({**row, "hit": hit, "miss": row["prompt"] - hit})
    return result


def run(baseline, candidate):
    scenarios = []
    for block in (1, 128, 256, 1024):
        for minimum in (0, 1024, 4096):
            a = rounded_points(baseline, block=block, minimum=minimum)
            b = rounded_points(candidate, block=block, minimum=minimum)
            report = analyze(a, b)
            scenarios.append(dict(block_tokens=block, minimum_prefix_tokens=minimum,
                                  baseline_hit_pct=100*sum(r["hit"] for r in a)/sum(r["prompt"] for r in a),
                                  candidate_hit_pct=100*sum(r["hit"] for r in b)/sum(r["prompt"] for r in b),
                                  baseline_additional_miss=sum(r["miss"]-s["miss"] for r,s in zip(a,baseline)),
                                  candidate_additional_miss=sum(r["miss"]-s["miss"] for r,s in zip(b,candidate)),
                                  price_scenarios=[r for r in report["matrix"] if r["predicted_prefix_realization"] == 1],
                                  aggregate_ratio_interval=report["aggregate_interval"]))
    return dict(points=len(baseline), scenarios=scenarios)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(load_points(args.baseline), load_points(args.candidate))
    report["scope"] = "Fixed UTF8/4 estimated token sequences, hypothetical block rounding and thresholds; no assertion of current vendor block size, tokenizer, retention, output caching, real bills or task scores. Historical missing system/tools replaced by fixed8192-token prefix. No new projections or fold decisions."
    report["sha256"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                        (args.baseline, args.candidate, Path(__file__))}
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(dict(points=report["points"], scenarios=len(report["scenarios"]))))


if __name__ == "__main__":
    main()
