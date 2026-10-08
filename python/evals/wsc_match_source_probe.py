"""Read-only positional match probe on a reconstructed real-source cold view."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from evals.wsc_recall_executor import RecallExecutor


def run(view, output):
    view, output = Path(view).resolve(), Path(output).resolve()
    original = view.read_bytes()
    lines = original.decode("utf-8").splitlines()
    chosen = None
    for number, line in enumerate(lines, 1):
        if len(line) < 600:
            continue
        for match in re.finditer(r"\b[A-Za-z_][A-Za-z_0-9-]*\.py\b", line):
            token = match.group()
            if line.find(token) > 500:
                chosen = number, match.start(), token
                break
        if chosen:
            break
    if not chosen:
        raise ValueError("real_view_has_no_matching_long_line_probe")
    number, position, token = chosen
    matches = [(index, match.start()) for index, line in enumerate(lines, 1)
        for match in re.finditer(re.escape(token), line)]
    ordinal = matches.index((number, position))
    previous = os.environ.get("XEYO_WSC_TASK_CONTINUITY")
    try:
        os.environ["XEYO_WSC_TASK_CONTINUITY"] = "1"
        executor = RecallExecutor(view.parent, "read_search")
        old = executor.execute("Grep", {"path": str(view), "pattern": re.escape(token), "output_mode": "content",
            "head_limit": 0})
        new = executor.execute("Grep", {"path": str(view), "pattern": re.escape(token), "output_mode": "matches",
            "head_limit": 1, "offset": ordinal})
        record = json.loads(new["content"].splitlines()[0]) if not new["is_error"] else {}
        expected_column = len(lines[number-1][:position].encode("utf-8")) + 1
        old_rows = [line for line in old["content"].splitlines()
            if line.startswith(f"{number}:") or line.startswith(f"{view.name}:{number}:")]
        old_visible = any(token in line for line in old_rows)
        report = {"scope": "product Grep on an unchanged real-source reconstructed view; different mode pagination units accounted for; no model call",
            "view_sha256": hashlib.sha256(original).hexdigest(), "public_filename_token": token,
            "source_line": number, "expected_byte_column": expected_column,
            "legacy_target_row_present": bool(old_rows), "legacy_excerpt_contains_match": old_visible, "native_record": record,
            "acceptance": {"legacy_truncation_reproduced": not old["is_error"] and bool(old_rows) and not old_visible,
                "native_literal_preserved": record.get("text") == token and record.get("text_complete") is True,
                "native_position_exact": record.get("line") == number and record.get("byte_column") == expected_column,
                "view_unchanged": original == view.read_bytes()}}
        output.mkdir(parents=True, exist_ok=True)
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report
    finally:
        if previous is None:
            os.environ.pop("XEYO_WSC_TASK_CONTINUITY", None)
        else:
            os.environ["XEYO_WSC_TASK_CONTINUITY"] = previous


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("view")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run(args.view, args.output)
    print(json.dumps(report, ensure_ascii=False))
    sys.exit(0 if all(report["acceptance"].values()) else 1)
