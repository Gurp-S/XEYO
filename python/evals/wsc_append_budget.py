"""Same-budget, same ordinary-tail fresh-fold check for state-source changes.

This checks deterministic protected facts and recoverability, not model task
success or multi-turn caching economics. Historical states are taken from logs.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import runpy

from session.compression_source import SourceReader
from memory.wsc_source_layout import APPEND
from evals.wsc_extension_economics_ab import without_repeat_facts, canonical_projection
from session.hydrate import message_from_row
from session.message_store import MessageStore


def boundary(source, ordinary_count):
    seen = 0
    for i, row in enumerate(source):
        if row.get("note_key"):
            continue
        if seen == ordinary_count:
            return i
        seen += 1
    return len(source)


def protected(projection):
    seeds = projection.seeds
    return {"original_task": [seeds.original_task] if seeds.original_task else [],
            "constraints": list(seeds.constraints), "errors": list(seeds.unresolved_errors),
            "todos": list(seeds.todos)}


def matched_pair(raw, *, cwd, budget=3000, head_cap=6000):
    from memory.runtime import c2_cut_index
    from memory.wsc_projection import production_params
    from synaptic.project import project
    from synaptic.graph import build_graph
    from synaptic.textutil import node_token_len

    items = [m for row in raw if (m := message_from_row(row)) is not None]
    store = MessageStore(items)
    baseline = store.as_api_messages()
    sources = [baseline, SourceReader().read(store, APPEND)]
    count = sum(not row.get("note_key") for row in baseline[:c2_cut_index(baseline, None)])
    cuts = [boundary(source, count) for source in sources]
    ordinary_tails = [[row for row in source[cut:] if not row.get("note_key")]
                      for source, cut in zip(sources, cuts)]
    assert ordinary_tails[0] == ordinary_tails[1]
    # Both sides receive the same authoritative state snapshot outside the head.
    state = [row for row in baseline if row.get("note_key")]
    common_tail = ordinary_tails[0] + state
    tail_tokens = node_token_len(canonical_projection(common_tail, "openai"))
    base = production_params()
    params = replace(base, journal_layout=False, freeze_main_chain=False,
                     freeze_working_set=False, hot_budget_tokens=budget,
                     fixed_segment_budget_tokens=budget * 2 // 5,
                     main_segment_budget_tokens=budget - budget * 2 // 5)
    ordinary = [row for row in sources[0] if not row.get("note_key")]
    # Independent ordinary-message facts; note-derived facts are not human constraints.
    reference = project(ordinary, region_end=count, params=params, persist_view=False)
    gold = protected(reference)
    result = []
    for arm, (source, cut) in enumerate(zip(sources, cuts)):
        view = cwd / ("a" if arm == 0 else "b") / "cold.txt"
        out = project(source, region_end=cut, params=params, view_path=view,
                      view_ref="WSC/cold.txt", persist_view=False, exclude_state_notes=bool(arm))
        facts = protected(out)
        missing = {key: [value for value in values if value not in facts[key]]
                   for key, values in gold.items()}
        ordinary_nodes = [node for node, row in zip(out.graph.nodes, source)
                          if node.idx < cut and not row.get("note_key")]
        oracle_nodes = build_graph(ordinary[:count]).nodes
        assert [node.text for node in ordinary_nodes] == [node.text for node in oracle_nodes]
        body = " ".join(out.text.split())
        unrecoverable = [node.idx for node in ordinary_nodes
                         if out.cold.texts.get(node.idx) != node.text and " ".join(node.text.split()) not in body]
        result.append({"head_tokens": out.tokens, "tail_tokens": tail_tokens,
                       "total_tokens": out.tokens + tail_tokens,
                       "configured_total_budget": head_cap + tail_tokens,
                       "budget_excess": max(0, out.tokens - head_cap),
                       "selection_budget_excess": max(0, out.tokens - budget),
                       "budget_audit": out.result.budget,
                       "ordinary_source_count": count,
                       "unrecoverable_ordinary": unrecoverable,
                       "protected_missing": missing,
                       "protected": facts,
                       "current_state_count": len(state)})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folds", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=3000)
    parser.add_argument("--head-cap", type=int, default=6000)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    harness = runpy.run_path(str(root / "_wsc_out" / "_fold_veto_ab.py"))
    os.environ["XEYO_HOME"] = str(args.output.parent / "budget-probe-home")
    os.environ["XEYO_USAGE_DIR"] = str(args.output.parent / "budget-probe-usage")
    points = [json.loads(line) for line in args.folds.read_text(encoding="utf-8").splitlines()]
    histories = {name: harness["load_case"](source) for name, source in harness["CASES"]}
    rows = []
    with args.output.with_suffix(".points.jsonl").open("w", encoding="utf-8") as file:
        for point in points:
            if not point["fold"]:
                continue
            raw = without_repeat_facts(histories[point["case"]][:point["end"]])
            pair = matched_pair(raw, cwd=args.output.parent / "budget-probe", budget=args.budget,
                                head_cap=args.head_cap)
            row = {"case": point["case"], "shot": point["shot"], "end": point["end"],
                   "baseline": pair[0], "candidate": pair[1]}
            rows.append(row)
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {"scope": "Fresh folds at baseline fold points; same raw ordinary boundary, identical ordinary tail/current state, same 6000-token head attention cap plus common tail. Both use a 3000-token internal selection budget, which is not a hard emitted-token cap: production separately accounts recovery index/protected facts. Snapshot layout for both arms. Tests deterministic protected seed facts and complete ordinary-text recovery; not task success or cache economics or journal growth.",
               "points": len(rows), "selection_budget": args.budget, "head_budget": args.head_cap,
               "arms": {arm: {"head_tokens": sum(row[arm]["head_tokens"] for row in rows),
                              "over_budget_points": sum(row[arm]["budget_excess"] > 0 for row in rows),
                              "max_budget_excess": max((row[arm]["budget_excess"] for row in rows), default=0),
                              "over_selection_budget_points": sum(row[arm]["selection_budget_excess"] > 0 for row in rows),
                              "max_head_tokens": max((row[arm]["head_tokens"] for row in rows), default=0),
                              "unrecoverable_ordinary": sum(len(row[arm]["unrecoverable_ordinary"]) for row in rows),
                              "protected_missing": {key: sum(len(row[arm]["protected_missing"][key]) for row in rows)
                                                    for key in ("original_task", "constraints", "errors", "todos")}}
                        for arm in ("baseline", "candidate")},
               "fold_manifest_sha256": hashlib.sha256(args.folds.read_bytes()).hexdigest(),
               "candidate_head_larger_points": sum(row["candidate"]["head_tokens"] > row["baseline"]["head_tokens"] for row in rows),
               "max_candidate_head_increase": max((row["candidate"]["head_tokens"] - row["baseline"]["head_tokens"] for row in rows), default=0),
               "inputs_sha256": {name: hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                                 for name, raw in histories.items()},
               "source_sha256": {name: hashlib.sha256((root / "python" / name).read_bytes()).hexdigest()
                                 for name in ("evals/wsc_append_budget.py", "session/compression_source.py", "synaptic/state_source.py", "synaptic/project.py", "synaptic/budget.py", "synaptic/seeds.py")}}
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("points", "head_budget", "arms")}))


if __name__ == "__main__":
    main()
