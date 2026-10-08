"""Machine-readable offline gate. Failed or unexecuted stages cannot pass."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    run = args.output or root / "_wsc_out" / "gate" / str(time.time_ns())
    run.mkdir(parents=True, exist_ok=True)
    stages = []
    if not args.skip_install:
        stages.extend([("python-install", "python", ["py", "-3.11", "-m", "pip", "install", "-q", "-r", "requirements.txt"]),
                       ("python-dev", "python", ["py", "-3.11", "-m", "pip", "install", "-q", "-e", ".[dev]"])])
    stages.extend([("python-tests", "python", ["py", "-3.11", "-m", "pytest", "-q", "--timeout=60", "-m", "not live"]),
                   ("manifest", "python", ["py", "-3.11", "-m", "slash.export_manifest", "--check"]),
                   ("changedetect", "python", ["py", "-3.11", "-m", "evals.changedetect", "check", "--json"])])
    for directory in ("gui", "tui"):
        if not (root / directory / "node_modules").exists():
            stages.append((directory + "-install", directory, ["npm.cmd", "ci"]))
        stages.append((directory + "-types", directory, ["npm.cmd", "run", "typecheck"]))
        if directory == "gui":
            stages.append(("gui-tests", directory, ["npm.cmd", "test"]))
    results = []
    for name, directory, argv in stages:
        start = time.monotonic()
        logfile = run / (name + ".log")
        try:
            with logfile.open("wb") as out:
                process = subprocess.run(argv, cwd=root / directory, stdout=out, stderr=subprocess.STDOUT, timeout=1800)
            status, code = ("passed" if process.returncode == 0 else "failed"), process.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            status, code = "incomplete", None
            with logfile.open("ab") as out:
                out.write(type(exc).__name__.encode())
        results.append({"stage": name, "status": status, "exit_code": code,
                        "seconds": round(time.monotonic() - start, 3), "log": str(logfile)})
        (run / "progress.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = all(r["status"] == "passed" for r in results)
    report = {"schema_version": 1, "status": "passed" if passed else "failed", "stages": results}
    (run / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
