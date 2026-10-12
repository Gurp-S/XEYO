"""Compare failure identities, not whole-run exit codes. CLI consumes run JSON."""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def read_junit(path):
    root = ET.parse(path).getroot()
    cases = {}
    for case in root.iter("testcase"):
        identity = case.get("classname", "") + "::" + case.get("name", "")
        if identity in cases:
            raise ValueError(f"duplicate_test_identity: {identity}")
        failure = case.find("failure")
        if failure is None:
            failure = case.find("error")
        skipped = case.find("skipped")
        status = "failed" if failure is not None else "skipped" if skipped is not None else "passed"
        detail = "" if failure is None else failure.get("message", "") + "\n" + (failure.text or "")
        cases[identity] = {"status": status, "failure_sha256": hashlib.sha256(detail.encode()).hexdigest() if detail else None}
    return cases


def compare_runs(baseline, current):
    required = ("test_manifest_id", "environment_id")
    comparable = bool(baseline.get("source_id") and current.get("source_id")) and all(
        baseline.get(key) and baseline.get(key) == current.get(key) for key in required)
    out = {"comparable": comparable, "baseline_source": baseline.get("source_id"),
           "current_source": current.get("source_id"), "tests": {}}
    for name in sorted(set(baseline["tests"]) | set(current["tests"])):
        left, right = baseline["tests"].get(name), current["tests"].get(name)
        if left is None or right is None:
            state = "missing_in_baseline" if left is None else "missing_in_current"
        elif not comparable:
            state = "not_comparable"
        elif right["status"] == "failed":
            if left["status"] != "failed":
                state = "new_failure"
            elif not left.get("failure_sha256") or not right.get("failure_sha256"):
                state = "not_comparable"
            elif left.get("failure_sha256") == right.get("failure_sha256"):
                state = "same_failure"
            else:
                state = "changed_failure"
        elif left["status"] == "failed" and right["status"] == "passed":
            state = "fixed"
        else:
            state = "unchanged" if left["status"] == right["status"] else "changed_status"
        out["tests"][name] = state
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("current", type=Path)
    args = parser.parse_args()
    result = compare_runs(json.loads(args.baseline.read_text(encoding="utf-8-sig")),
                          json.loads(args.current.read_text(encoding="utf-8-sig")))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if not result["comparable"] or any(value not in {"unchanged", "fixed", "same_failure"}
             for value in result["tests"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
