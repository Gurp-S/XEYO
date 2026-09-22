"""Reproduce the XEYO usage-ledger arithmetic used by the resume audit.

The source log is read-only.  Set ``XEYO_USAGE_LOG`` to an explicit JSONL path,
or use the normal ``XEYO_USAGE_DIR/events.jsonl`` location.

Run from the repository root:

    py -3.11 benchmarks/resume_evidence/xeyo_usage_ledger_audit.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def _source_path() -> Path:
    explicit = os.environ.get("XEYO_USAGE_LOG", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    usage_dir = os.environ.get("XEYO_USAGE_DIR", "").strip()
    if usage_dir:
        return Path(usage_dir).expanduser() / "events.jsonl"
    return Path.home() / ".xeyo" / "usage" / "events.jsonl"


def _num(row: dict[str, Any], key: str) -> int:
    try:
        return max(0, int(row.get(key) or 0))
    except (TypeError, ValueError):
        return 0


def _ts_range(rows: list[dict[str, Any]]) -> dict[str, str | None]:
    values = []
    for row in rows:
        try:
            values.append(float(row.get("ts")))
        except (TypeError, ValueError):
            pass
    if not values:
        return {"first_utc": None, "last_utc": None}
    return {
        "first_utc": datetime.fromtimestamp(min(values), timezone.utc).isoformat(),
        "last_utc": datetime.fromtimestamp(max(values), timezone.utc).isoformat(),
    }


def main() -> int:
    source = _source_path()
    rows: list[dict[str, Any]] = []
    invalid_lines = 0
    if source.is_file():
        with source.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    invalid_lines += 1
                    continue
                if isinstance(row, dict):
                    rows.append(row)

    prompt_tokens = sum(_num(row, "prompt_tokens") for row in rows)
    cache_hit = sum(_num(row, "cache_hit") for row in rows)
    cache_miss = sum(_num(row, "cache_miss") for row in rows)
    cache_total = cache_hit + cache_miss
    hit_rate = cache_hit / cache_total if cache_total else None
    models = Counter(str(row.get("model") or "") for row in rows)

    result = {
        "schema_version": 1,
        "benchmark": "xeyo_usage_ledger_audit",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(),
        "source": {
            "path": str(source),
            "exists": source.is_file(),
            "line_count_valid_json_objects": len(rows),
            "invalid_lines": invalid_lines,
            **_ts_range(rows),
        },
        "definition": {
            "prompt_tokens": "sum(row.prompt_tokens)",
            "cache_hit": "sum(row.cache_hit)",
            "cache_miss": "sum(row.cache_miss)",
            "cache_hit_rate": "cache_hit / (cache_hit + cache_miss)",
        },
        "aggregate": {
            "prompt_tokens": prompt_tokens,
            "cache_hit": cache_hit,
            "cache_miss": cache_miss,
            "cache_input_total": cache_total,
            "cache_hit_rate": hit_rate,
            "cache_hit_rate_percent": round(hit_rate * 100, 6) if hit_rate is not None else None,
            "models": models,
        },
    }
    output = ROOT / "benchmarks" / "resume_evidence" / "results" / "xeyo_usage_ledger_audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"raw_result={output}")
    return 0 if source.is_file() and not invalid_lines else 1


if __name__ == "__main__":
    raise SystemExit(main())
