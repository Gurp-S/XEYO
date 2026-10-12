"""Read-only replay of a real model checkpoint across both compaction channels."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

from evals.wsc_unfolded_source_ab import environment


def run(session, output, *, cards_index=False):
    from memory.runtime import force_compact, project_for_model
    from memory.working import WorkingSnapshot, flush, hydrate
    from memory import wsc_projection
    from session.record_transcript import load_transcript
    from session.surface import fold_surface_rows
    from session.transcript_blobs import resolve_transcript_rows
    from session.hydrate import messages_from_rows
    from session.message_store import MessageStore
    from session.compression_source import compression_messages
    from synaptic.todo_snapshot import latest_todo_snapshot
    original = session.read_bytes()
    rows = resolve_transcript_rows(fold_surface_rows(load_transcript(session)), session)
    sources = compression_messages(MessageStore(messages_from_rows(rows)), WorkingSnapshot())
    state = latest_todo_snapshot(sources)
    prior = latest_todo_snapshot(sources[:-2])
    if not state.observed or not prior.observed: raise ValueError("cycle_two_checkpoints_required")
    first_sources = sources[:prior.checkpoint_source + 1]
    untouched = deepcopy(sources)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for native in (False, True):
        folder = output / ("native" if native else "fallback")
        folder.mkdir()
        with environment(folder):
            os.environ["XEYO_WSC"] = str(int(native))
            os.environ["XEYO_WSC_CARD_INDEX_ONLY"] = str(int(cards_index))
            wsc_projection._STATE.clear()
            working = WorkingSnapshot(session_id="state-replay")
            first = force_compact(first_sources, working, cwd=folder)
            cursor = working.compact_cursor
            appended = project_for_model(sources, working, cwd=folder)
            second = force_compact(sources, working, cwd=folder)
            flush(working.session_id, working)
            wsc_projection._STATE.clear()
            restored = hydrate(working.session_id, source_layout=working.compression_source_layout)
            recovered = project_for_model(sources, restored, cwd=folder)
            result = {"channel": "native" if native else "fallback", "first_cursor": cursor,
                "second_cursor": working.compact_cursor, "advanced": working.compact_cursor > cursor,
                "append_frozen_head_equal": appended[0] == first[0],
                "recovered_head_equal": recovered[0] == second[0],
                "head_characters": len(str(second[0]["content"])),
                "source_rows_unchanged": sources == untouched}
            (folder / "head.txt").write_text(str(second[0]["content"]), encoding="utf-8")
            results.append(result)
    report = {"scope": __doc__, "source": str(session.resolve()),
        "cards_index": cards_index,
        "source_sha256": hashlib.sha256(original).hexdigest(), "source_unchanged": session.read_bytes() == original,
        "state_records": list(state.records), "state_checkpoint": state.checkpoint,
        "results": results, "api_calls": 0}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--cards-index", action="store_true")
    args = p.parse_args()
    r = run(args.session, args.output, cards_index=args.cards_index)
    print(json.dumps({"source_unchanged": r["source_unchanged"], "results": r["results"]}))
