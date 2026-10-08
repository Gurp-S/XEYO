"""Paired execution of card surfaces with equal explicit checkpoint support."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

from evals.wsc_execution_behavior import run_arm, seed, event
from evals.wsc_request_projection import arm
from synaptic.card_surface import ENV


def seed_archive(root):
    rows, records = seed(root)
    archive = []
    for index in range(18):
        archive += event(f"archive-{index}", "Bash", {"command": f"old_fixture_{index}"},
            {"content": "Archived synthetic load. " + "archive " * 1200, "is_error": False})
    return rows[:1] + archive + rows[1:], records


def run(output, max_turns=12):
    from evals.client import MODEL_ID
    from memory.wsc_projection import production_params
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    previous = {key: os.environ.get(key) for key in (ENV, "XEYO_WSC_TASK_CONTINUITY", "XEYO_WSC_FAILURE_FACTS")}
    report = {"scope": "paired card display only, explicit checkpoint in both arms; synthetic archived branches and arithmetic fixture, real resumed tools/model; constrained main budget and forced folds, not historical wire",
        "model": MODEL_ID, "main_segment_budget_tokens": 100, "arms": {}}
    try:
        os.environ["XEYO_WSC_FAILURE_FACTS"] = "1"
        for label, flag in (("cards", "0"), ("index", "1")):
            os.environ[ENV] = flag
            with arm("1", output / label / "home"), patch("evals.wsc_execution_behavior.seed", side_effect=seed_archive), \
                patch("memory.wsc_projection.production_params", side_effect=lambda: replace(production_params(), main_segment_budget_tokens=100)):
                sample = run_arm(output / label / "task", "1", model=MODEL_ID, max_turns=max_turns)
                wires = json.loads((output / label / "task/wire.json").read_text(encoding="utf-8"))
                sample["surface_observation"] = {"indexed_requests": sum("历史折叠来源索引" in json.dumps(wire["request"]["messages"], ensure_ascii=False) for wire in wires),
                    "requests": len(wires)}
                report["arms"][label] = sample
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"arm": label, "acceptance": sample["acceptance"], "surface": sample["surface_observation"]}), flush=True)
        return report
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-turns", type=int, default=12)
    args = parser.parse_args()
    result = run(args.output, args.max_turns)
    sample = result["arms"]["index"]
    sys.exit(0 if all(sample["acceptance"].values()) and sample["surface_observation"]["indexed_requests"] else 1)
