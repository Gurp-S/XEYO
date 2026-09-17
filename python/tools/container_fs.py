# -*- coding: utf-8 -*-
"""容器工作面文件原语：让**文件工具落在模型真正的工作面**上。

## 为什么需要

引擎跑在宿主进程，``Bash`` 经容器路由（``XEYO_DOCKER_CONTAINER`` / ContextVar）
落进容器；而 ``Write`` / ``Edit`` / ``Glob`` / ``Grep`` 走宿主 ``pathlib``。
两者不一致时出现**静默错位**——最坏的一种失败：

- ``Write`` 报告成功，文件却落在宿主空 scratch 目录，判分（在容器里）永远看不见；
- ``Glob``/``Grep`` 报"没找到"，而文件明明在容器里；
- ``Edit`` 报"文件不存在"，模型据此改用 Bash 重写整个文件。

这与 ``tools/exec_channel.py`` 是同一类问题的两面：那边修的是引擎的**观测**，
这边修的是模型的**动作**。该模块原名注释已指明纪律——"把观测与动作统一到
同一条通道"。

## 语义（三条纪律，与 exec_channel 对齐）

1. **宿主路由零改变**：无容器路由时，本模块的每个函数都退化为直接文件系统
   调用，行为与调用方原先的实现逐字节一致。
2. **失败响亮**：容器内操作失败返回 `None` / 抛 `OSError`，**绝不**静默回落宿主
   ——"静默错位"正是要被消灭的失败形态。
3. **二进制安全**：写文件走 base64 单条命令（不经 shell 插值正文，避免引号/
   换行/编码把内容改坏）。

## 边界

本模块只管**文件字节**；不做权限判断、不写 journal、不做语法门——那些留在
调用方（``write_store`` / 各工具）既有路径上，顺序与语义不变。
"""

from __future__ import annotations

import base64
import re
import os
import threading

__all__ = [
	"active_container",
	"container_exec",
	"exists",
	"glob_paths",
	"mtime_ms",
	"read_bytes",
	"read_text",
	"run_argv",
	"to_container_path",
	"write_bytes",
	"write_text",
]

#: 单次容器文件操作超时（秒）。文件读写应当快；慢说明路由出了问题，早失败。
OP_TIMEOUT_S = 30.0


_DRIVE_ABS = re.compile(r"^[A-Za-z]:[\\/]")


def _host_shaped_to_container(token: str) -> str:
	"""把宿主形态的**绝对**路径纠正为容器 POSIX 形态。

	为什么需要：工具层普遍用 ``os.path.abspath``/``Path`` 规范化路径，在 Windows
	宿主上会把容器路径 ``/app/src`` 变成 ``D:\\app\\src``。这种字符串喂给容器 shell
	必然找不到——实测 Grep 回退路径就是这样报 ``D:\\app\\src: No such file``。

	**只认驱动器绝对路径**（``X:\\`` / ``X:/``）。刻意**不**处理单个反斜杠开头的形态
	（``\\app\\src``）：那与正则转义序列无法区分，实测该启发式会把 ``\\bPASSWORD\\b``
	改成 ``/bPASSWORD/b``——静默改坏搜索模式，比"容器里报找不到文件"坏得多。
	"""
	if _DRIVE_ABS.match(token):
		return "/" + token[3:].replace("\\", "/")
	return token


def run_argv(
	argv: list[str], *, cwd: str | None = None, timeout_s: float = OP_TIMEOUT_S
) -> tuple[int, str, str] | None:
	"""在容器内按 argv 执行（**不经宿主 shell 拼串**，参数各自单引号转义）。

	返回 ``(退出码, stdout, stderr)``（流分开——见 ``container_exec`` 的说明）。
	供 Glob / Grep 这类"宿主上跑 CLI 工具"的实现复用：命令语义与宿主分支
	逐字一致，只换执行场所。不可达 → ``None``。
	"""
	parts = " ".join(_sq(_host_shaped_to_container(str(a))) for a in argv)
	prefix = f"cd {_sq(to_container_path(cwd))} && " if cwd else ""
	result = container_exec(prefix + parts, timeout_s=timeout_s, separate=True)
	return result  # type: ignore[return-value]


def active_container() -> str:
	"""当前活动路由的容器 id；宿主路由返回空串。"""
	try:
		from tools.container_routing import current_container

		cid = current_container()
	except Exception:  # noqa: BLE001 — 路由模块不可用视为宿主
		cid = ""
	return (cid or os.environ.get("XEYO_DOCKER_CONTAINER", "") or "").strip()


def container_exec(
	command: str, *, timeout_s: float = OP_TIMEOUT_S, separate: bool = False
) -> tuple[int, str] | tuple[int, str, str] | None:
	"""在活动容器内执行 ``bash -lc <command>``；不可达/超时 → ``None``。

	``separate=True`` 时返回 ``(退出码, stdout, stderr)``——**stdout/stderr 必须能
	分开**：Task 镜像里常常没有 ``rg``，把它俩合并会让 `bash: rg: command not
	found` 被当成搜索结果（静默错答）。
	"""
	cid = active_container()
	if not cid:
		return None
	box: dict = {}

	def _worker() -> None:
		try:
			import docker

			client = docker.from_env()
			res = client.containers.get(cid).exec_run(["bash", "-lc", command], demux=True)
			out_b, err_b = res.output
			box["r"] = (
				int(res.exit_code or 0),
				(out_b or b"").decode("utf-8", "replace"),
				(err_b or b"").decode("utf-8", "replace"),
			)
		except Exception:  # noqa: BLE001
			box["r"] = None

	thread = threading.Thread(target=_worker, name="container-fs", daemon=True)
	thread.start()
	thread.join(timeout_s)
	got = box.get("r")
	if got is None:
		return None
	if separate:
		return got
	return (got[0], got[1] + got[2])


def _sq(value: str) -> str:
	"""POSIX 单引号转义。"""
	return "'" + str(value).replace("'", "'\"'\"'") + "'"


def to_container_path(path: object) -> str:
	"""把调用方给的路径转成容器内可用的 POSIX 形态。

	为什么要转（两个都实测撞过）：
	1. **反斜杠**：Windows 上 ``Path("/tmp/x")`` 会被规范化成 ``\\tmp\\x``，
	   ``str()`` 出来带反斜杠，塞进 ``bash -lc`` 就是"文件名里有反斜杠"的怪路径。
	2. **驱动器前缀**：工具层普遍用 ``os.path.abspath``，会把容器路径
	   ``/app/src`` 变成 ``D:\\app\\src``。只翻斜杠会得到 ``D:/app/src``，容器里
	   仍然找不到（Read 实测报 "File does not exist in the container"）。

	本函数只处理**路径**（不处理 argv 里的正则等任意串，那由
	``_host_shaped_to_container`` 用更保守的规则处理）。
	"""
	raw = str(path)
	if os.name == "nt":
		raw = raw.replace("\\", "/")
		match = re.match(r"^[A-Za-z]:(/.*)$", raw)
		if match:
			raw = "/" + match.group(1).lstrip("/")
	return raw


def read_text(path: str) -> str | None:
	"""读文件文本（容器路由 → 容器内读；否则宿主读）。

	容器内不存在 → ``None``。宿主路由下与 ``Path.read_text`` 同语义。
	"""
	cid = active_container()
	if not cid:
		try:
			with open(os.path.expanduser(path), "r", encoding="utf-8", errors="replace") as fh:
				return fh.read()
		except OSError:
			return None
	probed = container_exec(f"cat -- {_sq(to_container_path(path))}")
	if probed is None or probed[0] != 0:
		return None
	return probed[1]


def write_text(path: str, content: str) -> bool:
	"""整文写入（容器路由 → base64 解码落容器；否则宿主原子写）。

	返回是否成功。容器分支失败返回 ``False``（**不回落宿主**）。
	"""
	cid = active_container()
	if not cid:
		try:
			target = os.path.expanduser(path)
			parent = os.path.dirname(target)
			if parent:
				os.makedirs(parent, exist_ok=True)
			with open(target, "w", encoding="utf-8", newline="") as fh:
				fh.write(content)
			return True
		except OSError:
			return False
	cpath = to_container_path(path)
	payload = base64.b64encode(content.encode("utf-8")).decode("ascii")
	parent = os.path.dirname(cpath).replace("\\", "/")
	script = (
		(f"mkdir -p -- {_sq(parent)} && " if parent else "")
		+ f"printf %s {_sq(payload)} | base64 -d > {_sq(cpath)}"
	)
	probed = container_exec(script)
	return bool(probed is not None and probed[0] == 0)


def read_bytes(path: str) -> bytes | None:
	"""读文件原始字节（容器路由 → 容器内 base64 取回）。不存在 → ``None``。

	给 ``fileio.text.read_text_file`` 用：编码检测（UTF-16 BOM）必须在**字节层**
	做，拿字符串是检不出来的。
	"""
	cid = active_container()
	if not cid:
		try:
			with open(os.path.expanduser(path), "rb") as fh:
				return fh.read()
		except OSError:
			return None
	probed = container_exec(f"base64 -w0 -- {_sq(to_container_path(path))}")
	if probed is None or probed[0] != 0:
		return None
	try:
		return base64.b64decode(probed[1].strip() or "")
	except Exception:  # noqa: BLE001
		return None


def write_bytes(path: str, data: bytes) -> bool:
	"""写原始字节（容器路由 → base64 解码落容器）。失败返回 ``False``。"""
	cid = active_container()
	if not cid:
		try:
			target = os.path.expanduser(path)
			parent = os.path.dirname(target)
			if parent:
				os.makedirs(parent, exist_ok=True)
			with open(target, "wb") as fh:
				fh.write(data)
			return True
		except OSError:
			return False
	cpath = to_container_path(path)
	parent = os.path.dirname(cpath)
	payload = base64.b64encode(data).decode("ascii")
	script = (
		(f"mkdir -p -- {_sq(parent)} && " if parent else "")
		+ f"printf %s {_sq(payload)} | base64 -d > {_sq(cpath)}"
	)
	probed = container_exec(script)
	return bool(probed is not None and probed[0] == 0)


def mtime_ms(path: str) -> int | None:
	"""毫秒级 mtime（容器路由 → 容器内 stat）。不可观测 → ``None``。"""
	cid = active_container()
	if not cid:
		try:
			return int(os.path.getmtime(os.path.expanduser(path)) * 1000)
		except OSError:
			return None
	probed = container_exec(f"stat -c %Y -- {_sq(to_container_path(path))} 2>/dev/null")
	if probed is None or probed[0] != 0:
		return None
	raw = probed[1].strip().splitlines()
	if not raw:
		return None
	try:
		return int(float(raw[0])) * 1000
	except ValueError:
		return None


def display_cwd(cwd: str) -> str:
	"""模型可见的工作目录：容器路由下返回**容器内**的 pwd，否则原样返回宿主 cwd。

	单一口径（2026-09-16）：系统提示词左段与各文件工具的错误文案都走这里，
	否则会出现"提示词说 /app、错误说 D:\\..."的自相矛盾——模型会照后者去试。

	不可观测（路由异常 / 探测失败）→ 回落宿主 cwd（= 改动前行为）。
	"""
	if not active_container():
		return cwd
	try:
		from tools.exec_channel import model_workspace

		display, _entries = model_workspace(cwd)
		if display:
			return str(display)
	except Exception:  # noqa: BLE001 — 探测失败绝不挡文案生成
		pass
	return cwd


def is_dir(path: str) -> bool | None:
	"""是否为目录（容器路由 → 容器内 test -d）。不可观测 → ``None``。"""
	cid = active_container()
	if not cid:
		try:
			return os.path.isdir(os.path.expanduser(path))
		except OSError:
			return None
	probed = container_exec(f"test -d {_sq(to_container_path(path))} && echo Y || echo N")
	if probed is None or probed[0] != 0:
		return None
	return probed[1].strip().endswith("Y")


def exists(path: str) -> bool | None:
	"""路径是否存在（容器路由 → 容器内 test -e）。不可观测 → ``None``。"""
	cid = active_container()
	if not cid:
		try:
			return os.path.exists(os.path.expanduser(path))
		except OSError:
			return None
	probed = container_exec(f"test -e {_sq(to_container_path(path))} && echo Y || echo N")
	if probed is None or probed[0] != 0:
		return None
	return probed[1].strip().endswith("Y")


def _split_glob(pattern: str) -> tuple[str, str]:
	"""拆出 ``(find 根目录, -name 模式)``：根 = 第一个含通配符之前的部分。

	``/tmp/**/*.txt`` → ``("/tmp", "*.txt")``；``/app/*.py`` → ``("/app", "*.py")``。
	``**`` 段按"任意深度"处理（find 默认递归，语义等价）。
	"""
	norm = to_container_path(pattern)
	parts = [p for p in norm.split("/") if p not in ("", ".")]
	root: list[str] = []
	name = "*"
	for i, seg in enumerate(parts):
		if any(ch in seg for ch in "*?["):
			name = parts[-1] if i < len(parts) - 1 else seg
			# 取通配符之后的最后一段作为 -name（前面的通配段视为任意深度）
			for later in reversed(parts[i:]):
				if not any(ch in later for ch in "*?[") or later == parts[-1]:
					name = later
					break
			break
		root.append(seg)
	base = "/" + "/".join(root) if root else "/"
	if not any(ch in name for ch in "*?["):
		name = "*"
	return base, name


def glob_paths(pattern: str, *, root: str = "/", limit: int = 500) -> list[str] | None:
	"""容器内按 glob 展开（``find`` 实现，按 mtime 倒序）。不可观测 → ``None``。"""
	cid = active_container()
	if not cid:
		import glob as _glob

		try:
			return sorted(_glob.glob(os.path.expanduser(str(pattern))))[:limit]
		except OSError:
			return None
	base, name = _split_glob(str(pattern))
	probed = container_exec(
		f"find {_sq(base)} -maxdepth 8 -name {_sq(name)} -type f "
		f"-printf '%T@ %p\\n' 2>/dev/null | sort -rn | head -n {int(limit)} | cut -d' ' -f2-"
	)
	if probed is None:
		return None
	if probed[0] != 0:
		return []
	return [line for line in probed[1].splitlines() if line.strip()]
