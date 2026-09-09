"""coord 接入门控回归：锁死主链路边界与惰性导入。

准入转正(2026-09-10)后的冻结口径：
1. coord_backend 默认 memory（presence file 后端不进 GUI server event loop）；
2. coord_workers_enabled 默认 **True**（唯一消费方 = `xeyo coord run` 显式 CLI
   入口；引擎主链路不读此键）——显式 false 仍可关；
3. import cli.coord_cmd / coord.config 不拉起 engine.query_engine（接线代码惰性）；
4. 坏配置：backend 回退 memory（保守），workers 缺省落开。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from coord.config import (
    BACKEND_MEMORY,
    coord_backend,
    coord_workers_enabled,
    home_settings_path,
)

PYTHON = sys.executable
ROOT = str(Path(__file__).resolve().parents[2])  # python/


def _write_settings(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")


def test_defaults_are_conservative(tmp_path, monkeypatch):
    """准入转正(2026-09-10)：workers 默认开；backend 保持 memory 保守默认。"""
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))  # 无 settings.json
    ws = tmp_path / "ws"
    ws.mkdir()
    assert coord_backend(str(ws)) == BACKEND_MEMORY
    assert coord_workers_enabled(str(ws)) is True  # 默认开（唯一消费方=coord run 显式入口）


def test_workers_disabled_requires_explicit_false(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    ws = tmp_path / "ws"
    (ws / ".xeyo").mkdir(parents=True)
    assert coord_workers_enabled(str(ws)) is True  # 有目录无配置 = 默认开
    _write_settings(ws / ".xeyo" / "settings.json", {"coord": {"workers": False}})
    assert coord_workers_enabled(str(ws)) is False
    _write_settings(ws / ".xeyo" / "settings.json", {"coord": {"workers": "off"}})
    assert coord_workers_enabled(str(ws)) is False
    _write_settings(ws / ".xeyo" / "settings.json", {"coord": {"workers": True}})
    assert coord_workers_enabled(str(ws)) is True
    # 非法值（默认开档下）→ 不表态，落默认 True
    _write_settings(ws / ".xeyo" / "settings.json", {"coord": {"workers": "maybe"}})
    assert coord_workers_enabled(str(ws)) is True


def test_bad_config_direction_safe(tmp_path, monkeypatch):
    """坏 JSON / 非法值 → 回退最保守档，绝不静默升级。"""
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    ws = tmp_path / "ws"
    (ws / ".xeyo").mkdir(parents=True)
    # 坏 JSON：backend 回退 memory（保守），workers 缺省落开（默认准入态）
    _write_settings(ws / ".xeyo" / "settings.json", "{not json")
    assert coord_backend(str(ws)) == BACKEND_MEMORY
    assert coord_workers_enabled(str(ws)) is True
    _write_settings(ws / ".xeyo" / "settings.json", {"coord": {"backend": "sqlite"}})
    assert coord_backend(str(ws)) == BACKEND_MEMORY


def test_workspace_overrides_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("XEYO_HOME", str(home))
    _write_settings(home_settings_path(), {"coord": {"backend": "file"}})
    # home 开 file，但 workspace 明确 memory → workspace 优先（方向安全）
    ws = tmp_path / "ws"
    (ws / ".xeyo").mkdir(parents=True)
    _write_settings(ws / ".xeyo" / "settings.json", {"coord": {"backend": "memory"}})
    assert coord_backend(str(ws)) == BACKEND_MEMORY
    # 无 workspace 声明时继承 home=file
    ws2 = tmp_path / "ws2"
    ws2.mkdir()
    assert coord_backend(str(ws2)) == "file"


def test_coord_cmd_import_is_lazy():
    """import cli.coord_cmd 不得拉起 engine.query_engine（接线重依赖全在函数内延迟 import）。"""
    code = ("import cli.coord_cmd, sys;"
            "print('ENGINE' if any(k=='engine.query_engine' or k.startswith('engine.query_engine.') "
            "for k in sys.modules) else 'LAZY')")
    r = subprocess.run([PYTHON, "-c", code], capture_output=True, text=True,
                       cwd=ROOT, timeout=60)
    assert "LAZY" in r.stdout, f"query_engine eagerly imported: {r.stdout!r} {r.stderr!r}"


def test_worker_session_not_imported_by_coord_init():
    """import coord（包初始化）不得拉起 worker_session（真会话依赖）。"""
    code = ("import coord, sys;"
            "print('EAGER' if any('worker_session' in k for k in sys.modules) else 'LAZY')")
    r = subprocess.run([PYTHON, "-c", code], capture_output=True, text=True,
                       cwd=ROOT, timeout=60)
    assert "LAZY" in r.stdout, f"worker_session eagerly imported: {r.stdout!r} {r.stderr!r}"
