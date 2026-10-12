"""Offline same-transcript comparison of verification invocation presentation."""
import argparse
import hashlib
import json
from pathlib import Path


def run(transcript, output):
    transcript, output = transcript.resolve(), output.resolve()
    from evals.wsc_catalog_behavior import environment
    from evals.stale_goal_ab import tool_read
    from memory.wsc_projection import production_params
    from memory.working import WorkingSnapshot
    from session.compression_source import compression_messages
    from session.hydrate import messages_from_rows
    from session.message_store import MessageStore
    from session.surface import fold_surface_rows
    from session.transcript_blobs import resolve_transcript_rows
    from synaptic import task_verification
    from synaptic.coldstore import node_group_handle
    from synaptic.project import project
    from synaptic.task_checkpoint import project_state

    data = transcript.read_bytes()
    rows = [json.loads(line) for line in data.decode("utf-8-sig").splitlines() if line.strip()]
    rows = resolve_transcript_rows(fold_surface_rows(rows), transcript)
    output.mkdir(parents=True, exist_ok=True)
    with environment(output):
        source = compression_messages(MessageStore(messages_from_rows(rows)), WorkingSnapshot())
        original = json.dumps(source, ensure_ascii=False, sort_keys=True)
        current_invocation = task_verification.invocation
        try:
            # Previous behavior: the result budget never charged invocation inputs.
            task_verification.invocation = lambda value, index, remaining: ({"input": value}, remaining)
            before = project(source, region_end=len(source), params=production_params(), view_path=output / "before.txt")
        finally:
            task_verification.invocation = current_invocation
        after = project(source, region_end=len(source), params=production_params(), view_path=output / "afterx.txt")
        state, _ = project_state(source, after.graph)
        scope = state.get("terminal_task") or state
        _, ranges = after.cold.render_text_view()
        recalls = []
        for receipt in scope["verification_receipts"]:
            if receipt.get("input_inline") is False:
                first, last = ranges[node_group_handle((receipt["input_source"],))]
                recovered = tool_read({"file_path": after.view_path, "offset": first, "limit": last-first+1}, output)
                # Compare the exact view block, not a guessed substring or preview.
                expected = Path(after.view_path).read_text(encoding="utf-8").splitlines()[first-1:last]
                text = recovered.get("content", "")
                recalls.append({"call_id": receipt["call_id"], "input_bytes": receipt["input_bytes"],
                    "read_success": not recovered["is_error"],
                    "exact_view_lines_present": all(line in text for line in expected),
                    "range": [first, last]})
        (output / "before-head.txt").write_text(before.text, encoding="utf-8")
        (output / "after-head.txt").write_text(after.text, encoding="utf-8")
        result = {"transcript": str(transcript), "source_rows": len(source),
            "before_characters": len(before.text), "after_characters": len(after.text),
            "input_recalls": recalls,
            "source_unchanged": original == json.dumps(source, ensure_ascii=False, sort_keys=True),
            "transcript_unchanged": hashlib.sha256(data).hexdigest() == hashlib.sha256(transcript.read_bytes()).hexdigest(),
            "api_calls": 0, "limits": "Same source and fold extent; presentation comparison, no model semantic score."}
        (output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.transcript, args.output)
