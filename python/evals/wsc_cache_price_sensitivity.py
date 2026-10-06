"""Reprice paired archived requests without provider calls or price assumptions.

Realization scales predicted reusable prefix tokens, not observed provider hit
rate. At zero realization every input token is full price. This is sensitivity
analysis of fixed projections; it does not rerun price-dependent fold decisions.
"""
import argparse
import hashlib
import json
from pathlib import Path


def load_points(path):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        if any(type(row.get(key)) is not int or row[key] < 0 for key in ("prompt", "hit", "miss")):
            raise ValueError("invalid token accounting")
        if row["prompt"] != row["hit"] + row["miss"]:
            raise ValueError("input tokens not conserved")
    return rows


def admissible_interval(delta_prompt, delta_hit, realization=1):
    # delta cost = R * delta_prompt - realization * (R-1) * delta_hit.
    # Normalize hit unit price to 1 and restrict miss/hit R >= 1.
    slope = delta_prompt - realization * delta_hit
    constant = realization * delta_hit
    if slope == 0:
        return [1, None] if constant <= 0 else None
    bound = -constant / slope
    if slope < 0:
        return [max(1, bound), None]
    return [1, bound] if bound >= 1 else None


def normalized_cost(row, ratio, realization):
    return ratio * row["prompt"] - realization * (ratio - 1) * row["hit"]


def analyze(baseline, candidate):
    identity = lambda row: (row["case"], row["shot"], row["end"])
    if not baseline or [identity(r) for r in baseline] != [identity(r) for r in candidate]:
        raise ValueError("request pairing mismatch")
    cases = {}
    for a, b in zip(baseline, candidate):
        pair = cases.setdefault(a["case"], [dict(prompt=0, hit=0), dict(prompt=0, hit=0)])
        for total, row in zip(pair, (a, b)):
            for key in total:
                total[key] += row[key]
    intervals = []
    for name, (a, b) in cases.items():
        dn, dh = b["prompt"] - a["prompt"], b["hit"] - a["hit"]
        intervals.append(dict(case=name, delta_prompt=dn, delta_hit=dh, delta_miss=dn-dh,
                              non_increasing_cost_ratio_interval=admissible_interval(dn, dh)))
    sums = [dict(prompt=sum(pair[i]["prompt"] for pair in cases.values()),
                 hit=sum(pair[i]["hit"] for pair in cases.values())) for i in (0, 1)]
    matrix = []
    for ratio in (1, 2, 4, 8, 10, 20, 30, 50, 100):
        for realization in (0, .8, .9, .95, 1):
            per_case = []
            for name, (a, b) in cases.items():
                ca, cb = normalized_cost(a, ratio, realization), normalized_cost(b, ratio, realization)
                per_case.append(dict(case=name, saving_pct=100*(1-cb/ca)))
            ca, cb = (normalized_cost(v, ratio, realization) for v in sums)
            matrix.append(dict(miss_hit_price_ratio=ratio, predicted_prefix_realization=realization,
                               aggregate_saving_pct=100*(1-cb/ca),
                               worst_case_saving_pct=min(p["saving_pct"] for p in per_case),
                               cases_cost_increased=[p["case"] for p in per_case if p["saving_pct"] < -1e-10],
                               per_case=per_case))
    return dict(points=len(baseline), cases=len(cases), per_case_intervals=intervals,
                aggregate_interval=admissible_interval(sums[1]["prompt"]-sums[0]["prompt"],
                                                       sums[1]["hit"]-sums[0]["hit"]), matrix=matrix)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = analyze(load_points(args.baseline), load_points(args.candidate))
    report["scope"] = "Fixed paired projections, UTF8/4 tokens and historical fixed prefix; input only, normalized hit unit price. Synthetic price ratios are not current vendor prices. Prefix realization is fraction of predicted LCP admitted as cached, not observed hit percentage. No paid bill, model task-score or price-dependent fold-policy optimality claim."
    report["sha256"] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in (args.baseline, args.candidate, Path(__file__))}
    args.output.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(points=report["points"], cases=report["cases"],
                          aggregate_interval=report["aggregate_interval"],
                          intervals=report["per_case_intervals"])))


if __name__ == "__main__":
    main()
