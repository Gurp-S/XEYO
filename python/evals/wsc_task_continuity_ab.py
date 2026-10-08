"""Real saved-source A/B plus explicitly annotated checkpoint continuation.

Reconstructed emissions are not historical provider wire captures. The probe
adds real TodoWrite tool receipts to a private copy, never to the saved session.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evals.wsc_request_projection import arm, protected_paths, source_prefix_intact
from evals.stale_goal_ab import fingerprints, tool_read
from memory.wsc_projection import production_params
from synaptic.project import project
from synaptic.coldstore import node_handle
from synaptic.task_checkpoint import canonical
from synaptic.todo_snapshot import latest_todo_snapshot
from tools.todo_write_tool.todo_write_tool import TodoWriteTool, parse_input


def emission_cost(text):
    """Partition rendered bytes; tokenizer approximation stays explicitly named."""
    parts = {name: 0 for name in ("current_request", "original_context_sources", "task_state", "failure_facts",
        "historical_request_handles", "source_links", "other")}
    section = ""
    in_task = False
    in_original = False
    for line in text.splitlines(keepends=True):
        heading = re.match(r"\[[^\]]+\]", line.strip())
        if heading:
            section = heading.group(0)
        original_bytes = 0
        link_text = line
        if line.startswith("[CONSTRAINTS] 任务交接快照："):
            in_task = True
        if in_task:
            link_text = line if line.startswith(("  来源=", "完整来源=", "来源范围=")) else ""
            if line.startswith("    ") and in_original:
                original_bytes = len(line[4:].rstrip("\r\n").encode("utf-8"))
            elif line.startswith("  原文:"):
                in_original = True
            else:
                in_original = False
        legacy_task = line.startswith("[CONSTRAINTS] 任务状态快照:")
        if legacy_task:
            start = line.index("任务状态快照:") + len("任务状态快照:")
            raw = line[start:].lstrip()
            state, end = json.JSONDecoder().raw_decode(raw)
            original_bytes = sum(len(canonical(item["text"]).encode("utf-8"))
                                 for item in state["context_sources"])
            link_text = line[:start] + raw[end:]
        links = re.findall(r"Read\([^()\n]*\)", link_text)
        link_bytes = sum(len(link.encode("utf-8")) for link in links)
        body_bytes = len(line.encode("utf-8")) - link_bytes
        category = "other"
        if legacy_task or in_task:
            category = "task_state"
            parts["original_context_sources"] += original_bytes
            body_bytes -= original_bytes
        elif "折叠区末人类请求:" in line:
            category = "current_request"
        elif section == "[UNRESOLVED]":
            category = "failure_facts"
        elif section == "[REQUESTS]":
            category = "historical_request_handles"
        parts[category] += body_bytes
        parts["source_links"] += link_bytes
        if in_task and line.startswith("完整来源="):
            in_task = False
    return {"utf8_bytes": parts, "total_utf8_bytes": len(text.encode("utf-8")),
            "partition_exact": sum(parts.values()) == len(text.encode("utf-8")),
            "basis": "rendered-byte partition; token totals use UTF-8 quarters, not provider receipts"}


def task_event(uid, records, checkpoint=None):
    inputs = {"todos": records, **({"checkpoint": checkpoint} if checkpoint is not None else {})}
    tool = TodoWriteTool()
    parsed = parse_input(inputs)
    if isinstance(parsed, dict):
        raise ValueError(parsed)
    result = tool.call(parsed)
    return [{"role": "assistant", "content": [{"type": "tool_use", "id": uid, "name": "TodoWrite", "input": inputs}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": uid, "is_error": False,
                "content": tool.map_tool_result_to_content(result), "execution": {"status": "ok", "complete": True}}]}]


def probe(rows, output):
    from memory import wsc_projection as live, wsc_head_store as heads
    records = [dict(item) for item in latest_todo_snapshot(rows).records]
    if not records:
        raise ValueError("probe_requires_observed_todos")
    context = {"context_message_ids": [rows[2163]["id"]],
               "decisions": ["文件系统存在性方案已否决；路径候选来自调用声明"], "verification_call_ids": []}
    annotated = rows + task_event("offline-checkpoint", records, context)
    working = SimpleNamespace(session_id="task-checkpoint-probe", compact_cursor=len(rows), c1_frozen_until=len(rows))
    prior = dict(live._STATE)
    def emit(messages):
        result = live.project_c2_messages(messages, working, cwd=str(output))
        if result is None:
            raise ValueError("probe_no_emission")
        return result
    try:
        with patch.object(live, "live_enabled", return_value=True), patch.object(live, "freeze_enabled", return_value=True), \
             patch.object(heads, "enabled", return_value=True), \
             patch("memory.wsc_extension_economics.absorb_boundary", side_effect=lambda messages, cursor: cursor):
            first = emit(annotated)
            growing = annotated + [{"role": "user", "content": "继续第二批"}]
            tail = emit(growing)
            live._STATE.clear()
            restarted = emit(growing)
            finished = growing + task_event("offline-complete", [dict(item, status="completed") for item in records])
            completed_tail = emit(finished)
            working.compact_cursor = working.c1_frozen_until = len(finished)
            folded = emit(finished)
            live._STATE.clear()
            folded_restart = emit(finished)
            for label, result in dict(first=first, tail=tail, restart=restarted, completed_tail=completed_tail,
                                      folded=folded, folded_restart=folded_restart).items():
                (output / (label + ".json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"scope": "operator-declared checkpoint/complete receipts appended to isolated real-source copy; no historical state backfill",
                "acceptance": {"old_head_unchanged_during_tail": first[0] == tail[0] == completed_tail[0],
                    "entire_emission_append_only": tail[:len(first)] == first,
                    "restart_exact": tail == restarted,
                    "complete_receipt_in_tail": "offline-complete" in canonical(completed_tail),
                    "completed_fold_retires_checkpoint_decisions": "文件系统存在性方案已否决；路径候选来自调用声明" not in folded[0]["content"],
                    "fold_restart_exact": folded == folded_restart}}
    finally:
        live._STATE.clear()
        live._STATE.update(prior)


def evaluate(source, output):
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    captured = source.read_bytes()
    rows = [json.loads(line) for line in captured.decode("utf-8").splitlines() if line.strip()]
    protected = [path for path in protected_paths(source, source.parent.parent) if path != source]
    seals = fingerprints(protected)
    switches = {name: os.environ.get(name) for name in ("XEYO_WSC_TASK_CONTINUITY", "XEYO_WSC_FAILURE_FACTS", "XEYO_WSC_REQUIREMENT_FLOOR")}
    report = {"source": str(source), "source_sha256": hashlib.sha256(captured).hexdigest(), "rows": len(rows),
        "scope": "offline reconstruction; no model call, no live head/settings writes; identical relative view names for A/B cost",
        "arms": {}, "historical_emission_reproducible": False}
    try:
        for label, value in (("before", "0"), ("after", "1")):
            os.environ.update(XEYO_WSC_TASK_CONTINUITY=value, XEYO_WSC_FAILURE_FACTS="1", XEYO_WSC_REQUIREMENT_FLOOR="0")
            with arm("1", output / label / "home"):
                samples = []
                for cut in (2164, 2245, len(rows)):
                    folder = output / label / str(cut)
                    folder.mkdir(parents=True, exist_ok=True)
                    projection = project(rows[:cut], region_end=cut, params=production_params(), session="real-source",
                        view_path=folder / "cold.txt", view_ref="cold.txt")
                    (folder / "head.txt").write_text(projection.text, encoding="utf-8")
                    view, ranges = projection.cold.render_text_view()
                    stored = Path(projection.view_path).read_text(encoding="utf-8").split("\n")
                    exact = sum("\n".join(stored[start-1:end]) == text.replace("\r\n", "\n").replace("\r", "\n")
                        for index, text in projection.cold.texts.items()
                        for start, end in [ranges[node_handle(index)]])
                    events = {i for group in projection.seeds.unresolved_source_groups for i in group}
                    represented = {i for pin in projection.result.hot.pins
                        if pin.key.startswith("unresolved:") or pin.key == "failure_archive" for i in pin.nodes}
                    indices = [2163, *sorted(events)[-3:]]
                    reads = []
                    for index in dict.fromkeys(indices):
                        start, end = ranges[node_handle(index)]
                        got = tool_read({"file_path": str(Path(projection.view_path).resolve()), "offset": start,
                            "limit": min(8, end-start+1)}, folder)
                        reads.append(not got["is_error"] and stored[start-1].strip() in got["content"])
                    checkpoint = next((json.loads(pin.text) for pin in projection.result.hot.pins if pin.key == "task_checkpoint"), None)
                    samples.append({"cut": cut, "head_tokens": projection.tokens, "failure_events": len(events),
                        "emission_cost": emission_cost(projection.text),
                        "represented_failure_events": len(events & represented), "cold_exact": exact,
                        "cold_total": len(projection.cold.texts), "actual_reads_pass": sum(reads), "actual_reads_total": len(reads),
                        "derived_goal_absent": not any(pin.key == "goal" for pin in projection.result.hot.pins),
                        "historical_constraints_not_promoted": not projection.seeds.constraints,
                        "checkpoint": checkpoint, "historical_context_not_inferred": not checkpoint or not checkpoint["context_observed"]})
                report["arms"][label] = samples
        os.environ["XEYO_WSC_TASK_CONTINUITY"] = "1"
        with arm("1", output / "probe/home"):
            (output / "probe").mkdir(parents=True, exist_ok=True)
            report["probe"] = probe(rows, output / "probe")
        # Recorded timestamps can be related to saved rows, not to lost provider
        # wire snapshots or to canonical cursor indices from another profile.
        ledger = source.parent.parent / "usage/fold_events.jsonl"
        folds = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        report["recorded_folds"] = [{"timestamp": f["ts"], "recorded_prompt_tokens": f.get("prompt_tokens"),
            "reason": f.get("reason"), "forced": f.get("forced"),
            "preceding_saved_row": max((i for i, row in enumerate(rows) if float(row.get("ts", 0)) <= f["ts"]), default=-1)}
            for f in folds if f.get("session_id") == source.stem and f.get("fold")]
        all_samples = [sample for samples in report["arms"].values() for sample in samples]
        report["acceptance"] = {"all_failure_events_recoverable": all(s["failure_events"] == s["represented_failure_events"] for s in all_samples),
            "cold_exact": all(s["cold_exact"] == s["cold_total"] for s in all_samples),
            "actual_read": all(s["actual_reads_pass"] == s["actual_reads_total"] > 0 for s in all_samples),
            "no_derived_goal": all(s["derived_goal_absent"] for s in all_samples),
            "missing_historical_checkpoint_not_fabricated": all(s["historical_context_not_inferred"] for s in all_samples),
            "historical_constraints_not_promoted": all(s["historical_constraints_not_promoted"] for s in report["arms"]["after"]),
            "probe_continuation": all(report["probe"]["acceptance"].values()),
            "protected_artifacts": fingerprints(protected) == seals, "source_prefix": source_prefix_intact(captured, source)}
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    finally:
        for name, value in switches.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = evaluate(args.source, args.output)
    print(json.dumps({"acceptance": result["acceptance"], "arms": {key: [{field:s[field] for field in
        ("cut", "head_tokens", "failure_events", "represented_failure_events", "actual_reads_pass")} for s in samples]
        for key, samples in result["arms"].items()}, "probe": result["probe"]}, ensure_ascii=False))
    sys.exit(0 if all(result["acceptance"].values()) else 1)
