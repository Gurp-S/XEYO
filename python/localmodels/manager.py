"""本地模型进程管理器：单实例 ``llama-server`` 的起停与切换。

**单实例**是核心约束，不是实现细节：一次只驻留一个模型。理由是显存——
8GB 级显卡装不下两支量化模型的常驻副本（4B Q4 约 2.8GB + 8B-A1B Q4 约 5.2GB
已接近上限，再加 llama.cpp 的 CUDA 上下文/KV 必然溢出）。所以"切换模型"
的实现就是"停旧起新"，本模块不做多实例调度。

三个必须守住的性质：

1. **进程归属确定**。谁起的谁负责杀。运行期把 pid/端口/模型写进
   ``run.json``，这样即使 Python 进程被硬杀（任务管理器 / taskkill），
   XEYO.bat 的兜底清理仍能凭该文件把 llama-server 收掉——"随 XEYO 关闭而关闭"
   不能只依赖正常退出路径。
2. **启动不阻塞请求**。模型加载是十秒级到分钟级。``start()`` 立刻返回
   ``state=starting``，加载与健康探测在后台线程做，前端轮询 ``status()``。
3. **失败留痕**。加载失败时把 llama-server 的最后若干行输出带回给调用方
   （而不是只说"启动失败"），否则用户面对一个空日志无从判断是权重缺失、
   显存不足还是参数错误。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from localmodels import catalog, config

#: 模型加载 + 健康探测的总等待上限（秒）。首次加载 8B 量化权重在机械盘上可能很久。
BOOT_TIMEOUT_S = 300.0
#: 停止时等待进程自行退出的时长；超时改强杀。
STOP_GRACE_S = 8.0
#: 健康探测的请求超时。
HEALTH_TIMEOUT_S = 2.0

_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_PROCESS_GROUP = 0x00000200


def _log(msg: str) -> None:
	import logging

	logging.getLogger(__name__).info("local-models: %s", msg)


class LocalModelManager:
	"""``llama-server`` 单实例生命周期。进程内单例（``default_manager()``）。"""

	def __init__(self) -> None:
		self._lock = threading.RLock()
		self._proc: subprocess.Popen[bytes] | None = None
		self._state = "stopped"
		self._model_id = ""
		self._pid: int | None = None
		self._port = 0
		self._host = ""
		self._started_at = 0.0
		self._error = ""
		self._boot_thread: threading.Thread | None = None

	# ---- 路径 ----

	def _log_path(self) -> Path:
		return config.run_dir() / "llama-server.log"

	def _run_path(self) -> Path:
		return config.run_dir() / "run.json"

	# ---- 运行期文件（跨进程兜底清理的唯一依据）----

	def _write_run_file(self, cfg: dict[str, Any], pid: int) -> None:
		try:
			path = self._run_path()
			path.parent.mkdir(parents=True, exist_ok=True)
			path.write_text(
				json.dumps(
					{
						"pid": pid,
						"model": self._model_id,
						"host": cfg["host"],
						"port": int(cfg["port"]),
						"base_url": config.base_url(cfg),
						"binary": str(config.resolve_binary(cfg) or ""),
						"log": str(self._log_path()),
						"started_at": self._started_at,
						"owner": "xeyo",
					},
					ensure_ascii=False,
					indent=2,
				)
				+ "\n",
				encoding="utf-8",
			)
		except OSError as exc:  # 兜底文件写不了不应阻断启动
			_log(f"cannot write run file: {exc}")

	def _read_run_file(self) -> dict[str, Any]:
		try:
			raw = json.loads(self._run_path().read_text(encoding="utf-8"))
			return raw if isinstance(raw, dict) else {}
		except Exception:  # noqa: BLE001 — 缺失/坏文件 = 无记录
			return {}

	def _clear_run_file(self) -> None:
		try:
			self._run_path().unlink(missing_ok=True)
		except OSError:
			pass

	# ---- 健康探测 ----

	@staticmethod
	def healthy(host: str, port: int) -> bool:
		"""llama.cpp ``/health``：加载完成返回 200，加载中返回 503。"""
		try:
			with urllib.request.urlopen(  # noqa: S310 — 地址来自本机配置
				f"http://{host}:{int(port)}/health", timeout=HEALTH_TIMEOUT_S
			) as resp:
				return int(getattr(resp, "status", 0) or 0) == 200
		except urllib.error.HTTPError as exc:
			return int(exc.code) == 200
		except Exception:  # noqa: BLE001 — 未监听/未就绪一律视为不健康
			return False

	@staticmethod
	def _image_name(pid: int) -> str | None:
		"""该 pid 的镜像名（小写）。``None`` = 查询失败（不确定）；``""`` = 确认不存在。

		两个坑都在这几行里：
		- ``tasklist`` 的输出是**本地化 OEM 编码**（中文系统上是 GBK），不能按
		  UTF-8 硬解；解崩会把"进程已退出"误判成"查不动"，进而漏收进程。
		  镜像名本身是纯 ASCII，所以宽松解码足够，真伪判据放在 CSV 结构上。
		- 不能用 ``str(pid) in out`` 判存活：pid=123 而输出含 ``1234`` 时会误判。
		"""
		if pid <= 0:
			return ""
		if sys.platform == "win32":
			try:
				proc = subprocess.run(  # noqa: S603,S607 — 系统自带 tasklist
					["tasklist", "/FI", f"PID eq {int(pid)}", "/NH", "/FO", "CSV"],
					capture_output=True,
					timeout=10,
					creationflags=_CREATE_NO_WINDOW,
				)
			except Exception:  # noqa: BLE001 — 查询失败 ≠ 进程不存在
				return None
			raw = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
			if not raw:
				return ""
			first = raw.splitlines()[0]
			if not first.startswith('"'):
				# 没有匹配项时 tasklist 打的是**本地化信息行**，不是 CSV。
				return ""
			return first.split(",")[0].strip().strip('"').lower()
		try:
			os.kill(int(pid), 0)
		except OSError:
			return ""
		return "unknown"

	@staticmethod
	def _pid_alive(pid: int) -> bool:
		return bool(LocalModelManager._image_name(int(pid)))

	@staticmethod
	def pid_ownership(pid: int | None) -> str:
		"""这个 pid 是不是我们的 llama-server：``ours`` / ``foreign`` / ``gone`` / ``unknown``。

		为什么要四态而不是布尔：``run.json`` 里的 pid 来自**上一次会话**，而
		Windows 会复用 pid。只看"存活"就杀会误杀无关进程（``foreign``）；
		而 ``tasklist`` 偶发失败时又不能断言"不是我们的"（``unknown``，
		此时宁可不动手、也不清记录，留给下一次重试）。
		"""
		if not isinstance(pid, int) or pid <= 0:
			return "gone"
		name = LocalModelManager._image_name(pid)
		if name is None:
			return "unknown"
		if not name:
			return "gone"
		if name == "unknown":  # 非 Windows：拿不到镜像名，按"存活即我们"处理
			return "ours"
		return "ours" if name.startswith("llama-server") else "foreign"

	@staticmethod
	def is_llama_server_pid(pid: int | None) -> bool:
		"""收停前的归属门：只有 ``ours`` 才允许动手。"""
		return LocalModelManager.pid_ownership(pid) == "ours"

	# ---- 状态 ----

	def status(self) -> dict[str, Any]:
		"""当前运行态快照（供设置面板轮询）。"""
		with self._lock:
			self._refresh_state_locked()
			cfg = config.store()
			info: dict[str, Any] = {
				"state": self._state,
				"model": self._model_id or str(cfg["active_model"]),
				"pid": self._pid,
				"host": self._host or str(cfg["host"]),
				"port": int(self._port or cfg["port"]),
				"base_url": config.base_url(cfg),
				"started_at": self._started_at,
				"uptime_s": (time.time() - self._started_at) if self._started_at else 0.0,
				"error": self._error,
				"log_path": str(self._log_path()),
			}
		info["healthy"] = (
			info["state"] == "running"
			and self.healthy(str(info["host"]), int(info["port"]))
		)
		return info

	def _refresh_state_locked(self) -> None:
		"""把"我们的 Popen 已退出"反映到状态上（没人调 stop 的崩溃路径）。"""
		if self._state not in ("starting", "running"):
			return
		if self._proc is not None and self._proc.poll() is not None:
			rc = self._proc.returncode
			self._state = "error"
			self._error = self._error or f"llama-server 退出，返回码 {rc}"
			self._pid = None
			self._clear_run_file()

	def tail_log(self, lines: int = 40) -> str:
		"""llama-server 日志末若干行（失败诊断用；读不到返回空串）。"""
		try:
			text = self._log_path().read_text(encoding="utf-8", errors="replace")
		except OSError:
			return ""
		return "\n".join(text.splitlines()[-max(1, int(lines)) :])

	# ---- 命令行 ----

	def _build_cmd(self, cfg: dict[str, Any], model_id: str) -> list[str]:
		binary = config.resolve_binary(cfg)
		if binary is None:
			raise FileNotFoundError(
				"未找到 llama-server.exe；请把 llama.cpp Windows 包解压到 "
				f"{config.models_dir() / 'bin'}，或在设置里指定可执行文件路径"
			)
		gguf = config.model_path(model_id, cfg)
		if not gguf.is_file():
			m = catalog.get(model_id)
			src = f"（权重来源 {m.repo}）" if m else ""
			raise FileNotFoundError(
				f"权重文件缺失：{gguf}{src}；"
				"可用 py -3.11 scripts/fetch-local-models.py 下载"
			)
		cmd = [
			str(binary),
			"-m",
			str(gguf),
			"--host",
			str(cfg["host"]),
			"--port",
			str(int(cfg["port"])),
			"-c",
			str(int(cfg["ctx"])),
			"-ngl",
			str(int(cfg["gpu_layers"])),
			# alias = 模型 id，使 /v1/models 报出前端账号里登记的那个名字。
			"--alias",
			model_id,
		]
		extra = str(cfg.get("extra_args") or "").strip()
		if extra:
			cmd.extend(extra.split())
		if model_id:
			m = catalog.get(model_id)
			if m is not None:
				cmd.extend(m.extra_args)
		return cmd

	# ---- 起停 ----

	def start(self, model_id: str | None = None) -> dict[str, Any]:
		"""启动（或确认已在运行）；**不等待加载完成**，立即返回。"""
		with self._lock:
			self._refresh_state_locked()
			cfg = config.store()
			target = catalog.resolve_model_id(model_id or str(cfg["active_model"]))
			if self._state in ("starting", "running"):
				if self._model_id == target and self._state == "running":
					return {"ok": True, "already": True, **self._snapshot_locked(cfg)}
				# 单实例：目标不同 → 先停再起。
				self._stop_locked()

			try:
				cmd = self._build_cmd(cfg, target)
			except FileNotFoundError as exc:
				self._state, self._error = "error", str(exc)
				return {"ok": False, "error": str(exc)}

			self._log_path().parent.mkdir(parents=True, exist_ok=True)
			log_fh = open(self._log_path(), "ab", buffering=0)  # noqa: SIM115 — 交给子进程持有
			flags = 0
			if sys.platform == "win32":
				flags = _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP
			try:
				proc = subprocess.Popen(  # noqa: S603 — 参数数组，不经 shell
					cmd,
					stdout=log_fh,
					stderr=subprocess.STDOUT,
					stdin=subprocess.DEVNULL,
					cwd=str(config.models_dir()),
					creationflags=flags,
				)
			except OSError as exc:
				log_fh.close()
				self._state, self._error = "error", f"无法启动 llama-server: {exc}"
				return {"ok": False, "error": self._error}
			finally:
				try:
					log_fh.close()
				except Exception:  # noqa: BLE001
					pass

			self._proc = proc
			self._pid = proc.pid
			self._model_id = target
			self._host = str(cfg["host"])
			self._port = int(cfg["port"])
			self._started_at = time.time()
			self._state = "starting"
			self._error = ""
			self._write_run_file(cfg, proc.pid)
			_log(f"started pid={proc.pid} model={target} port={self._port}")

			thread = threading.Thread(
				target=self._await_ready,
				args=(proc, target),
				name="xeyo-local-model-boot",
				daemon=True,
			)
			self._boot_thread = thread
			thread.start()
			return {"ok": True, **self._snapshot_locked(cfg)}

	def _snapshot_locked(self, cfg: dict[str, Any]) -> dict[str, Any]:
		return {
			"state": self._state,
			"model": self._model_id,
			"pid": self._pid,
			"host": self._host or str(cfg["host"]),
			"port": int(self._port or cfg["port"]),
			"base_url": config.base_url(cfg),
			"error": self._error,
		}

	def _await_ready(self, proc: subprocess.Popen[bytes], model_id: str) -> None:
		"""后台线程：等 ``/health`` 通；进程先退则把日志尾部当错误带回。"""
		deadline = time.monotonic() + BOOT_TIMEOUT_S
		host, port = self._host, self._port
		while time.monotonic() < deadline:
			if proc.poll() is not None:
				with self._lock:
					if self._proc is proc:
						self._state = "error"
						self._error = (
							f"llama-server 启动即退出（返回码 {proc.returncode}）"
						)
						self._pid = None
						self._clear_run_file()
				_log(f"boot failed model={model_id} rc={proc.returncode}")
				return
			if self.healthy(host, port):
				with self._lock:
					if self._proc is proc:
						self._state = "running"
						self._error = ""
				_log(f"ready model={model_id} port={port}")
				return
			time.sleep(1.0)
		with self._lock:
			if self._proc is proc:
				self._state = "error"
				self._error = f"等待 llama-server 就绪超时（{int(BOOT_TIMEOUT_S)}s）"

	def stop(self) -> dict[str, Any]:
		"""停止本地模型服务（连带收掉 pid 树，防残留占显存）。"""
		with self._lock:
			return self._stop_locked()

	def _stop_locked(self) -> dict[str, Any]:
		proc, pid = self._proc, self._pid
		run = self._read_run_file()
		if pid is None and isinstance(run.get("pid"), int):
			pid = int(run["pid"])
		stopped = False
		if proc is not None and proc.poll() is None:
			try:
				proc.terminate()
				proc.wait(timeout=STOP_GRACE_S)
			except Exception:  # noqa: BLE001 — 超时/已退出都走强杀
				pass
			stopped = True
		if pid and self.is_llama_server_pid(int(pid)):
			self._kill_tree(int(pid))
			stopped = True
		self._proc = None
		self._pid = None
		self._host = ""
		self._port = 0
		self._started_at = 0.0
		self._model_id = ""
		self._state = "stopped"
		self._error = ""
		self._clear_run_file()
		return {"ok": True, "stopped": stopped, "state": "stopped"}

	@staticmethod
	def _kill_tree(pid: int) -> None:
		if sys.platform == "win32":
			try:
				subprocess.run(  # noqa: S603,S607
					["taskkill", "/PID", str(pid), "/T", "/F"],
					capture_output=True,
					timeout=15,
					creationflags=_CREATE_NO_WINDOW,
				)
				return
			except Exception:  # noqa: BLE001 — 回落 os.kill
				pass
		try:
			os.kill(pid, 9)
		except OSError:
			pass

	def switch_to(self, model_id: str) -> dict[str, Any]:
		"""切换模型：写配置的 active_model；若正在运行则"停旧起新"。"""
		target = catalog.resolve_model_id(model_id)
		config.save({"active_model": target})
		with self._lock:
			self._refresh_state_locked()
			running = self._state in ("starting", "running")
			was = self._model_id
		if running and was != target:
			self.stop()
			return {"ok": True, "switched": True, "model": target, **self.start(target)}
		return {"ok": True, "switched": False, "model": target, "state": self._state}

	def autostart(self) -> dict[str, Any]:
		"""XEYO 启动钩子：仅当设置里启用且未在跑时拉起。

		已在跑（上一次会话遗留且仍健康）则**收养**而不是重复拉起——单实例约束下
		重复拉起会把显存撞爆。收养的条件是"配置端口上 /health 通 **且** 记录的
		pid 不是别人家的"：只看 pid 会在 tasklist 偶发失败时误判，只看 health
		又会漏掉不用 pid 也能认出的情况。
		"""
		cfg = config.store()
		if not cfg.get("enabled"):
			return {"ok": True, "skipped": "disabled"}
		with self._lock:
			self._refresh_state_locked()
			if self._state in ("starting", "running"):
				return {"ok": True, "skipped": "already-running"}
			run = self._read_run_file()
			pid = run.get("pid")
			host = str(run.get("host") or cfg["host"])
			port = int(run.get("port") or cfg["port"])
		verdict = LocalModelManager.pid_ownership(pid)
		if verdict != "foreign" and self.healthy(host, port):
			adopted = int(pid) if verdict == "ours" else None
			with self._lock:
				self._state = "running"
				self._pid = adopted
				self._host = host
				self._port = port
				self._model_id = str(run.get("model") or cfg["active_model"])
				self._started_at = float(run.get("started_at") or time.time())
			_log(f"adopted existing pid={adopted} port={port} (ownership={verdict})")
			return {"ok": True, "adopted": True, "pid": adopted}
		return self.start()


_MANAGER: LocalModelManager | None = None
_MANAGER_LOCK = threading.Lock()


def default_manager() -> LocalModelManager:
	"""进程内单例。"""
	global _MANAGER
	with _MANAGER_LOCK:
		if _MANAGER is None:
			_MANAGER = LocalModelManager()
		return _MANAGER


def shutdown() -> None:
	"""进程退出钩子：收掉子进程（idempotent）。"""
	if _MANAGER is not None:
		_MANAGER.stop()


def _cleanup_from_run_file() -> None:
	"""无管理器状态时的兜底清理：凭 ``run.json`` 收掉遗留 llama-server。

	给"Python 进程被硬杀、atexit 没跑到"的路径用；XEYO.bat 也走同一份文件。

	只杀 ``pid_ownership == "ours"`` 的进程。其余三种归属分别处理：
	``gone``/``foreign`` → 记录已失效，清掉；``unknown``（tasklist 查不动）
	→ 保留记录，留给下一次重试，绝不猜着杀。
	"""
	path = config.run_dir() / "run.json"
	try:
		run = json.loads(path.read_text(encoding="utf-8"))
	except Exception:  # noqa: BLE001
		return
	pid = run.get("pid") if isinstance(run, dict) else None
	verdict = LocalModelManager.pid_ownership(pid)
	if verdict == "ours":
		LocalModelManager._kill_tree(int(pid))
	if verdict != "unknown":
		try:
			path.unlink(missing_ok=True)
		except OSError:
			pass
