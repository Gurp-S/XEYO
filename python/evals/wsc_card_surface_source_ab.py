"""Card surface A/B on an isolated saved-source copy with a declared probe."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from evals.stale_goal_ab import tool_read
from evals.wsc_request_projection import arm
from evals.wsc_task_continuity_ab import task_event
from memory.wsc_projection import production_params
from synaptic.card_surface import ENV, PREFIX
from synaptic.project import project
from synaptic.todo_snapshot import latest_todo_snapshot


def run(source, output):
    source, output = Path(source), Path(output).resolve()
    captured = source.read_bytes()
    rows = [json.loads(line) for line in captured.decode("utf-8").splitlines() if line.strip()]
    previous = {key: os.environ.get(key) for key in (ENV, "XEYO_WSC_TASK_CONTINUITY")}
    report = {"scope": "same saved source plus operator-declared probe in private copies, not historical checkpoint/wire; production projection budgets",
        "source_sha256": hashlib.sha256(captured).hexdigest(), "rows": len(rows), "arms": {}}
    output.mkdir(parents=True, exist_ok=True)
    try:
        os.environ["XEYO_WSC_TASK_CONTINUITY"] = "1"
        copied = rows + task_event("card-probe", list(latest_todo_snapshot(rows).records),
            {"objective": "离线检验原去噪计划的任务续接表示", "context_message_ids": [rows[2163]["id"]],
                "decisions": ["文件系统存在性方案已否决；路径候选来自调用声明"]})
        projections = {}
        for label, flag in (("cards", "0"), ("index", "1")):
            os.environ[ENV] = flag
            root = output / label
            root.mkdir(exist_ok=True)
            with arm("1", root / "home"):
                projection = project(copied, region_end=len(copied), params=production_params(), view_path=root / "cold.txt")
                (root / "head.txt").write_text(projection.text, encoding="utf-8")
                projections[label] = projection
                report["arms"][label] = {"head_estimated_tokens": projection.tokens, "cards": len(projection.result.hot.cards),
                    "cold_sources": len(projection.cold.texts), "view_bytes": Path(projection.view_path).stat().st_size}
        indexed = projections["index"]
        handles = [handle for handle in indexed.cold.snapshots if handle.startswith(PREFIX)]
        _, ranges = indexed.cold.render_text_view()
        records = [json.loads(line) for line in indexed.cold.snapshots[handles[0]].splitlines()] if handles else []
        locations = {record["source"]: record for record in records if "view_lines" in record}
        card_sources = {index for card in indexed.result.hot.cards for index in card.nodes}
        valid = bool(locations) and set(locations) == card_sources
        from synaptic.chunked_recovery import prepare as prepare_chunks
        from synaptic.coldstore import node_handle
        aliases = prepare_chunks(indexed.cold)
        for index, record in locations.items():
            valid = valid and record["source_sha256"] == hashlib.sha256(indexed.cold.texts[index].encode("utf-8")).hexdigest()
            origin = aliases.get(node_handle(index), node_handle(index))
            valid = valid and tuple(record["view_lines"]) == ranges.get(origin)
        read_ok = False
        if handles:
            first, last = ranges[handles[0]]
            receipt = tool_read({"file_path": indexed.view_path, "offset": first, "limit": min(8, last-first+1)}, output)
            read_ok = not receipt["is_error"] and "card_source_index" in receipt["content"]
        checkpoint = lambda projection: next(pin.text for pin in projection.result.hot.pins if pin.key == "task_checkpoint")
        report["acceptance"] = {"explicit_state_identical": checkpoint(projections["cards"]) == checkpoint(indexed),
            "raw_cold_sources_identical": projections["cards"].cold.texts == indexed.cold.texts,
            "all_card_source_locations_valid": bool(valid), "actual_index_read": read_ok,
            "source_bytes_unchanged": captured == source.read_bytes(),
            "historical_goal_not_derived": not any(pin.key == "goal" for pin in indexed.result.hot.pins)}
        report["indexed_card_sources"] = len(locations)
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run(args.source, args.output)
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if all(result["acceptance"].values()) else 1)
