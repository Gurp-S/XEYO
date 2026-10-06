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


def resolve_bridge_workspace(raw: str | None = None) -> str | None:
	"""把启动器的 XEYO_CWD 解析成"桥"用的物理工作区；None=home 级语义。

	启动器给的常是相对值（`.env` 里 `.`），而本进程 cwd 可能已被 pushd 到 `python/`：
	必须先物理解析；结果若是 python 包根（点击式启动的典型情形），回退到其父=仓库根。
	否则 `_memory_store` 只合并 home 段 ⇒ **工作区级开关（R3/R4 等）静默失效**——
	2026-10-05 活后端实测事故（env 里两键 source=default，bridged 集与 home 存储逐键相同）。
	"""
	value = (raw if raw is not None else os.environ.get("XEYO_CWD", "")).strip()
	if not value:
		return None
	try:
		from session.workspace_path import is_python_package_root, resolve_physical_cwd

		physical = resolve_physical_cwd(value)
		if is_python_package_root(physical):
			from cli.cwdutil import package_parent_workspace

			physical = package_parent_workspace() or ""
		return physical or None
	except (OSError, ValueError):
		return None  # 解析失败退回 home 级语义（与未设 XEYO_CWD 同路径）


def main() -> None:
	os.environ.setdefault("XEYO_REWIND_ENABLED", "1")
	# 记忆系统开关：把 settings.json 的 memory 段桥接到 os.environ（运行时各开关读 env）。
	# cwd 取当前工作区（若已设为 XEYO_CWD）或默认 home 级 settings。
	try:
		from memory.memory_switches import apply_to_environ, prune_stale

		# XEYO_CWD 常由启动器给相对值（.env 里 "."），而本进程 cwd 可能已被 pushd 到
		# python/：解析职责收在 `resolve_bridge_workspace`（含包根→父级回退；详见其
		# docstring——这是 2026-10-05"R3/R4 从未生效"事故的修复点）。解析成功后**发布**为
		# 物理路径（与 `cli serve` 的 `resolve_cwd` 同契约），供发射侧 cwd 兜底读取
		# （`wsc_projection._pinned`/`ref_path_for` 会读 XEYO_CWD）。
		ws = resolve_bridge_workspace()
		if ws:
			os.environ["XEYO_CWD"] = ws
		applied = apply_to_environ(ws)
		if applied:
			print("[xeyo] 应用记忆开关: " + ", ".join(f"{k}={v}" for k, v in applied.items()), flush=True)
		# 清理 settings.memory 里的已删残留键：运行时本就不读，留着会让同名键将来
		# 复活时静默继承旧值。无残留则零写入（不重写 settings.json）。
		pruned = prune_stale(ws)
		if pruned:
			print("[xeyo] 清理记忆开关残留键: " + ", ".join(pruned), flush=True)
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
