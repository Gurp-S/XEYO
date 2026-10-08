"""Offline paired reconstructions and adversarial checks, with real Read receipts."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from dataclasses import asdict
import difflib
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.stale_goal_ab import fingerprints, tool_read
from memory.wsc_projection import production_params
from synaptic.project import project
from synaptic.contracts import verify_object
from synaptic.coldstore import node_handle


def freeze_replay(rows, output, sid):
    """Replay real rows through the live adapter at operator-selected fold boundaries."""
    from types import SimpleNamespace
    from unittest.mock import patch
    from memory import wsc_projection as live, wsc_head_store as store
    prior = dict(live._STATE)
    working = SimpleNamespace(session_id=sid + "-offline", compact_cursor=1844, c1_frozen_until=1844)
    output.mkdir(parents=True, exist_ok=True)
    try:
        with arm("1", output / "home"), patch.object(live, "live_enabled", return_value=True), \
             patch.object(live, "freeze_enabled", return_value=True), patch.object(store, "enabled", return_value=True), \
             patch("memory.wsc_extension_economics.absorb_boundary", side_effect=lambda messages, cursor: cursor):
            first = live.project_c2_messages(rows[:1844], working, cwd=str(output))
            tail = live.project_c2_messages(rows[:1845], working, cwd=str(output))
            working.compact_cursor = working.c1_frozen_until = 1845
            folded = live.project_c2_messages(rows[:1845], working, cwd=str(output))
            next_round = live.project_c2_messages(rows[:1866], working, cwd=str(output))
            live._STATE.clear()
            restart = live.project_c2_messages(rows[:1866], working, cwd=str(output))
            stages = {"before_closure": first, "closure_in_tail": tail, "after_fold": folded,
                      "next_round": next_round, "restart": restart}
            for name, messages in stages.items():
                if messages is None:
                    raise ValueError("offline_adapter_no_projection: " + name)
                (output / (name + ".json")).write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")
            return {"scope": "real transcript; operator-selected fold boundaries; no model calls",
                    "closure_in_tail_head_identical": first[0] == tail[0],
                    "one_lifecycle_fold_changes_head": first[0] != folded[0],
                    "next_round_head_identical": folded[0] == next_round[0],
                    "restart_emission_identical": next_round == restart}
    finally:
        live._STATE.clear()
        live._STATE.update(prior)


@contextmanager
def arm(value, home):
    values = {"XEYO_WSC_STATE_CONTRACTS": value, "XEYO_STALE_GOAL_RETIRE": "0",
              "XEYO_EXECUTION_FACT_CONTRACTS": value, "XEYO_WSC_OFFLINE": "1", "XEYO_HOME": str(home)}
    old = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def head_goal(projection):
    return next((pin.text for pin in projection.result.hot.pins if pin.key == "goal"), "")


def evaluate(source, output, cuts):
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    sid = source.stem
    home = source.parent.parent
    protected = [source, *source.parent.glob(sid + ".*"), * (home / "wsc_head").glob(sid + "*"),
                 * (Path.cwd() / ".xeyo_offload" / "wsc").glob(sid + "*")]
    before = fingerprints(protected)
    params = production_params()
    report = {"schema_version": 1, "source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "rows": len(rows), "params": asdict(params), "scope": "offline reconstruction; no model requests",
              "arms": {}, "comparisons": []}
    results = {}
    for label, value in (("before", "0"), ("after", "1")):
        snapshots = []
        with arm(value, output / label / "home"):
            for cut in cuts:
                folder = output / label / str(cut)
                folder.mkdir(parents=True, exist_ok=True)
                projection = project(rows[:cut], region_end=cut, params=params, session=sid,
                                     view_path=folder / "cold.txt")
                results[label, cut] = projection
                text, ranges = projection.cold.render_text_view()
                view = Path(projection.view_path).read_text(encoding="utf-8")
                recovery = []
                for index, original in projection.cold.texts.items():
                    handle = node_handle(index)
                    start, end = ranges[handle]
                    actual = "\n".join(view.split("\n")[start - 1:end])
                    reference = handle if handle in projection.cold.handles else next(
                        (h for h, nodes in projection.cold.handles.items() if index in nodes), None)
                    recovered = reference is not None and projection.cold.expand(reference)[projection.cold.handles[reference].index(index)] == original
                    recovery.append(actual == original.replace("\r\n", "\n").replace("\r", "\n") and recovered)
                indices = list(dict.fromkeys([0, *[i for i in projection.cold.texts if projection.graph.node(i).is_error][:3],
                                             *list(projection.cold.texts)[-2:]]))
                reads = []
                for index in indices:
                    if index not in projection.cold.texts:
                        continue
                    start, end = ranges[node_handle(index)]
                    reference = {"file_path": str(Path(projection.view_path).resolve()), "offset": start,
                                 "limit": min(10, end - start + 1)}
                    receipt = tool_read(reference, output)
                    reads.append({"node": index, "reference": reference,
                                  "is_error": receipt["is_error"], "content": receipt["content"]})
                (folder / "head.txt").write_text(projection.text, encoding="utf-8")
                snapshots.append({"cut": cut, "goal": head_goal(projection), "head_tokens": projection.tokens,
                                  "view_path": projection.view_path, "sealed": bool(verify_object(projection.view_path)),
                                  "unresolved_facts": list(projection.seeds.unresolved_errors),
                                  "cold_nodes": len(recovery), "cold_exact": sum(recovery), "reads": reads,
                                  "lifecycle": projection.state.lifecycle})
                (output / "progress.json").write_text(json.dumps({"arm": label, "cut": cut}), encoding="utf-8")
        report["arms"][label] = snapshots
    for cut in cuts:
        a, b = results["before", cut], results["after", cut]
        missing = [p.text for p in a.result.hot.pins if p.key != "goal" and p.text not in {q.text for q in b.result.hot.pins}]
        report["comparisons"].append({"cut": cut, "tokens_before": a.tokens, "tokens_after": b.tokens,
                                       "non_goal_facts_missing": missing})
    final = cuts[-1]
    a, b = results["before", final], results["after", final]
    (output / "head.diff").write_text("\n".join(difflib.unified_diff(a.text.splitlines(), b.text.splitlines(),
                                          fromfile="before", tofile="after", lineterm="")), encoding="utf-8")
    report["protected_before"] = before
    report["freeze_replay"] = freeze_replay(rows, output / "freeze-replay", sid) if len(rows) >= 1866 else {}
    report["protected_after"] = fingerprints(protected)
    report["acceptance"] = {
        "source_and_old_artifacts_unchanged": before == report["protected_after"],
        "all_cold_nodes_exact": all(s["cold_exact"] == s["cold_nodes"] for snapshots in report["arms"].values() for s in snapshots),
        "actual_reads_succeeded": all(not r["is_error"] for snapshots in report["arms"].values() for s in snapshots for r in s["reads"]),
        "all_candidate_views_content_sealed": all(s["sealed"] for s in report["arms"]["after"]),
        "standing_pin_facts_preserved": all(not row["non_goal_facts_missing"] for row in report["comparisons"]),
        "live_freeze_replay": all(v for k, v in report["freeze_replay"].items() if k != "scope"),
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cuts", default="200,400,800,1200,1600,1809,1844,1845,1866,1879")
    args = parser.parse_args()
    report = evaluate(args.source, args.output.resolve(), [int(x) for x in args.cuts.split(",")])
    print(json.dumps({"acceptance": report["acceptance"], "report": str(args.output / "report.json")}, ensure_ascii=False))
    return 0 if all(report["acceptance"].values()) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
