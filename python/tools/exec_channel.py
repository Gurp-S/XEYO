"""观测域一致性原语——引擎的「看」必须与模型的动作走同一条通道。

## 为什么需要

引擎会在若干处对模型声明磁盘事实（产物是否落盘、工作区里有什么）。这些核对
此前一律走**宿主**文件系统（``Path.exists`` / ``os.listdir``）；而模型的动作可能
经由**容器路由**（``XEYO_DOCKER_CONTAINER`` / ``ContextVar`` 覆盖）落到另一个
文件系统。两者不一致时，引擎会输出**自己都证不了的断言**：

- 容器路由下 ``todo_write_tool`` 把容器内 ``/app/*`` 产物判成"磁盘上不存在"；
- 容器路由下 ``first_sniff`` 把宿主空 scratch 当成工作区，注入 ``(空目录)``。

这不是评测专属缺陷——只要工作面不在宿主（容器 / WSL / 远程 / 沙盒工作区），
同一错误必然复现。修法不是"评测时跳过"，而是**把观测与动作统一到同一条通道**。

## 语义（三条纪律）

1. **可观测才说话**：``None`` 表示"本通道看不到"，调用方**必须沉默**——
   不猜测、不降级为宿主结果、不编造"不存在"。
2. **宿主路径字节级等价**：未设置容器路由时，本模块与直接 ``os``/``pathlib``
   的行为、返回值、异常语义完全一致（旧行为零改变）。
3. **链路 fail-open**：探测异常/超时 → ``None``（沉默），绝不抛给调用方。

容器分支自带超时（默认 5s）并显式指定 ``bash -lc``——只读探针必须**有界且同步**，
因此**刻意不复用** bash_tool 的 ``_docker_exec_with_timeout``（那条路带 promote
后台化语义，不适合探针，且属于主执行路径不宜改动）。
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

__all__ = [
	"active_container",
	"list_dir",
	"model_workspace",
	"read_text",
	"stat_path",
]

PROBE_TIMEOUT_S = 5.0
_TERMINAL = 95


def active_container() -> str:
	"""当前活动路由的容器 id；宿主路由返回空串。"""
	try:
		from tools.container_routing import current_container

		cid = current_container()
	except Exception:  # noqa: BLE001 — 路由模块不可用视为宿主
		cid = ""
	return (cid or os.environ.get("XEYO_DOCKER_CONTAINER", "") or "").strip()


def _sh_quote(value: str) -> str:
	return "'" + str(value).replace("'", "'\"'\"'") + "'"


def _probe(cid: str, command: str, timeout_s: float = PROBE_TIMEOUT_S) -> tuple[int, str] | None:
	"""同步只读探针。返回 (退出码, 输出)；不可观测（异常/超时）→ None。"""

	box: dict[str, tuple[int, str] | None] = {}

	def _worker() -> None:
		try:
			import docker

			client = docker.from_env()
			res = client.containers.get(cid).exec_run(["bash", "-lc", command], demux=True)
			out_b, err_b = res.output
			text = ((out_b or b"") + (err_b or b"")).decode("utf-8", "replace")
			box["r"] = (int(res.exit_code or 0), text)
		except Exception:  # noqa: BLE001 — 探针失败一律不可观测
			box["r"] = None

	thread = threading.Thread(target=_worker, name="exec-channel-probe", daemon=True)
	thread.start()
	thread.join(timeout_s)
	return box.get("r")


def _kind_map(kind_char: str) -> str:
	if kind_char == "d":
		return "d"
	if kind_char == "l":
		return "l"
	if kind_char in ("f", "-"):
		return "f"
	return "?"


def list_dir(path: str) -> list[tuple[str, str]] | None:
	"""活动路由下列出 ``path`` 顶层条目 → ``[(name, kind)]``，kind ∈ d/f/l/?。

	不可观测（路径不存在 / 无权限 / 路由失败 / 超时）→ ``None``。
	"""

	if not path:
		return None
	cid = active_container()
	if not cid:
		try:
			root = os.path.abspath(path)
			entries: list[tuple[str, str]] = []
			with os.scandir(root) as it:
				for entry in it:
					try:
						if entry.is_dir(follow_symlinks=False):
							kind = "d"
						elif entry.is_file(follow_symlinks=False):
							kind = "f"
						elif entry.is_symlink():
							kind = "l"
						else:
							kind = "?"
					except OSError:
						kind = "?"
					entries.append((entry.name, kind))
			return entries
		except OSError:
			return None

	quoted = _sh_quote(path)
	# GNU find 精确给出类型字母；不支持的镜像回退 ls -F 后缀。
	found = _probe(cid, f"find {quoted} -maxdepth 1 -mindepth 1 -printf '%y\\t%f\\n' 2>/dev/null")
	if found is not None and found[0] == 0 and found[1].strip():
		entries = []
		for line in found[1].splitlines():
			raw = line.rstrip("\n")
			if "\t" not in raw:
				continue
			kind_char, name = raw.split("\t", 1)
			name = name.strip()
			if not name or name in (".", ".."):
				continue
			entries.append((name, _kind_map(kind_char.strip())))
		if entries:
			return entries
	listed = _probe(cid, f"ls -1aF -- {quoted} 2>/dev/null")
	if listed is None:
		return None
	if listed[0] != 0:
		return None
	entries = []
	for raw in listed[1].splitlines():
		name = raw.rstrip("\n").strip()
		if not name or name in (".", ".."):
			continue
		if name.endswith("/"):
			kind, name = "d", name[:-1]
		elif name.endswith("@"):
			kind, name = "l", name[:-1]
		elif name.endswith("*"):
			kind, name = "f", name[:-1]
		else:
			kind = "f"
		if name:
			entries.append((name, kind))
	return entries


def stat_path(path: str) -> tuple[bool, int] | None:
	"""活动路由下 stat ``path`` → ``(是否普通文件, 字节数)``。

	不可观测（路由失败 / 超时 / 非文件系统错误）→ ``None``。
	路径确实不存在 → ``(False, 0)``（这是**可观测**的事实，与"看不到"不同）。
	"""

	if not path:
		return None
	cid = active_container()
	if not cid:
		try:
			target = Path(os.path.expanduser(path))
			if not target.exists():
				return (False, 0)
			if not target.is_file():
				return (False, 0)
			return (True, int(target.stat().st_size))
		except OSError:
			return None

	quoted = _sh_quote(path)
	cmd = (
		f"if [ -e {quoted} ]; then "
		f"if [ -f {quoted} ]; then echo F $(stat -c %s {quoted} 2>/dev/null || echo 0); "
		f"else echo D; fi; else echo M; fi"
	)
	probed = _probe(cid, cmd)
	if probed is None:
		return None
	code, text = probed
	if code != 0:
		return None
	head = (text.strip().splitlines() or [""])[0].strip()
	if head == "M":
		return (False, 0)
	if head.startswith("F"):
		parts = head.split()
		size = 0
		if len(parts) > 1:
			try:
				size = max(0, int(parts[1]))
			except ValueError:
				size = 0
		return (True, size)
	if head == "D":
		return (False, 0)
	return None


def read_text(path: str, *, limit: int = 4096) -> str | None:
	"""活动路由下读一段文本（供完成门控的证据执行器用）。不可观测 → None。"""

	if not path:
		return None
	limit = max(1, int(limit))
	cid = active_container()
	if not cid:
		try:
			with open(os.path.expanduser(path), "r", encoding="utf-8", errors="replace") as handle:
				return handle.read(limit)
		except OSError:
			return None

	probed = _probe(cid, f"head -c {limit} -- {_sh_quote(path)} 2>/dev/null")
	if probed is None or probed[0] != 0:
		return None
	return probed[1]


def model_workspace(cwd: str) -> tuple[str | None, list[tuple[str, str]] | None]:
	"""模型首轮的工作面：``(显示用 cwd, 顶层条目)``。

	宿主路由 → ``(abspath(cwd), 宿主清单)``；
	容器路由 → ``(容器内 pwd, 该目录清单)``——模型的动作落在容器里，这才是它的工作面。
	任一分量不可观测 → 该分量为 ``None``；两者皆 None 时调用方应放弃注入。
	"""

	cid = active_container()
	if not cid:
		root = os.path.abspath(cwd) if cwd else ""
		return (root or None, list_dir(root) if root else None)

	pwd_probe = _probe(cid, "pwd")
	display: str | None = None
	if pwd_probe is not None and pwd_probe[0] == 0:
		display = (pwd_probe[1].strip().splitlines() or [""])[0].strip() or None
	entries = list_dir(display) if display else None
	return (display, entries)
