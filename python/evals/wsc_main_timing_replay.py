"""Offline reconstruction of a captured XEYO conversation under main timing.

No provider calls, historical wire inference or writes to the live session.
"""
import argparse
import hashlib
import json
import uuid
from pathlib import Path

from evals.wsc_unfolded_source_ab import environment
from memory.runtime import force_compact, project_for_model
from memory.working import WorkingSnapshot, flush, hydrate
from memory.wsc_request_timing import prepare
from memory.wsc_timing import delivered
from memory import wsc_projection
from tools.catalog import build_default_registry
from model.openai_compat import OpenAICompatClient


def run(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    captured = source.read_bytes()
    rows = [json.loads(line) for line in captured.decode("utf-8").splitlines() if line.strip()]
    output.mkdir(parents=True, exist_ok=True)
    with environment(output):
        import os
        os.environ["XEYO_WSC"] = "1"
        os.environ["XEYO_WSC_MODEL_TIMING"] = "0"
        os.environ["XEYO_WSC_TASK_CONTINUITY"] = "0"
        wsc_projection._STATE.clear()
        working = WorkingSnapshot(session_id="offline-main-timing-" + uuid.uuid4().hex[:12])
        schemas = build_default_registry(cwd=str(output)).schemas()
        model = OpenAICompatClient(api_key="offline", base_url="https://example.invalid", model="offline")
        model.declare_context_limit(1_000_000)
        def build(projected):
            return [{"role": "system", "content": "offline reconstruction"}] + [
                {key: value for key, value in row.items() if key in {"role", "content", "name"}}
                for row in projected]
        def render(projected, notice):
            return projected + [{"role": "system", "content": notice}]
        keep = project_for_model(rows, working, context_limit=model.context_limit,
                                 capacity_managed=True, include_memory_index=False, cwd=output)
        pre_cursor = working.compact_cursor
        prepared = prepare(keep, schemas, working, context_limit=model.context_limit,
                           build=build, render=render, model=model,
                           compact=lambda: force_compact(rows, working, cwd=output))
        native = next(iter(wsc_projection._STATE.values()))
        head, cold_path = native.head, Path(native.view_path)
        cold_bytes = cold_path.read_bytes()
        (output / "rebuilt-head.txt").write_text(head, encoding="utf-8")
        (output / "rebuilt-request.json").write_text(json.dumps(prepared.messages, ensure_ascii=False), encoding="utf-8")
        # Read five actual source ranges using the same Read implementation.
        from evals.stale_goal_ab import tool_read
        raw, ranges = native.cold.render_text_view()
        stored = cold_bytes.decode("utf-8").split("\n")
        reads = []
        for handle, (start, end) in list(ranges.items())[:5]:
            result = tool_read({"file_path": str(cold_path), "offset": start, "limit": min(8, end-start+1)}, output)
            reads.append(not result["is_error"] and stored[start-1].strip() in result["content"])
        cursor = working.compact_cursor
        delivered(working, prepared.delivery_key)
        flush(working.session_id, working)
        recovered = hydrate(working.session_id)
        wsc_projection._STATE.clear()
        resumed = project_for_model(rows, recovered, context_limit=model.context_limit,
                                    capacity_managed=True, include_memory_index=False, cwd=output)
        again = prepare(resumed, schemas, recovered, context_limit=model.context_limit,
                        build=build, render=render, model=model,
                        compact=lambda: force_compact(rows, recovered, cwd=output))
        from memory.wsc_execution_boundary import protect
        tail_start = protect(rows, len(rows))
        unconsumed = [block["content"] for row in rows[tail_start:] if isinstance(row.get("content"), list)
                      for block in row["content"] if block.get("type") == "tool_result" and isinstance(block.get("content"), str)]
        report = {"scope": "real saved conversation, offline rebuilt request; no real-model behavior claim",
                  "source_rows": len(rows), "source_sha256": hashlib.sha256(captured).hexdigest(),
                  "declared_capacity": model.context_limit, "cursor_before_request_admission": pre_cursor,
                  "cursor_after": cursor, "admission": prepared.facts, "following_request": again.facts,
                  "head_lines": len(head.splitlines()), "actual_read_pass": sum(reads), "actual_read_total": len(reads),
                  "unconsumed_receipts": len(unconsumed),
                  "acceptance": {"no_fold_before_full_request": pre_cursor == 0,
                                 "85_percent_force": prepared.facts["before"]["timing_action"] == "capacity" and cursor > 0,
                                 "unconsumed_results_intact": all(body in str(prepared.messages) for body in unconsumed),
                                 "restart_head_exact": resumed[0]["content"] == head,
                                 "below_85_no_new_fold": again.facts["automatic_attempts"] == 0 and recovered.compact_cursor == cursor,
                                 "cold_bytes_immutable": cold_path.read_bytes() == cold_bytes,
                                 "cold_layout_exact": raw == cold_bytes.decode("utf-8"),
                                 "actual_read": all(reads) and bool(reads),
                                 "source_bytes_immutable": captured == source.read_bytes()}}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run(args.source, args.output)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if all(result["acceptance"].values()) else 1)
