"""Offline paired getter benchmark; no provider calls or production changes."""
import argparse
import hashlib
import json
from pathlib import Path
from statistics import median
from time import perf_counter

from evals.wsc_source_contract import APPEND, source_messages
from evals.wsc_source_reader import SourceReader
from msgtypes.message import user_message, system_note, assistant_text_message
from session.message_store import MessageStore


def run(size, *, cached, cycles=20, reads=8):
    items = [user_message(f"fact {i}: " + "x" * 120) for i in range(size)]
    for i in range(0, size, 10):
        items[i] = system_note(f"state version {i}", key="state", fp=str(i))
    store = MessageStore(items)
    store.as_api_messages()
    reader = SourceReader()
    read = (lambda: reader.read(store, APPEND)) if cached else (lambda: source_messages(store, APPEND))
    elapsed = 0.0
    for turn in range(cycles):
        store.append(assistant_text_message(f"result {turn}"))
        start = perf_counter()
        for _ in range(reads):
            rows = read()
        elapsed += perf_counter() - start
        # Equality check excluded from timing, after every mutation boundary.
        assert rows == source_messages(store, APPEND)
    fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    return elapsed, fingerprint


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    points = []
    for size, reads in ((size, reads) for size in (100, 1000, 5000) for reads in (1, 3, 8)):
        baseline, reused = [], []
        for repeat in range(5):
            # Alternate ordering to reduce systematic warmup bias.
            result = {}
            for cached in ((False, True) if repeat % 2 == 0 else (True, False)):
                result[cached] = run(size, cached=cached, reads=reads)
            assert result[False][1] == result[True][1]
            baseline.append(result[False][0])
            reused.append(result[True][0])
        before, after = median(baseline), median(reused)
        points.append({"initial_rows": size, "reads_per_cycle": reads, "baseline_seconds": baseline, "reused_seconds": reused,
                       "baseline_median_seconds": before, "reused_median_seconds": after,
                       "median_elapsed_reduction_pct": 100 * (1 - after / before),
                       "final_source_sha256": result[False][1], "all_mutation_boundaries_equal": True})
    root = Path(__file__).resolve().parents[1]
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (Path(__file__), root / "evals/wsc_source_reader.py",
                        root / "session/compression_source.py", root / "memory/wsc_source_layout.py",
                        root / "evals/wsc_source_contract.py", root / "session/message_store.py")}
    payload = {"scope": "Synthetic local CPU benchmark; not task score, provider cache hit or paid cost",
               "cycles_per_repeat": 20, "reads_per_cycle": [1, 3, 8], "paired_repeats": 5,
               "input": "120-character ordinary facts with every tenth row an older state note; one assistant append per cycle",
               "source_hashes": hashes, "points": points}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps([{key: p[key] for key in ("initial_rows", "reads_per_cycle", "median_elapsed_reduction_pct")} for p in points]))


if __name__ == "__main__":
    main()
