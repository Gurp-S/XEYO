"""G51+G52: workspace/media/usage/audit/memory 路由挂 loopback 门禁;workspace_fs 直写有只读开关+审计。"""

from __future__ import annotations

import pytest

from server.local_gate import require_loopback


class _FakeClient:
	def __init__(self, host: str):
		self.host = host


class _FakeRequest:
	def __init__(self, host: str):
		self.client = _FakeClient(host)


def test_require_loopback_rejects_lan(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.delenv("XEYO_ALLOW_REMOTE_CONTROL", raising=False)
	with pytest.raises(Exception) as ei:
		require_loopback(_FakeRequest("192.168.1.50"))
	assert getattr(ei.value, "status_code", 0) in (403, None) or "localhost-only" in str(ei.value)


def test_require_loopback_allows_local(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.delenv("XEYO_ALLOW_REMOTE_CONTROL", raising=False)
	require_loopback(_FakeRequest("127.0.0.1"))  # 不抛即通过
	require_loopback(_FakeRequest("testclient"))
	require_loopback(_FakeRequest("localhost"))


def test_workspace_fs_readonly_env_blocks_writes(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv("XEYO_WORKSPACE_FS_READONLY", "1")
	from server import workspace_fs as fs

	(tmp_path / "a.txt").write_text("x", encoding="utf-8")
	with pytest.raises(PermissionError):
		fs.write_file(str(tmp_path), "b.txt", "hello")
	with pytest.raises(PermissionError):
		fs.delete_path(str(tmp_path), "a.txt")
	# 读不受影响
	assert fs.read_file(str(tmp_path), "a.txt")["text"] == "x"


def test_workspace_fs_write_allowed_by_default(tmp_path) -> None:
	import os
	import server.workspace_fs as fs

	os.environ.pop("XEYO_WORKSPACE_FS_READONLY", None)
	out = fs.write_file(str(tmp_path), "b.txt", "hello")
	assert out["path"] == "b.txt"
	assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "hello"
