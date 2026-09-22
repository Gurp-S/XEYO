"""Audit local Terminal-Bench evidence without changing or rerunning it.

The script only reads ``TerminalBench/run`` and tracked ``docs/BENCH-口径.md``.
It reports the raw reward distribution and provenance warnings; it does not
reinterpret a relay-union score as a single-engine score.
"""

from __future__ import annotations

import hashlib
import json
import re
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


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reward(path: Path) -> str:
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "invalid"
    verifier = data.get("verifier_result") or {}
    reward_block = verifier.get("rewards") or {}
    value = reward_block.get("reward")
    if value is None:
        value = data.get("reward")
    try:
        return str(float(value))
    except (TypeError, ValueError):
        return "missing"


def main() -> int:
    run_root = ROOT / "TerminalBench" / "run"
    result_files = sorted(run_root.rglob("result.json")) if run_root.is_dir() else []
    rewards = Counter(_reward(path) for path in result_files)
    tracked_doc = ROOT / "docs" / "BENCH-口径.md"
    ignored_report = ROOT / "TerminalBench" / "REPORT.md"
    ignored_resume = ROOT / "TerminalBench" / "秋招项目说明.md"
    tracked_text = tracked_doc.read_text(encoding="utf-8") if tracked_doc.is_file() else ""
    report_text = ignored_report.read_text(encoding="utf-8") if ignored_report.is_file() else ""

    result = {
        "schema_version": 1,
        "benchmark": "xeyo_terminalbench_provenance",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(),
        "sources": {
            "result_root": str(run_root),
            "result_root_exists": run_root.is_dir(),
            "result_json_count": len(result_files),
            "tracked_metric_doc": {
                "path": str(tracked_doc),
                "exists": tracked_doc.is_file(),
                "sha256": _sha256(tracked_doc),
            },
            "ignored_report": {
                "path": str(ignored_report),
                "exists": ignored_report.is_file(),
                "sha256": _sha256(ignored_report),
            },
            "ignored_resume_note": {
                "path": str(ignored_resume),
                "exists": ignored_resume.is_file(),
                "sha256": _sha256(ignored_resume),
            },
        },
        "raw_reward_distribution": dict(rewards),
        "tracked_doc_markers": {
            "relay_union_70_8": bool(re.search(r"接力并集口径", tracked_text)),
            "xeyo_increment_6_of_29": bool(re.search(r"20\.7%.*6/29|6（XEYO）", tracked_text)),
            "lower_bound_67_4": bool(re.search(r"67\.4%", tracked_text)),
        },
        "ignored_report_markers": {
            "claims_single_engine_63_of_89": bool(re.search(r"63\s*/\s*89\s*=\s*70\.8%", report_text)),
            "claims_n_attempts_one": bool(re.search(r"n_attempts=1", report_text)),
        },
        "conclusion": "Raw files exist locally, but tracked provenance defines 70.8% as relay union; do not write it as single-engine XEYO full-score evidence.",
    }
    output = ROOT / "benchmarks" / "resume_evidence" / "results" / "xeyo_terminalbench_provenance.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"raw_result={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
