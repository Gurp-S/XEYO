"""Launch pytest from a JSON argv file (bulletproof on Windows)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
	if len(sys.argv) != 3:
		print("usage: _spawn_json.py <log> <args.json>", file=sys.stderr)
		return 2
	log = Path(sys.argv[1])
	args = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
	if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
		print("args.json must be a JSON string array", file=sys.stderr)
		return 2
	cmd = [sys.executable, "-m", "pytest", *args]
	proc = subprocess.run(
		cmd,
		cwd=str(Path(__file__).resolve().parent),
		capture_output=True,
		text=True,
		encoding="utf-8",
		errors="replace",
	)
	body = (proc.stdout or "") + (proc.stderr or "")
	if body and not body.endswith("\n"):
		body += "\n"
	log.write_text(body + f"EXIT={proc.returncode}\n", encoding="utf-8")
	return int(proc.returncode)


if __name__ == "__main__":
	raise SystemExit(main())
