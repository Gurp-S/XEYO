"""Offline same-source replay of an actual generated handoff; no API calls."""
import argparse
from dataclasses import fields
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from evals.wsc_unfolded_source_ab import environment
from memory.working import WorkingSnapshot
from memory.wsc_projection import production_params
from msgtypes.message import Message
from session.compression_source import compression_messages
from session.message_store import MessageStore
from synaptic.graph import build_graph
from synaptic.project import project
from synaptic.task_checkpoint import project_state


def run(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    captured = source.read_bytes()
    output.mkdir(parents=True, exist_ok=False)
    names = {field.name for field in fields(Message)}
    native = [json.loads(line) for line in captured.decode("utf-8").splitlines() if line.strip()]
    store = MessageStore([Message(**{key: value for key, value in row.items() if key in names}) for row in native])
    rows = compression_messages(store, WorkingSnapshot(session_id="offline-fact-replay"))
    # Final text response is not a source available to the compaction boundary.
    while rows and not (rows[-1].get("role") == "tool" and rows[-1].get("name") == "TodoWrite"):
        rows.pop()
    if not rows:
        raise ValueError("no_final_committed_handoff")
    arms = {}
    with environment(output):
        for label in ("before", "after"):
            root = output / label
            root.mkdir()
            def capture():
                state, nodes = project_state(rows, build_graph(rows))
                projection = project(rows, region_end=max(0, len(rows) - 6),
                                     params=production_params(), view_path=root / "cold.txt")
                (root / "head.txt").write_text(projection.text, encoding="utf-8")
                return {"state": state, "nodes": nodes, "head_bytes": len(projection.text.encode("utf-8")),
                        "cold_sha256": hashlib.sha256(Path(projection.view_path).read_bytes()).hexdigest()}
            if label == "before":
                # Reproduce the previous not_text branch while preserving the
                # identical real generated declaration and deterministic WSC.
                with patch("synaptic.task_fact_sources.resolve", return_value=None):
                    arms[label] = capture()
            else:
                arms[label] = capture()
    before, after = arms["before"]["state"], arms["after"]["state"]
    checks = {"source_bytes_unchanged": captured == source.read_bytes(),
              "unknown_source_before": bool(before["unknown_sources"]),
              "unknown_source_resolved": not after["unknown_sources"],
              "committed_slot_located": bool(after.get("committed_fact_sources")),
              "same_declared_facts": all(before[field] == after[field] for field in
                  ("declared_objective", "declared_decisions", "declared_constraints", "items", "verification_receipts"))}
    report = {"scope": "offline rebuild from actual Flash Compact/handoff transcript; old resolver negative control, no new model behavior claim",
              "source_sha256": hashlib.sha256(captured).hexdigest(), "rows": len(rows), "checks": checks, "arms": arms,
              "api_requests": 0}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"checks": checks, "head_bytes": {name: arm["head_bytes"] for name, arm in arms.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.source, args.output)
