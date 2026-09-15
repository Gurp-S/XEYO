"""Coord 开关配置：读 ``coord.backend``，默认 ``memory``（零行为变化）。

权威面 = 本模块实现（`python/coord/`）。设计来源为
``_design_drafts/distributed-agents-plan.md`` §3 阶段 0，但该稿早于实现、可能漂移，
**以本模块与 `coord/__init__.py` 的实际行为为准**：
- ``memory``（默认）= 现状，进程内 dict，零持久化；
- ``file`` = presence/任务/租约/ask 队列持久化到 ``<ws>/.xeyo/coord/``，跨进程可见。

读取姿势参照 ``extension/config.py``：home 级 ``~/.xeyo/settings.json`` 与
工作区级 ``<ws>/.xeyo/settings.json`` 两层，workspace 更具体者优先；
坏 JSON / 非法值一律回退 ``memory``（方向安全：最坏情况=回到现状，绝不静默升级）。
coord 只读该键，不写 settings.json。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

_log = logging.getLogger("xeyo.coord.config")

BACKEND_MEMORY = "memory"
BACKEND_FILE = "file"
_VALID_BACKENDS = (BACKEND_MEMORY, BACKEND_FILE)

_DEFAULT = {"coord": {"backend": BACKEND_MEMORY}}


def home_settings_path() -> Path:
    home = os.environ.get("XEYO_HOME", "").strip()
    base = Path(home) if home else Path.home()
    return base / ".xeyo" / "settings.json"


def workspace_settings_path(cwd: str | None) -> Path | None:
    if not cwd or not str(cwd).strip():
        return None
    return Path(str(cwd)).expanduser().resolve() / ".xeyo" / "settings.json"


def _read_backend(path: Path) -> str | None:
    """读单处 settings.json 的 coord.backend；坏文件返回 None（该处回退空）。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _log.debug("coord config read failed at %s: %s", path, exc)
        return None
    if not isinstance(raw, dict):
        return None
    coord = raw.get("coord")
    if not isinstance(coord, dict):
        return None
    backend = coord.get("backend")
    if isinstance(backend, str) and backend.strip().lower() in _VALID_BACKENDS:
        return backend.strip().lower()
    return None


def coord_backend(cwd: str | None = None) -> str:
    """返回生效后端：workspace 覆盖 home；任何失败回退 memory。"""
    backend = _read_backend(home_settings_path())
    ws_path = workspace_settings_path(cwd)
    if ws_path is not None:
        ws_backend = _read_backend(ws_path)
        if ws_backend is not None:
            backend = ws_backend
    if backend not in _VALID_BACKENDS:
        return _DEFAULT["coord"]["backend"]
    return str(backend)


def _read_workers(path: Path) -> bool | None:
    """读单处 settings.json 的 coord.workers；坏文件/缺失返回 None（该处不表态）。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _log.debug("coord workers config read failed at %s: %s", path, exc)
        return None
    if not isinstance(raw, dict):
        return None
    coord = raw.get("coord")
    if not isinstance(coord, dict):
        return None
    val = coord.get("workers")
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        low = val.strip().lower()
        if low in ("true", "1", "on"):
            return True
        if low in ("false", "0", "off"):
            return False
    return None


def coord_workers_enabled(cwd: str | None = None) -> bool:
    """worker 接线开关（**默认开**，2026-09-10 阶段 4 准入转正）：
    workspace 覆盖 home；显式 ``false``（或 ``"false"/"0"/"off"``）关闭。

    唯一消费方 = ``xeyo coord run``（显式 CLI 入口）；引擎主链路不读此键，
    GUI/server 行为与本键无关。缺省/坏配置 → 开（默认即准入态）。"""
    enabled = _read_workers(home_settings_path())
    ws_path = workspace_settings_path(cwd)
    if ws_path is not None:
        ws = _read_workers(ws_path)
        if ws is not None:
            enabled = ws
    return True if enabled is None else bool(enabled)


__all__ = [
    "BACKEND_FILE",
    "BACKEND_MEMORY",
    "coord_backend",
    "coord_workers_enabled",
    "home_settings_path",
    "workspace_settings_path",
]
