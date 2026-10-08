"""Offline G1 A/B reconstruction; production transcripts/heads/views are read-only.

Closure indices are operator annotations, not inferred by the candidate rule.
No model/provider call is made. Full-head breaks and goal-line changes are
reported separately: a goal change may coincide with an existing head break.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from dataclasses import asdict
import difflib
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from synaptic.coldstore import node_handle
from synaptic.freshness import analyze
from synaptic.graph import build_graph
from synaptic.goal_staleness import ENV
from synaptic.project import project


def tool_read(reference, cwd):
    from engine.abort import AbortController
    from tools.file_read_tool.file_read_tool import FileReadTool
    result = asyncio.run(FileReadTool(cwd=str(cwd)).execute(reference, AbortController()))
    return {"is_error": result.is_error, "content": result.content}


@contextmanager
def arm(value):
    old = os.environ.get(ENV)
    os.environ[ENV] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = old


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fingerprints(paths):
    return {str(p.resolve()): sha(p.read_bytes()) for p in paths if p.is_file()}


def transitions(texts):
    return sum(not new.startswith(old) for old, new in zip(texts, texts[1:]))


def evaluate(rows, *, goal_index, close_index, cuts, output, protected=()):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    before = fingerprints(protected)
    from memory.wsc_projection import production_params
    # Identical algorithm budget and source in both arms. New head each time;
    # production's frozen head reuse is intentionally not overridden here.
    params = production_params()
    summary = {"schema": 1, "rows": len(rows), "goal_index": goal_index,
               "close_index": close_index, "cuts": cuts, "params": asdict(params),
               "scope": "isolated reconstruction, not live model traffic", "arms": {}}
    projections = {}
    for label, value in (("off", "0"), ("on", "1")):
        heads, goals, snapshots = [], [], []
        with arm(value):
            for cut in cuts:
                source = rows[:cut]
                graph = build_graph(source, include_soft_edges=params.soft_dag)
                fresh = analyze(graph, region_end=cut)
                folder = output / label / str(cut)
                folder.mkdir(parents=True, exist_ok=True)
                result = project(source, region_end=cut, params=params,
                                 session="isolated-g1-ab", view_path=folder / "cold.txt")
                goal = next((p for p in result.result.hot.pins if p.key == "goal"), None)
                goal_text = goal.text if goal else ""
                retired = [asdict(d) for d in fresh.downgrades if d.cls == "goal"]
                recalled = result.cold.expand(node_handle(goal_index))
                original = graph.node(goal_index).text
                view_text, ranges = result.cold.render_text_view()
                start, end = ranges[node_handle(goal_index)]
                read_back = "\n".join((folder / "cold.txt").read_text(encoding="utf-8").split("\n")[start-1:end])
                snapshot = {"cut": cut, "goal": goal_text,
                            "goal_nodes": list(goal.nodes) if goal else [],
                            "closed_goal_still_pinned": cut > close_index and goal is not None and goal_index in goal.nodes,
                            "retired": retired, "mis_downgrade": list(fresh.mis_downgrade),
                            "cold_lossless": recalled == (original,),
                            "read_slice_matches": read_back == original.replace("\r\n", "\n").replace("\r", "\n"),
                            "read_ref": {"file_path": str((folder / 'cold.txt').resolve()), "offset": start, "limit": end-start+1},
                            "head_sha256": sha(result.text.encode()), "head_tokens": result.tokens}
                (folder / "head.txt").write_text(result.text, encoding="utf-8")
                receipt = tool_read(snapshot["read_ref"], output)
                snapshot["real_read_tool"] = receipt
                snapshot["real_read_tool_contains_original"] = not receipt["is_error"] and original in str(receipt["content"])
                heads.append(result.text)
                goals.append(goal_text)
                snapshots.append(snapshot)
                projections[label, cut] = result
        summary["arms"][label] = {
            "closed_goal_still_pinned_count": sum(s["closed_goal_still_pinned"] for s in snapshots),
            "post_closure_samples": sum(s["cut"] > close_index for s in snapshots),
            "mis_downgrade": sorted({x for s in snapshots for x in s["mis_downgrade"]}),
            "full_head_prefix_breaks": transitions(heads),
            "goal_line_prefix_breaks": transitions(goals), "snapshots": snapshots,
        }
    off, on = summary["arms"]["off"], summary["arms"]["on"]
    summary["full_head_prefix_break_increment"] = on["full_head_prefix_breaks"] - off["full_head_prefix_breaks"]
    summary["goal_line_prefix_break_increment"] = on["goal_line_prefix_breaks"] - off["goal_line_prefix_breaks"]
    summary["annotated_goal_switches"] = sum(a <= close_index < b for a,b in zip(cuts,cuts[1:]))
    final_cut = cuts[-1]
    a, b = projections["off", final_cut], projections["on", final_cut]
    diff = list(difflib.unified_diff(a.text.splitlines(), b.text.splitlines(), fromfile="off", tofile="on", lineterm=""))
    (output / "head.diff").write_text("\n".join(diff) + "\n", encoding="utf-8")
    normalize_a = a.text.replace(str(output / "off" / str(final_cut) / "cold.txt"), "<isolated-view>")
    normalize_b = b.text.replace(str(output / "on" / str(final_cut) / "cold.txt"), "<isolated-view>")
    normalized_diff = list(difflib.unified_diff(normalize_a.splitlines(), normalize_b.splitlines(), fromfile="off", tofile="on", lineterm=""))
    (output / "head-normalized.diff").write_text("\n".join(normalized_diff) + "\n", encoding="utf-8")
    summary["final_non_goal_pin_changes"] = [p.key for p in a.result.hot.pins if p.key != "goal" and p not in b.result.hot.pins]
    remaining_facts = {p.text for p in b.result.hot.pins}
    summary["final_non_goal_facts_missing"] = [p.text for p in a.result.hot.pins if p.key != "goal" and p.text not in remaining_facts]
    summary["protected_before"] = before
    summary["protected_after"] = fingerprints(protected)
    summary["protected_unchanged"] = summary["protected_before"] == summary["protected_after"]
    summary["acceptance"] = {
        "post_closure_samples_present": on["post_closure_samples"] > 0,
        "closed_goal_retired": on["closed_goal_still_pinned_count"] == 0,
        "no_observed_reopen": not on["mis_downgrade"],
        "goal_changes_equal_annotated_switches": summary["goal_line_prefix_break_increment"] == summary["annotated_goal_switches"],
        "protected_files_unchanged": summary["protected_unchanged"],
        "original_recovered": all(s["cold_lossless"] and s["read_slice_matches"] and s["real_read_tool_contains_original"]
                                  for a in summary["arms"].values() for s in a["snapshots"]),
        "remaining_pin_facts_preserved": not summary["final_non_goal_facts_missing"],
    }
    (output / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--goal-index", type=int, required=True)
    parser.add_argument("--close-index", type=int, required=True)
    parser.add_argument("--cuts", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.transcript.read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    cuts = sorted(set(int(x) for x in args.cuts.split(",")))
    if not 0 <= args.goal_index < args.close_index < len(rows) or any(c <= args.goal_index or c > len(rows) for c in cuts):
        parser.error("indices or reconstruction cuts outside transcript")
    sid = args.transcript.stem
    workspace = Path(__file__).resolve().parents[2]
    protected = set(args.transcript.parent.glob(sid + ".*"))
    protected.update((args.transcript.parent.parent / "wsc_head").glob(sid + ".*"))
    protected.update((workspace / ".xeyo_offload" / "wsc").glob(sid + "*"))
    protected.update(workspace / p for p in ("python/prompt/system_prompt.py", "python/synaptic/assemble.py", "python/synaptic/pin_render.py"))
    output = args.output.resolve()
    if any(output == p.resolve() or p.resolve().is_relative_to(output) for p in protected):
        parser.error("output overlaps protected session paths")
    report = evaluate(rows, goal_index=args.goal_index, close_index=args.close_index,
                      cuts=cuts, output=output, protected=protected)
    report["transcript_sha256"] = sha(raw)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"rows": report["rows"], "arms": {k: {n:v for n,v in a.items() if n != "snapshots"} for k,a in report["arms"].items()},
                      "full_head_prefix_break_increment": report["full_head_prefix_break_increment"],
                      "goal_line_prefix_break_increment": report["goal_line_prefix_break_increment"],
                      "annotated_goal_switches": report["annotated_goal_switches"],
                      "protected_unchanged": report["protected_unchanged"]}, ensure_ascii=False, indent=2))
    return 0 if all(report["acceptance"].values()) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
