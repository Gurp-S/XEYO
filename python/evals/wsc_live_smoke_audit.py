"""Read-only real-session WSC/usage inventory; no API calls or session writes."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def read_jsonl(path):
    data = path.read_bytes()
    return ([json.loads(line) for line in data.decode("utf-8-sig").splitlines() if line.strip()],
            {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})


def usage_summary(rows):
    seen, unique, duplicate = set(), [], 0
    for row in rows:
        identity = (row.get("request_id"), row.get("attempt")) if row.get("request_id") else None
        if identity is not None and identity in seen:
            duplicate += 1
            continue
        if identity is not None:
            seen.add(identity)
        unique.append(row)
    valid = [row for row in unique if type(row.get("prompt_tokens")) is int
             and type(row.get("cache_hit")) is int
             and 0 <= row["cache_hit"] <= row["prompt_tokens"] and row["prompt_tokens"] > 0]
    inputs = sum(row["prompt_tokens"] for row in valid)
    hits = sum(row["cache_hit"] for row in valid)
    valid_identities = {id(row) for row in valid}
    active = []
    previous = None
    for row in sorted(unique, key=lambda r: r.get("ts", 0)):
        if (previous and row.get("provider") == previous.get("provider")
                and row.get("model") == previous.get("model")
                and row.get("key_id") == previous.get("key_id")
                and 0 <= row.get("ts", 0) - previous.get("ts", 0) < 120
                and id(row) in valid_identities):
            active.append(row)
        previous = row
    active_inputs = sum(row["prompt_tokens"] for row in active)
    return {"logged_calls": len(unique), "duplicate_request_attempt_rows": duplicate,
            "valid_cache_usage_calls": len(valid), "input_tokens_sum": inputs,
            "cache_hit_sum": hits, "token_weighted_cache_hit_rate": hits / inputs if inputs else None,
            "peak_logged_prompt_tokens": max((r["prompt_tokens"] for r in valid), default=None),
            "active_same_model_key_calls": len(active),
            "active_same_model_key_hit_rate": sum(r["cache_hit"] for r in active) / active_inputs if active_inputs else None,
            "recorded_cost_cny_sum": sum(r.get("cost_cny", 0) or 0 for r in unique),
            "cost_source_counts": dict(Counter(r.get("cost_source", "unspecified") for r in unique)),
            "models": sorted({str(r.get("model")) for r in unique})}


def audit(root, since):
    from session.transcript_blobs import resolve_transcript_rows
    from session.surface import fold_surface_rows
    from synaptic.textutil import tool_use_blocks, tool_result_blocks
    from synaptic.todo_snapshot import latest_todo_snapshot
    evidence = []
    logs = {}
    for name in ("events.jsonl", "fold_events.jsonl", "c2_events.jsonl"):
        logs[name], receipt = read_jsonl(root / "usage" / name)
        evidence.append(receipt)
    events = [r for r in logs["events.jsonl"] if r.get("day", "") >= since]
    identities = sorted({str(r["session_id"]) for r in events if r.get("session_id")
                         and (root / "sessions" / (str(r["session_id"]) + ".jsonl")).is_file()})
    sessions = []
    for sid in identities:
        path = root / "sessions" / (sid + ".jsonl")
        rows, receipt = read_jsonl(path)
        evidence.append(receipt)
        rows = resolve_transcript_rows(rows, path)
        source = [dict(row, message_id=row.get("id")) for row in rows]
        working_path = path.with_suffix(".working.json")
        working = {}
        if working_path.exists():
            data = working_path.read_bytes()
            working = json.loads(data.decode("utf-8-sig"))
            evidence.append({"path": str(working_path), "bytes": len(data),
                             "sha256": hashlib.sha256(data).hexdigest()})
        selected = [r for r in events if r.get("session_id") == sid]
        folds = [r for r in logs["fold_events.jsonl"] if r.get("session_id") == sid
                 and r.get("day", "") >= since and r.get("fold") is True]
        c2 = [r for r in logs["c2_events.jsonl"] if r.get("session_id") == sid and r.get("day", "") >= since]
        calls = [use for row in source for use in tool_use_blocks(row)]
        compact_ids = {use.get("id") for use in calls if use.get("name") == "Compact"}
        results = [result for row in source for result in tool_result_blocks(row)]
        compact_successes = [r for r in results if r.get("tool_use_id") in compact_ids and not r.get("is_error")
                             and isinstance(r.get("execution"), dict) and r["execution"].get("status") == "ok"]
        active_surface = fold_surface_rows(source)
        snapshot = latest_todo_snapshot(active_surface)
        manifest = working.get("last_projection_manifest") or {}
        latest_prompt, latest_hit = working.get("last_prompt_tokens"), working.get("last_cache_hit_tokens")
        capacity = manifest.get("context_limit")
        title_path = path.with_suffix(".title.json")
        title = json.loads(title_path.read_text(encoding="utf-8-sig")) if title_path.exists() else None
        sessions.append({"session_id": sid, "title": title, "source_rows": len(source),
            "active_surface_rows": len(active_surface),
            "human_text_rows": sum(r.get("role") == "user" and isinstance(r.get("content"), str)
                                   and not r.get("note_key") for r in source),
            "usage_window_since": since, "usage": usage_summary(selected),
            "days": {day: usage_summary([r for r in selected if r.get("day") == day]) for day in sorted({r["day"] for r in selected})},
            "fold_events": folds, "c2_event_count": len(c2), "compact_call_count_all_history": len(compact_ids),
            "compact_success_receipt_count_all_history": len(compact_successes),
            "latest_snapshot": {"compact_cursor": working.get("compact_cursor"), "actual_prompt_tokens": latest_prompt,
                "cache_hit_tokens": latest_hit, "declared_capacity": capacity,
                "occupancy": latest_prompt / capacity if type(latest_prompt) is int and type(capacity) is int and capacity > 0 else None,
                "cache_hit_rate": latest_hit / latest_prompt if type(latest_hit) is int and type(latest_prompt) is int and latest_prompt > 0 else None,
                "request_admission": (working.get("wsc_timing_state") or {}).get("last_request_admission"),
                "projection_invariant_errors": manifest.get("invariant_errors"),
                "todo_observed": snapshot.observed, "active_count": snapshot.active_count,
                "checkpoint_present": snapshot.checkpoint is not None},
            "task_tool_counts": dict(Counter(use.get("name", "unknown") for use in calls if use.get("name") in {"TodoWrite", "Compact"}))})
    return {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "since": since,
            "scope": "Existing saved XEYO sessions with usage in the date window; historical logs and latest snapshots, not a controlled A/B",
            "sessions": sessions, "evidence": evidence,
            "limits": ["Cost values retain their recorded estimate label; no billing reconciliation.",
                       "No final provider request bodies in diagnostic captures; cache causality is unproven.",
                       "No fold in a session does not verify continuity after folding.",
                       "Fold and c2 events describe the same operation and are not added together."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--since", default="2026-10-07")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root, args.since)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"sessions": len(result["sessions"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
