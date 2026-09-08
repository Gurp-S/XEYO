"""轮询 /health 直至 OK 或超时。用法: py -3.11 scripts/wait_health.py URL [seconds] [portfile]

URL 中可带 {PORT} 占位符；若给定了 portfile，则每轮重新读取该文件里的实际端口，
并在替换 {PORT} 后再请求。端口文件尚未写入时本轮跳过，下次再试，
处理「后端端口被占用自动挪动/端口文件写入有延迟」的情况。
T30：端口文件升级为 JSON {port, pid, ...}——兼容旧纯数字格式。
"""
from __future__ import annotations

import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
	from server.portfile import read_port_file
except Exception:  # 脚本独立运行时容忍导入失败，走旧文本解析
	read_port_file = None  # type: ignore[assignment]


def _read_port(path: Path) -> str:
	if read_port_file is not None:
		data = read_port_file(path)
		if data and isinstance(data.get("port"), int):
			return str(data["port"])
		return ""
	try:
		return path.read_text(encoding="utf-8").strip()
	except OSError:
		return ""


def main() -> int:
	url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/health"
	deadline = time.monotonic() + float(sys.argv[2] if len(sys.argv) > 2 else "25")
	port_file = Path(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else None

	while time.monotonic() < deadline:
		target = url
		if port_file is not None and "{PORT}" in target:
			port = _read_port(port_file)
			if port:
				target = target.replace("{PORT}", port)

		if "{PORT}" in target:
			# 仍拿不到端口：先等下一轮再探测
			time.sleep(0.2)
			continue

		try:
			with urllib.request.urlopen(target, timeout=0.8) as res:
				if 200 <= getattr(res, "status", 200) < 300:
					return 0
		except Exception:
			# 后端尚未就绪/网络抖动/端口未就绪：继续轮询
			pass
		time.sleep(0.2)
	return 1


if __name__ == "__main__":
	raise SystemExit(main())
