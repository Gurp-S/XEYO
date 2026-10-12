"""Read-only counterfactual mutation audit of an actual committed checkpoint.

No API calls or writes to the selected session; this tests rejection, not
model interpretation or execution following compaction.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from memory.wsc_handoff_fact_disposition import basis, validate
from memory.wsc_handoff_bindings import validate as validate_context_bindings
from session.record_transcript import load_transcript
from session.transcript_blobs import resolve_transcript_rows
from synaptic.todo_snapshot import latest_todo_snapshot


def run(session, output):
    before = session.read_bytes()
    rows = resolve_transcript_rows(load_transcript(session), session)
    snapshot = latest_todo_snapshot(rows)
    prior = basis(rows)
    if prior is None:
        raise ValueError("audit_explicit_task_facts_missing")
    raw = {"todos": deepcopy(list(snapshot.records)), "checkpoint": deepcopy(snapshot.checkpoint)}
    validate(raw, rows)
    checks = []
    for field in ("decisions", "constraints"):
        scopes = raw["checkpoint"]["phase_state"]["fact_scopes"][field]
        for i, scope in enumerate(scopes):
            if scope["kind"] != "task": continue
            for mutation in ("omit", "demote", "shorten"):
                candidate = deepcopy(raw)
                cp = candidate["checkpoint"]
                if mutation == "omit":
                    cp[field].pop(i)
                    cp["phase_state"]["fact_scopes"][field].pop(i)
                elif mutation == "demote":
                    cp["phase_state"]["fact_scopes"][field][i] = {
                        "kind": "phase", "phase_id": cp["phase_state"]["current_phase_id"]}
                else:
                    fact = cp[field][i]
                    if isinstance(fact, str): cp[field][i] = fact[:-1]
                    else: fact["quote"] = fact["quote"][:-1]
                error = None
                binding_error = None
                try: validate_context_bindings(candidate, rows)
                except ValueError as exc: binding_error = str(exc)
                try: validate(candidate, rows)
                except ValueError as exc: error = str(exc)
                checks.append({"field": field, "index": i, "mutation": mutation,
                    "context_ids_unchanged": cp["context_message_ids"] == raw["checkpoint"]["context_message_ids"],
                    "context_binding_check_passed": binding_error is None,
                    "error": error, "rejected": error == "handoff_task_fact_disposition_missing"})
    report = {"session": str(session.resolve()), "source_sha256": hashlib.sha256(before).hexdigest(),
        "source_unchanged": session.read_bytes() == before, "baseline_retained": True,
        "task_fact_count": len(prior["task_facts"]), "checks": checks,
        "rejections": sum(c["rejected"] for c in checks), "api_calls": 0,
        "scope": __doc__}
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.session, args.output)
    print(json.dumps({k: report[k] for k in ("task_fact_count", "rejections", "source_unchanged", "api_calls")}))
