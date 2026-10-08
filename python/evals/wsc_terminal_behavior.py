"""Controlled fork at an actual committed terminal receipt, no new request."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evals.wsc_execution_behavior import run_arm, digest
from evals.wsc_request_projection import arm


def run(source, output, max_turns=6):
    from evals.client import MODEL_ID
    from memory import wsc_projection as live
    source, output = Path(source).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    seals = {name: digest(source / name) for name in ("trace.json", "payment.py", "report.json", "verify.py", "legacy.txt")}
    report = {"scope": "controlled fork of actual previously executed terminal receipt; identical source; no new human request",
        "model": MODEL_ID, "arms": {}, "compression_model_calls": 0}
    saved = {key: os.environ.get(key) for key in ("XEYO_WSC_TASK_CONTINUITY", "XEYO_WSC_FAILURE_FACTS")}
    try:
        os.environ["XEYO_WSC_FAILURE_FACTS"] = "1"
        for label in ("before", "after"):
            live._STATE.clear()
            with ExitStack() as stack:
                stack.enter_context(arm("1", output / label / "home"))
                if label == "before":
                    stack.enter_context(patch("synaptic.task_terminal.project", return_value=(None, ())))
                    stack.enter_context(patch("memory.wsc_execution_boundary.protect", side_effect=lambda messages, requested: requested))
                result = run_arm(output / label / "task", "1", model=MODEL_ID, max_turns=max_turns, resume_source=source)
            report["arms"][label] = result
            # Resumption tests already committed completion, not the earlier
            # edit phase. Do not score the ability to generate that commit.
            result["closure_acceptance"] = {key: value for key, value in result["acceptance"].items()
                if key not in {"cold_restart_exercised", "repeated_fold_exercised"}}
            result["closure_acceptance"]["no_post_commit_payment_edits"] = not any(
                item["name"] in {"Edit", "Write"} and item["arguments"].get("file_path") == "payment.py"
                for item in result["calls"])
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"arm": label, "closure_acceptance": result["closure_acceptance"]}), flush=True)
        report["source_files_unchanged"] = seals == {name: digest(source / name) for name in seals}
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-turns", type=int, default=6)
    args = parser.parse_args()
    run(args.source, args.output, args.max_turns)
