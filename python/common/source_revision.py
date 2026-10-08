"""本进程加载的源码修订 vs 磁盘现状（**给人看的**陈旧事实）。

动因（agent 自报摩擦，2026-10-08）：提示面 / 工具面改动全在常驻后端进程里，改完看不到
效果——唯一出口是"等重启"。观测面因此被拆成两截：`cli probe`（新进程 = 新代码）负责
"看到效果"，本模块负责"看见进程旧了"。

为什么不进模型注意力：模型对"引擎进程是否陈旧"没有可执行动作，属引擎自陈（铁律 4）。
所以这里只写日志，不产 T_now 块。

为什么不在 import 时就扫描：本模块被 CLI/测试大量间接导入，import 期 rglob 四个目录会
给每个进程加一笔固定开销。只有 :func:`log_loaded`（由服务启动时显式调用）做一次。
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

_log = logging.getLogger("xeyo.revision")

#: 会随"改代码"漂移的目录（提示面 / 工具面 / 引擎 / 记忆面）。
WATCH_DIRS: tuple[str, ...] = ("prompt", "tools", "engine", "memory")

_PY_ROOT = Path(__file__).resolve().parents[1]

#: 启动时那一次快照；只在 :func:`log_loaded` 里填。
_STARTUP: dict[str, float | str] | None = None


def _git_rev(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:  # noqa: BLE001 — 没有 git 也要能报 mtime
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _newest_mtime(root: Path, name: str) -> float:
    base = root / name
    if not base.is_dir():
        return 0.0
    newest = 0.0
    for path in base.rglob("*.py"):
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return newest


def snapshot(root: Path | str | None = None) -> dict[str, float | str]:
    """当前磁盘上的修订事实：git rev + 各目录最新 mtime。"""
    base = Path(root) if root else _PY_ROOT
    out: dict[str, float | str] = {"repo_rev": _git_rev(base.parent.parent), "rev_at": time.time()}
    for name in WATCH_DIRS:
        out[f"{name}_mtime"] = _newest_mtime(base, name)
    return out


def _fmt(ts: float | str) -> str:
    value = float(ts or 0)
    return time.strftime("%H:%M:%S", time.localtime(value)) if value else "-"


def log_loaded(root: Path | str | None = None) -> dict[str, float | str]:
    """服务启动时记一行：这一进程加载的是哪一版（给人看，不进注意力）。

    stdout 与 logger 各写一次：服务以 ``log_level="warning"`` 起 uvicorn 时 INFO 不出，
    而这行事实的价值就是"看得见"。
    """
    global _STARTUP
    _STARTUP = snapshot(root)
    line = "source revision: rev={} {}".format(
        _STARTUP.get("repo_rev") or "-",
        " ".join(f"{name}={_fmt(_STARTUP.get(f'{name}_mtime', 0.0))}" for name in WATCH_DIRS),
    )
    _log.info(line)
    try:
        print(f"[xeyo] {line}", flush=True)
    except Exception:  # noqa: BLE001 — 打不出来也不影响启动
        pass
    return _STARTUP


def stale_dirs(root: Path | str | None = None) -> tuple[str, ...]:
    """相对启动快照，磁盘上已变动的目录（没调用过 :func:`log_loaded` ⇒ 空）。"""
    if _STARTUP is None:
        return ()
    now = snapshot(root)
    return tuple(
        name for name in WATCH_DIRS if float(now.get(f"{name}_mtime", 0.0)) > float(_STARTUP.get(f"{name}_mtime", 0.0))
    )
