"""import_waterfall — 旁路(P2):启动/首轮 import 成本瀑布。

零侵入:不修改任何源码,以 ``python -X importtime -c "import <target>"``
子进程量测,解析 stderr 的 import 计时,输出按自耗/累计耗时排序的 top-N。

用法:
    python scripts/import_waterfall.py engine.query_engine [--top 20] [--python py -3.11]
默认 python 用 ``sys.executable``;server/engine 有第三方依赖时应传项目解释器
(如 ``--python "py" --python-args "-3.11"``),否则 import 会在缺依赖处中断
并如实报错(不影响其它目标的量测)。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence

def _parse_line(ln: str) -> tuple[str, float, float] | None:
	"""解析 ``import time: self[us|ms] | cumulative | package``(3.12 前带 ms,3.13 起为 us)。"""
	if "import time:" not in ln:
		return None
	_, _, tail = ln.partition("import time:")
	parts = tail.split("|")
	if len(parts) < 3:
		return None

	def to_ms(tok: str) -> float | None:
		tok = tok.strip()
		num = tok.replace("ms", "").strip()
		try:
			v = float(num)
		except ValueError:
			return None
		return v / 1000.0 if "ms" not in tok else v

	self_ms = to_ms(parts[0])
	cum_ms = to_ms(parts[1])
	if self_ms is None or cum_ms is None:
		return None
	mod = parts[2].strip().split()[0] if parts[2].strip() else ""
	if not mod:
		return None
	return mod, self_ms, cum_ms


def measure(target: str, python: Sequence[str]) -> list[tuple[str, float, float]]:
	"""返回 [(module, self_ms, cumulative_ms)] 按累计降序。"""
	cmd = [*python, "-X", "importtime", "-c", f"import {target}"]
	proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
	if proc.returncode != 0:
		raise RuntimeError(
			f"import {target} failed (rc={proc.returncode}):\n"
			f"{proc.stderr[-1500:]}"
		)
	rows: list[tuple[str, float, float]] = []
	for ln in proc.stderr.splitlines():
		parsed = _parse_line(ln)
		if parsed is not None:
			rows.append(parsed)
	return rows


def main(argv: Sequence[str] | None = None) -> int:
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("target", help="要量测的顶层 import 目标(如 engine.query_engine)")
	ap.add_argument("--top", type=int, default=25, help="只显示 top-N")
	ap.add_argument(
		"--python", default=sys.executable, help="解释器路径/命令(默认 sys.executable)"
	)
	ap.add_argument("--python-args", default="", help="解释器附加参数(如 '-3.11')")
	args = ap.parse_args(argv)

	python = [args.python]
	if args.python_args:
		python += args.python_args.split()

	try:
		rows = measure(args.target, python)
	except RuntimeError as exc:
		print(exc, file=sys.stderr)
		return 1

	if not rows:
		print("no import rows captured", file=sys.stderr)
		return 2

	rows.sort(key=lambda r: r[2], reverse=True)
	total_cum = max(c for _, _, c in rows)
	print(f"import {args.target} -> cumulative total ~{total_cum:.1f} ms "
	      f"({len(rows)} modules)")
	print(f"{'self ms':>9} {'cum ms':>9}  module")
	shown = rows[: args.top]
	for mod, self_ms, cum_ms in shown:
		bar = "#" * max(1, int(cum_ms / max(total_cum, 0.001) * 40))
		print(f"{self_ms:9.1f} {cum_ms:9.1f}  {mod} {bar}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
