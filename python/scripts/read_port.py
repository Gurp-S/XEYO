"""T30：读取 .xeyo/backend_port（JSON {port,pid,...}，兼容旧纯数字）并打印字段。

用法: py -3.11 scripts/read_port.py [portfile] [--pid]
默认打印 port；--pid 打印 pid（旧格式无 pid 时退出码 1，调用方跳过清理）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.portfile import read_port_file  # noqa: E402


def main() -> int:
	path: Path | None = None
	want_pid = False
	for arg in sys.argv[1:]:
		if arg == "--pid":
			want_pid = True
		elif arg.strip():
			path = Path(arg)
	data = read_port_file(path)
	if data is None:
		return 1
	key = "pid" if want_pid else "port"
	value = data.get(key)
	if isinstance(value, int) and value > 0:
		print(value)
		return 0
	return 1


if __name__ == "__main__":
	raise SystemExit(main())
