"""本地模型进程的兜底控制：按 run.json 收掉遗留的 llama-server。

为什么需要它（而不是让后端自己收）：后端只在**正常退出**路径上跑 shutdown 钩子。
Python 被硬杀（任务管理器 / ``taskkill /F`` / 崩溃）时钩子不会执行，llama-server
会继续占着显存与端口跑下去——正是"防止日常消耗"要挡的那种情况。

本脚本是**跨进程的唯一兜底入口**：XEYO.bat 在启动前与退出后各调一次，
用户也可以手动跑一次把显存要回来。

只读 ``run.json``、只认镜像名守卫，不 import 服务器依赖；解释器用仓内 venv
或系统 ``py -3.11`` 均可（XEYO.bat 用后者，因为它要能在后端起来之前先跑）。

用法::

    py -3.11 python/scripts/local_model_ctl.py --stop     # 收掉遗留进程并清 run.json
    py -3.11 python/scripts/local_model_ctl.py --status   # 打印 {pid, model, port, alive}
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from localmodels import config  # noqa: E402
from localmodels.manager import LocalModelManager  # noqa: E402


def _run_path() -> Path:
	return config.run_dir() / "run.json"


def _read_run() -> dict:
	try:
		raw = json.loads(_run_path().read_text(encoding="utf-8"))
	except Exception:  # noqa: BLE001 — 缺失/坏文件 = 无遗留
		return {}
	return raw if isinstance(raw, dict) else {}


def _clear_run() -> None:
	try:
		_run_path().unlink(missing_ok=True)
	except OSError:
		pass


def _emit(payload: dict) -> None:
	print(json.dumps(payload, ensure_ascii=False))


def main() -> int:
	argv = sys.argv[1:]
	stop = "--stop" in argv or "--status" not in argv  # 默认动作 = 收掉

	run = _read_run()
	pid = run.get("pid")
	# 归属四态：pid 可能被系统复用给无关进程（foreign），也可能因为 tasklist
	# 查不动而无法判断（unknown）。只有 ours 才动手；unknown 保留记录下次再试。
	verdict = LocalModelManager.pid_ownership(pid)

	if not stop:
		_emit(
			{
				"pid": pid if verdict == "ours" else None,
				"model": run.get("model"),
				"port": run.get("port"),
				"alive": verdict == "ours",
				"recorded_pid": pid,
				"ownership": verdict,
			}
		)
		return 0

	if verdict == "ours":
		# 收掉整棵 pid 树：llama-server 在 Windows 上可能派生子进程（如 CUDA 相关
		# helper），只杀父进程会留下仍持有显存的孤儿。
		_emit({"stopped": True, "pid": pid, "model": run.get("model")})
		LocalModelManager._kill_tree(int(pid))
		deadline = time.time() + 8.0
		while time.time() < deadline and LocalModelManager.pid_ownership(pid) == "ours":
			time.sleep(0.3)
		_clear_run()
		return 0

	if verdict == "unknown":
		# 判断不了就不猜：留着 run.json，下一次（或后端起来后）再收。
		_emit({"stopped": False, "reason": "ownership-unknown", "pid": pid})
		return 0

	if run:
		_emit({"stopped": False, "reason": f"stale-record({verdict})", "pid": pid})
		_clear_run()
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
