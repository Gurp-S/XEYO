"""Check whether an append-only raw state source is safe without emission changes.

Synthetic mechanism probe only; no model calls or claimed billing benefit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from synaptic.freshness import analyze
from synaptic.project import project
from synaptic.types import WscParams


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [
        {"role": "user", "content": "Inspect current workspace"},
        {"role": "user", "content": "<environment_context>cwd=D:/old</environment_context>"},
        {"role": "assistant", "content": "observed workspace"},
        {"role": "user", "content": "<environment_context>cwd=D:/new</environment_context>"},
    ]
    params = replace(WscParams(), journal_layout=False, freeze_main_chain=False,
                     handle_style="expand")
    result = project(rows, region_end=len(rows), params=params)
    freshness = analyze(result.graph, region_end=len(rows))
    kept = [row["idx"] for row in result.audit if row["kept"]]
    evidence = {
        "scope": "Synthetic fresh-fold mechanism probe; not current-state lifecycle, task quality or provider cost measurement",
        "inputs": rows,
        "params": vars(params),
        "injected_nodes": freshness.injected_nodes,
        "superseded": sorted(freshness.superseded),
        "kept": kept,
        "old_state_emitted": rows[1]["content"] in result.text,
        "current_state_emitted": rows[3]["content"] in result.text,
        "head": result.text,
        "decision": "Reject raw-history switch alone: seed exclusion does not exclude old machine state from MAIN. Explicit note identity/revision emission rules and tail handling need validation before any source-coordinate change.",
        "source_sha256": {
            name: hashlib.sha256((Path(__file__).resolve().parents[1] / name).read_bytes()).hexdigest()
            for name in ("evals/wsc_raw_state_probe.py", "synaptic/project.py", "synaptic/freshness.py", "synaptic/closure.py", "synaptic/seeds.py")
        },
    }
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: evidence[key] for key in ("injected_nodes", "kept", "old_state_emitted", "current_state_emitted")}, ensure_ascii=True))


if __name__ == "__main__":
    main()
