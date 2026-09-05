"""T30 端口文件真相 + /health 真实引擎状态。

- port 文件 JSON {port, pid, started_at, engine_version}，兼容旧纯数字。
- 僵尸判定：pid 不存在即清理文件；活实例保留。
- /health 带 engine_version / pid / busy_sessions / sessions_loaded。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from server.portfile import (
	cleanup_stale_port_file,
	default_port_file,
	is_pid_alive,
	read_port_file,
	write_port_file,
)


def test_write_and_read_port_file(tmp_path: Path) -> None:
	path = tmp_path / "backend_port"
	assert write_port_file(8123, path) == path
	data = json.loads(path.read_text(encoding="utf-8"))
	assert data["port"] == 8123
	assert data["pid"] == os.getpid()
	assert data["started_at"]
	assert data["engine_version"]
	parsed = read_port_file(path)
	assert parsed is not None
	assert parsed["port"] == 8123
	assert parsed["pid"] == os.getpid()


def test_read_legacy_plain_number_port_file(tmp_path: Path) -> None:
	path = tmp_path / "backend_port"
	path.write_text("8017\n", encoding="utf-8")
	parsed = read_port_file(path)
	assert parsed == {"port": 8017}
	# 旧格式无 pid：僵尸清理无事可做
	assert cleanup_stale_port_file(path) is False
	assert path.exists()


def test_read_garbage_port_file(tmp_path: Path) -> None:
	path = tmp_path / "backend_port"
	path.write_text("{not json", encoding="utf-8")
	assert read_port_file(path) is None


def test_pid_alive_and_zombie_cleanup(tmp_path: Path) -> None:
	assert is_pid_alive(os.getpid())
	assert not is_pid_alive(-1)
	proc = subprocess.Popen(
		[sys.executable, "-c", "import time; time.sleep(60)"],
		stdout=subprocess.DEVNULL,
		stderr=subprocess.DEVNULL,
	)
	try:
		assert is_pid_alive(proc.pid)
		path = tmp_path / "backend_port"
		write_port_file(8000, path)
		path.write_text(
			json.dumps({**json.loads(path.read_text(encoding="utf-8")), "pid": proc.pid}),
			encoding="utf-8",
		)
		# 活实例：保留
		assert cleanup_stale_port_file(path) is False
		assert path.exists()
	finally:
		proc.kill()
		proc.wait(timeout=10)
	# 僵尸（pid 已死）：清理
	deadline = time.monotonic() + 10
	while time.monotonic() < deadline and is_pid_alive(proc.pid):
		time.sleep(0.05)
	assert cleanup_stale_port_file(path) is True
	assert not path.exists()


def test_default_port_file_env_override(monkeypatch) -> None:
	monkeypatch.setenv("XEYO_PORT_FILE", r"D:\tmp\xeyo_test_port")
	assert str(default_port_file()) == r"D:\tmp\xeyo_test_port"
	monkeypatch.delenv("XEYO_PORT_FILE")
	assert default_port_file().name == "backend_port"


def test_health_reports_engine_truth() -> None:
	from server.app import app

	c = TestClient(app)
	r = c.get("/health")
	assert r.status_code == 200
	body = r.json()
	assert body.get("ok") is True
	assert body.get("engine_version")
	assert body.get("pid") == os.getpid()
	assert isinstance(body.get("busy_sessions"), list)
	assert isinstance(body.get("sessions_loaded"), int)
