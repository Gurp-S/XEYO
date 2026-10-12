"""Local exact-recall audit of an emitted receipt reference; no provider call."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from evals.stale_goal_ab import tool_read
from evals.wsc_unfolded_source_ab import environment


def run(folder, call_id):
    folder = folder.resolve()
    input_path = folder / "input.json"
    original = input_path.read_bytes()
    messages = json.loads(original)
    head = messages[0]["content"]
    matches = []
    for line, reference in zip(head.splitlines(), head.splitlines()[1:]):
        if not line.startswith("- ") or not reference.startswith("  来源="):
            continue
        try:
            receipt = json.loads(line[2:])
        except ValueError:
            continue
        if receipt.get("call_id") == call_id:
            match = re.fullmatch(r"  来源=Read\(file_path='([^']*)', offset=(\d+), limit=(\d+)\)", reference)
            if match:
                matches.append((receipt, match))
    if len(matches) != 1:
        raise ValueError("receipt_reference_missing_or_ambiguous")
    receipt, match = matches[0]
    path = (folder / match[1]).resolve()
    if not path.is_relative_to(folder):
        raise ValueError("reference_outside_private_archive")
    view = path.read_bytes()
    lines = view.decode("utf-8").splitlines()
    start, limit = int(match[2]), int(match[3])
    original_lines = lines[start - 1:start - 1 + limit]
    with environment(folder):
        result = tool_read({"file_path": str(path), "offset": start, "limit": limit}, folder)
    text = str(result["content"])
    # These two lines are deliberately absent from the retained recent report.
    exact = {"read_description": next(line for line in original_lines if line.startswith("Read a text file")),
             "cleanup_line": next(line for line in original_lines if line.startswith("[cleanup]"))}
    hot = json.dumps(messages, ensure_ascii=False)
    report = {"scope": __doc__, "call_id": call_id, "source": receipt["source"],
              "receipt_result_inline": receipt.get("result_inline"),
              "read": {"file_path": str(path), "offset": start, "limit": limit},
              "expected": exact, "read_error": result["is_error"],
              "exact_lines_returned": {key: value in text for key, value in exact.items()},
              "exact_lines_in_initial_messages": {key: value in hot for key, value in exact.items()},
              "input_sha256": hashlib.sha256(original).hexdigest(),
              "input_unchanged": input_path.read_bytes() == original,
              "view_sha256": hashlib.sha256(view).hexdigest(),
              "view_unchanged": path.read_bytes() == view, "api_calls": 0}
    model_report_path = folder / "report.json"
    if model_report_path.is_file():
        model_report = json.loads(model_report_path.read_text(encoding="utf-8"))
        answer = (model_report.get("answer") or "").strip()
        if answer.startswith("```json\n"):
            answer = answer[len("```json\n"):].split("```", 1)[0]
        try:
            observed = json.loads(answer)
        except ValueError:
            observed = None
        model_reads = model_report.get("reads", [])
        def correct_read(row):
            args = row.get("input", {})
            actual = Path(args.get("file_path", ""))
            if not actual.is_absolute():
                actual = folder / actual
            return (row.get("name") == "Read" and actual.resolve() == path
                    and args.get("offset") == start and args.get("limit") == limit
                    and not row.get("result", {}).get("is_error", True)
                    and all(value in str(row.get("result", {}).get("content", "")) for value in exact.values()))
        report["model_acceptance"] = {"error": model_report.get("error"),
            "read_count": len(model_reads), "correct_source_read": any(correct_read(row) for row in model_reads),
            "exact_answer": isinstance(observed, dict) and all(observed.get(key) == value for key, value in exact.items()),
            "evidence_identity": isinstance(observed, dict) and observed.get("evidence_call_id") == call_id}
    (folder / "cold-receipt-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--call-id", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.folder, args.call_id), ensure_ascii=False))
