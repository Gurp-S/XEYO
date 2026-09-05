"""运行：py -3.11 -m server"""

from __future__ import annotations

import os
import socket

import uvicorn

from server.portfile import (
	cleanup_stale_port_file,
	default_port_file,
	write_port_file,
)


def _pick_free_port(host: str, start: int, max_attempts: int = 50) -> int:
	"""从 start 起找一个可绑定的端口；找不到则抛错。"""
	for port in range(start, start + max_attempts):
		# 注意：探测时不要设 SO_REUSEADDR——Windows 下它允许重复绑定，
		# 会让被占用的端口误判为空闲。
		with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
			try:
				s.bind((host, port))
			except OSError:
				continue
			return port
	raise RuntimeError(f"no free port in range {start}..{start + max_attempts}")


def main() -> None:
	os.environ.setdefault("XEYO_REWIND_ENABLED", "1")
	# 记忆系统开关：把 settings.json 的 memory 段桥接到 os.environ（运行时各开关读 env）。
	# cwd 取当前工作区（若已设为 XEYO_CWD）或默认 home 级 settings。
	try:
		from memory.memory_switches import apply_to_environ

		ws = os.environ.get("XEYO_CWD", "").strip() or None
		applied = apply_to_environ(ws)
		if applied:
			print("[xeyo] 应用记忆开关: " + ", ".join(f"{k}={v}" for k, v in applied.items()), flush=True)
	except Exception:  # noqa: BLE001 — 启动失败不应阻断 server
		pass
	host = os.environ.get("XEYO_HTTP_HOST", "127.0.0.1")
	requested = int(os.environ.get("XEYO_HTTP_PORT", "8000"))

	# T30：先按 pid 判僵尸——port 文件里的进程已死则清掉旧文件（不 netstat 误杀）。
	try:
		if cleanup_stale_port_file():
			print("[xeyo] 清理了僵尸端口文件（pid 已不存在）。", flush=True)
	except Exception:
		pass

	try:
		port = _pick_free_port(host, requested, 50)
	except RuntimeError:
		# 全被占用则沿用配置端口，交给 uvicorn 报错
		port = requested

	if port != requested:
		print(
			f"[xeyo] 端口 {requested} 被占用，自动改用 {port}。"
			"（若属上一实例，GUI/客户端会经端口文件与健康检查自动跟随/复用）",
			flush=True,
		)
	# T30：文件升级为 {port, pid, started_at, engine_version}
	write_port_file(port, default_port_file())
	print(
		f"[xeyo] 后端监听 http://{host}:{port}（实际端口已写入 {default_port_file()}）",
		flush=True,
	)

	uvicorn.run(
		"server.app:app",
		host=host,
		port=port,
		# T39：单 worker 是硬约束——SessionPool busy 表 / TurnRunner / 租约
		# 全部进程内内存态，多 worker 会让互斥失效（横扩需先做外置 lease）。
		workers=1,
		reload=False,
		access_log=False,
		log_level="warning",
	)


if __name__ == "__main__":
	main()
