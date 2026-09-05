"""One-shot pytest runner that avoids shell quoting issues on Windows."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


def main() -> int:
	if len(sys.argv) < 3:
		print("usage: _run_batch.py <log> <pytest-args...>", file=sys.stderr)
		return 2
	log_path = Path(sys.argv[1])
	pytest_args = sys.argv[2:]
	log_path.parent.mkdir(parents=True, exist_ok=True)
	with log_path.open("w", encoding="utf-8") as logf:
		old_out, old_err = sys.stdout, sys.stderr
		sys.stdout = logf  # type: ignore[assignment]
		sys.stderr = logf  # type: ignore[assignment]
		try:
			code = int(pytest.main(pytest_args))
			print(f"EXIT={code}", flush=True)
		finally:
			sys.stdout = old_out
			sys.stderr = old_err
	return code


if __name__ == "__main__":
	raise SystemExit(main())
