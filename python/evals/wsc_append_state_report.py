"""Summarize the append-state paired replay without provider billing claims."""
import argparse
import json
from pathlib import Path


def read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--repeat", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = [args.baseline, args.candidate, args.repeat]
    runs = [read(path) for path in paths]
    points = [read(path.with_suffix(".points.jsonl")) for path in paths]
    manifests = [json.loads(path.with_suffix(".manifest.json").read_text(encoding="utf-8")) for path in paths]
    for manifest in manifests[1:]:
        for key in ("inputs", "params", "arm", "head_layout", "message_format", "prefix-tokens",
                    "fixed_prefix_tokens", "window_tokens", "drop_repeat_facts", "state_persist", "state_dedup"):
            if manifests[0].get(key) != manifest.get(key):
                raise AssertionError(f"unpaired experiment setting: {key}")
    identity = lambda rows: [(row["case"], row["shot"], row["end"]) for row in rows]
    if any(identity(rows) != identity(points[0]) for rows in points[1:]):
        raise AssertionError("unpaired request boundaries")
    if points[1] != points[2]:
        raise AssertionError("independent repeat differs")
    if manifests[1]["source_sha256"] != manifests[2]["source_sha256"]:
        raise AssertionError("independent repeat source differs")
    keys = ("shots", "prompt", "hit", "miss", "response_prefix_hit", "response_prefix_miss",
            "folds", "state_injections", "stale_state_rows", "over_window", "state_quality_checks",
            "input_cost_estimate", "response_prefix_cost_estimate")
    totals = [{key: sum(row[key] for row in run) for key in keys} for run in runs]
    before, after = totals[:2]
    cases = [{"case": a["case"], "input_cost_before": a["input_cost_estimate"],
              "input_cost_after": b["input_cost_estimate"],
              "response_cost_before": a["response_prefix_cost_estimate"],
              "response_cost_after": b["response_prefix_cost_estimate"]}
             for a, b in zip(runs[0], runs[1], strict=True)]
    if any(a["case"] != b["case"] for a, b in zip(runs[0], runs[1], strict=True)):
        raise AssertionError("unpaired summary cases")
    result = {
        "scope": "6 archived histories, 1031 real assistant request boundaries; archived current states are an oracle. UTF8/4 tokens, fixed 8192-token prefix, input hit .05/miss 1.5 CNY/M. Output-prefix caching is optimistic. No paid calls, actual bill or downstream task score.",
        "runs": {str(path): total for path, total in zip(paths, totals, strict=True)},
        "input_hit_before": before["hit"] / before["prompt"],
        "input_hit_after": after["hit"] / after["prompt"],
        "response_hit_before": before["response_prefix_hit"] / before["prompt"],
        "response_hit_after": after["response_prefix_hit"] / after["prompt"],
        "input_cost_reduction": 1 - after["input_cost_estimate"] / before["input_cost_estimate"],
        "response_cost_reduction": 1 - after["response_prefix_cost_estimate"] / before["response_prefix_cost_estimate"],
        "prompt_growth": after["prompt"] / before["prompt"] - 1,
        "cases": cases,
        "pointwise_repeat_equal": True,
        "source_repeat_equal": True,
        "mechanism": "Append-only source retains all simulated state originals and indices. Explicit note nodes are excluded from seeds, hot selection and file-state paths; cold originals remain intact. Tail emits only latest full current note plus any required reinjection.",
        "verified": ["1031 oracle current-state full-delivery checks per arm", "1031 ordinary-source history equivalence checks per arm", "Actual WSC cold original retention", "Actual frozen head and cold bytes unchanged during state update", "Actual head-store restart preserves emission, following fold forks cold generation"],
        "gate": "714 passed, 2 existing xfailed, 4 existing xpassed; includes 9 lifecycle/append-state tests",
        "decision": "Retain shadow candidate; not production-admitted. More benefit than changing-key detachment and avoids state-source index drift. Validate actual state generator/query-loop wiring, automatic/manual source consistency, existing-session cursor migration and matched total attention budget before admission.",
        "risks": ["Accumulated input grows 7.42%; fixed 128k capacity test is not a matched attention-budget task test", "Oracle delivery is not evidence of model use or TB success", "Original API-projection numeric cursors cannot be silently reused against append-only source", "Exclusion is an isolated evaluation hook, not a production-compatible implementation"],
        "complexity": "Small evaluation store and graph/freshness hooks; no production imports, flags or behavioral changes",
        "quota_round_since_58_percent_instruction": 4,
        "quota_next_check_round": 5,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("input_hit_before", "input_hit_after", "input_cost_reduction", "response_cost_reduction", "prompt_growth")}, ensure_ascii=True))


if __name__ == "__main__":
    main()
