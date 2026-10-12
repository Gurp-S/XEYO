"""Read-only historical fold attribution; neighboring usage is not exact wire proof."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def audit(snapshot: Path, usage: Path) -> dict:
    captured = {path: path.read_bytes() for path in (snapshot, usage)}
    inventory = json.loads(captured[snapshot].decode("utf-8-sig"))
    receipts = [json.loads(line) for line in captured[usage].decode("utf-8-sig").splitlines() if line.strip()]
    events = []
    for session in inventory["sessions"]:
        rows = sorted((row for row in receipts if row.get("session_id") == session["session_id"]),
                      key=lambda row: row.get("ts", 0))
        for fold in session.get("fold_events", []):
            ts = fold["ts"]
            before = [row for row in rows if row.get("ts", 0) <= ts]
            after = [row for row in rows if row.get("ts", 0) > ts]
            def neighbor(row):
                if row is None:
                    return None
                return {**{key: row.get(key) for key in
                           ("ts", "request_id", "attempt", "provider", "model", "prompt_tokens")},
                        "seconds_from_fold": row.get("ts", 0) - ts}
            reason = fold.get("reason")
            events.append({**{key: fold.get(key) for key in
                              ("session_id", "ts", "day", "reason", "forced", "gate", "region_tokens",
                               "head_tokens", "tail_tokens", "prompt_tokens", "prompt_basis", "economics_basis")},
                           "attribution": "legacy_automatic_rule" if reason in ("size_gate_fold", "worth_fold")
                                          else "origin_unknown",
                           "previous_usage": neighbor(before[-1] if before else None),
                           "next_usage": neighbor(after[0] if after else None)})
    return {"scope": "folds in captured six-session inventory; usage neighbors from original ledger",
            "fold_count": len(events), "reason_counts": dict(Counter(row["reason"] for row in events)),
            "attribution_counts": dict(Counter(row["attribution"] for row in events)),
            "prompt_basis_counts": dict(Counter(row["prompt_basis"] or "absent" for row in events)),
            "events": events,
            "evidence": [{"path": str(path), "sha256": hashlib.sha256(data).hexdigest(),
                          "unchanged": path.read_bytes() == data} for path, data in captured.items()],
            "limits": ["region_tokens is a region estimate, not complete provider input",
                       "region_raw prompt basis is historical raw-material estimate, not vendor usage",
                       "timestamp neighbors do not prove exact request correlation or trigger capacity",
                       "forced events lack origin/revision proof; not classified as 85-percent admission",
                       "old offline probes may have written global usage markers; originals are retained"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--usage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.snapshot.resolve(), args.usage.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({key: report[key] for key in ("fold_count", "reason_counts", "attribution_counts", "prompt_basis_counts")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
