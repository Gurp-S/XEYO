"""Same rebuilt native WSC head, same saved-source tail, C0 policy A/B.

This is a new offline reconstruction at a declared pair-safe boundary. It
does not recover historical provider wire or infer task completion.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path

from engine.env_switches import isolation_pins
from memory.runtime import pair_safe_cut
from memory.token import token_len
from memory.wsc_projection import _emit, production_params
from synaptic.project import project


@contextmanager
def environment(root):
    old = dict(os.environ)
    try:
        for key, value in isolation_pins():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        os.environ.update(XEYO_HOME=str(root / "home"), XEYO_SESSIONS_DIR=str(root / "sessions"),
            XEYO_SPILL_DIR=str(root / "spill"), XEYO_WSC_OFFLINE="1",
            XEYO_WSC_TASK_CONTINUITY="1", XEYO_WSC_REQUEST_PROJECTION="1",
            XEYO_WSC_STATE_CONTRACTS="1", XEYO_TOOL_OFFLOAD="0", XEYO_WSC_SIZE_PRUNE="0")
        yield
    finally:
        os.environ.clear()
        os.environ.update(old)


def run(source, output, cut):
    source, output = Path(source).resolve(), Path(output).resolve()
    captured = source.read_bytes()
    rows = [json.loads(line) for line in captured.decode("utf-8").splitlines() if line.strip()]
    selected = pair_safe_cut(rows, cut)
    output.mkdir(parents=True, exist_ok=True)
    report = {"scope": "rebuilt native WSC generation at operator-selected pair-safe boundary; same head/tail, no historic wire or real-model behavior claim",
        "source_sha256": hashlib.sha256(captured).hexdigest(), "source_rows": len(rows),
        "requested_boundary": cut, "pair_safe_boundary": selected, "arms": {}}
    with environment(output):
        frozen = project(rows, region_end=selected, params=production_params(), view_path=output / "cold.txt")
        head_path = output / "head.txt"
        head_path.write_text(frozen.text, encoding="utf-8")
        head_bytes = head_path.read_bytes()
        cold_bytes = Path(frozen.view_path).read_bytes()
        emissions = {}
        for name, flag in (("before", "0"), ("after", "1")):
            os.environ["XEYO_WSC_MODEL_TIMING"] = flag
            emitted = _emit(frozen.text, rows, selected, selected, cwd=output, view_path=frozen.view_path)
            if len(emitted) != len(rows) - selected + 1:
                raise ValueError("unexpected source/emission coordinate change")
            (output / f"{name}-emission.json").write_text(json.dumps(emitted, ensure_ascii=False), encoding="utf-8")
            records = []
            for index in range(selected, len(rows)):
                blocks = rows[index].get("content")
                if not isinstance(blocks, list):
                    continue
                shown = emitted[index-selected+1].get("content")
                if not isinstance(shown, list) or len(blocks) != len(shown):
                    raise ValueError("unexpected result block layout")
                for position, block in enumerate(blocks):
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    raw = block.get("content")
                    if not isinstance(raw, str):
                        continue
                    visible = shown[position].get("content", "")
                    records.append({"source_index": index, "block": position, "call_id": block.get("tool_use_id"),
                        "source_characters": len(raw), "visible_characters": len(visible),
                        "committed_text_preserved": raw in visible,
                        "source_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest()})
            emissions[name] = (emitted, records)
            report["arms"][name] = {"input_estimated_tokens": token_len(json.dumps(emitted, ensure_ascii=False, separators=(",", ":"))),
                "receipt_records": len(records), "committed_text_preserved": sum(record["committed_text_preserved"] for record in records),
                "changed_receipts": [record for record in records if not record["committed_text_preserved"]]}
        before, after = emissions["before"], emissions["after"]
        recovered = [old["call_id"] for old, new in zip(before[1], after[1])
                     if not old["committed_text_preserved"] and new["committed_text_preserved"]]
        report["receipts_recovered_without_refetch"] = recovered
        report["acceptance"] = {"same_frozen_head": before[0][0] == after[0][0],
            "frozen_head_file_unchanged": head_bytes == head_path.read_bytes(),
            "published_cold_bytes_unchanged": cold_bytes == Path(frozen.view_path).read_bytes(),
            "all_committed_tail_receipts_preserved": all(record["committed_text_preserved"] for record in after[1]),
            "source_bytes_unchanged": captured == source.read_bytes(),
            "old_user_words_not_promoted_to_goal": not any(pin.key == "goal" for pin in frozen.result.hot.pins)}
        report["historical_behavior_or_useful_information_ratio_verified"] = False
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--output", required=True)
    parser.add_argument("--cut", type=int, default=2_000)
    args = parser.parse_args()
    result = run(args.source, args.output, args.cut)
    print(json.dumps({"source_rows": result["source_rows"], "pair_safe_boundary": result["pair_safe_boundary"],
        "arms": {name: {key: value for key, value in arm.items() if key != "changed_receipts"} for name, arm in result["arms"].items()},
        "recovered": len(result["receipts_recovered_without_refetch"]), "acceptance": result["acceptance"]}, ensure_ascii=False))
    raise SystemExit(0 if all(result["acceptance"].values()) else 1)
