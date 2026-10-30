"""Read-only replay of a native archive. No model calls or host installation.

The chosen existing assistant message is supplied by ordinal; this is explicit
replay selection, not evidence for automatic selection or task quality.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wsc import WSC, Store, Limits, Selection, Understanding
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.contracts import encode, require


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--old-restoration", type=Path)
    parser.add_argument("--understanding-ordinal", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = perf_counter()
    raw = args.source.read_bytes()
    source_hash = sha256(raw).hexdigest()
    archive = json.loads(raw.decode("utf-8-sig"))
    items = archive["items"]
    args.output.mkdir(parents=True, exist_ok=True)
    require(not (args.output / "state.db").exists(), "replay_output_exists")
    adapter = CodexCheckpointAdapter()
    batch = adapter.import_items(items, thread_id=archive["thread_id"])
    core = WSC(Store(args.output / "state.db", session_id="offline-replay:" + source_hash,
                     workspace=str(args.output)), access=lambda *args: True)
    ids = core.ingest(batch)
    # The replay harness observes these archived result values. This does NOT
    # assert that an earlier live model received, understood or verified them.
    core.presented("offline-archive-reader", tuple(e.id for e in batch if e.kind == "result"),
                   receiver="offline_replay_harness_not_native_model")
    selected = batch[args.understanding_ordinal]
    require(selected.role == "assistant" and selected.kind == "message" and bool(selected.text),
            "replay_understanding_not_public_assistant_text")
    view = core.prepare(core.capture(), Selection(new_understandings=(Understanding(
        selected.text, "historical_public_reply", (selected.id,),
        scope={"source_ordinal": args.understanding_ordinal, "current_applicability": "unverified"}),)),
        producer="offline_replay_of_original_public_assistant", limits=Limits(max_view_bytes=262144))
    operation = core.stage(view, directory=args.output / "exports", adapter=adapter)
    package = core.package(operation)
    exported = [json.loads(Path(package["evidence"][key]["file_path"]).read_text(encoding="utf-8")) for key in ids]
    require(exported == items, "replay_source_roundtrip_failed")
    original_controls = [x for x in items if x.get("role") in {"user", "system", "developer"}]
    actual_controls = [x for x in package["items"] if x.get("role") in {"user", "system", "developer"}]
    require(original_controls == actual_controls, "replay_control_preservation_failed")
    require(args.source.read_bytes() == raw, "replay_input_changed")
    report = {
        "kind": "offline_source_and_checkpoint_contract_replay",
        "source": str(args.source.resolve()), "source_sha256": source_hash,
        "source_items": len(items), "source_kinds": dict(Counter(e.kind for e in batch)),
        "exported_source_values_equal": exported == items,
        "original_control_messages_equal_and_ordered": original_controls == actual_controls,
        "native_input_file_unchanged": args.source.read_bytes() == raw,
        "source_canonical_json_bytes": len(encode(items).encode("utf-8")),
        "checkpoint_items_canonical_json_bytes": len(encode(package["items"]).encode("utf-8")),
        "checkpoint_item_count": len(package["items"]),
        "reused_public_reply_ordinal": args.understanding_ordinal,
        "reused_public_reply_characters": len(selected.text),
        "new_model_calls": 0,
        "historical_generation_cost": None, "task_quality": "not_evaluated", "total_token_cost": None,
        "publication_state": core.status()["operations"][-1]["state"],
        "fold_cursor": core.status()["cursor"], "installation": "not_attempted",
        "checkpoint": str((args.output / "exports" / operation / "checkpoint.json").resolve()),
        "elapsed_ms": round((perf_counter() - started) * 1000, 3),
        "limits": ["Explicit replay selection; automatic semantic selection not evaluated",
                   "Offline presentation receipt is not a historical native-model receipt",
                   "Bytes are not tokens, billed cost, latency savings or correctness",
                   "All source control roles are retained; old restoration may use different host setup",
                   "Original task tools were not rerun; native continuation not evaluated"]}
    if args.old_restoration:
        old_raw = args.old_restoration.read_bytes()
        old = json.loads(old_raw.decode("utf-8-sig"))
        report["old_reference"] = {"path": str(args.old_restoration.resolve()),
                                   "sha256": sha256(old_raw).hexdigest(), "items": len(old),
                                   "canonical_json_bytes": len(encode(old).encode("utf-8")),
                                   "comparison": "different_material_scope_not_an_A_B_cost_result"}
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(encode(report))


if __name__ == "__main__":
    main()
