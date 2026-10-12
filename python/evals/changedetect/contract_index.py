"""Source-backed pin lookup: candidate references never imply a test will fail."""
import argparse
import json
from pathlib import Path


def query(subject, root=None):
    root = Path(root) if root else Path(__file__).resolve().parents[3]
    if not subject.strip():
        raise ValueError("missing_subject")
    candidates = []
    for directory in (root / "python/tests", root / "python/evals/changedetect/goldens"):
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".txt", ".json"}:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if subject in line:
                    candidates.append({"path": path.relative_to(root).as_posix(), "line": number,
                                       "kind": "golden_reference" if "goldens" in path.parts else "static_candidate"})
    return {"subject": subject, "references": candidates,
            "runtime_dependents": "unknown", "predicted_failures": "unknown"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("subject")
    args = parser.parse_args()
    print(json.dumps(query(args.subject), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
