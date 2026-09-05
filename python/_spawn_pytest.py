"""Launch pytest with a proper argv list (avoids PowerShell Start-Process quoting bugs)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
	if len(sys.argv) < 3:
		print("usage: _spawn_pytest.py <log> -- <pytest args...>", file=sys.stderr)
		return 2
	log = Path(sys.argv[1])
	try:
		sep = sys.argv.index("--")
	except ValueError:
		print("missing -- separator", file=sys.stderr)
		return 2
	pytest_args = sys.argv[sep + 1 :]
	cmd = [sys.executable, "-m", "pytest", *pytest_args]
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
