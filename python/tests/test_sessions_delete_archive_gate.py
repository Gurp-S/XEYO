"""会话删除归档门槛（2026-09-05）。

规则：常态会话一律不允许删除（409 archived_required）——必须先归档，
从已归档态才能删除。删除是不可逆破坏性操作，归档作为缓冲层。

覆盖：
① 未归档 DELETE /v1/sessions/{sid} → 409 archived_required，transcript 不动。
② 归档后删除 → 200，transcript + archive sidecar 清干净。
③ restore（清 sidecar）后再次删除 → 重新被 409 拦下（恢复即回到常态保护）。

直接调路由函数（与 test_cross_entry_ssot_t31.py 同形态），不起真实 engine。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from session.persistence import transcript_path


def _seed_transcript(sessions_dir: Path, sid: str) -> Path:
	tp = transcript_path(sid, sessions_dir=sessions_dir)
	tp.parent.mkdir(parents=True, exist_ok=True)
	tp.write_text(
		'{"role":"user","content":"hello","ts":1757000000.0}\n',
		encoding="utf-8",
	)
	return tp


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch) -> Path:
	"""隔离会话目录，避免测试触碰真实 ~/.xeyo/sessions。"""
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
	return tmp_path / "sessions"


def _delete(sid: str) -> dict:
	from server.routers import sessions as sessions_module

	return sessions_module.delete_session(sid)


def test_delete_blocked_when_not_archived(isolated_env: Path) -> None:
	"""常态会话删除必须 409 archived_required；transcript 原样保留。"""
	from server.routers import sessions as sessions_module
	from server.session_pool import SessionPool

	sessions_module._pool = SessionPool(cwd=str(isolated_env), busy_stale_sec=600)
	sid = "sess_not_archived"
	tp = _seed_transcript(isolated_env, sid)

	with pytest.raises(HTTPException) as ei:
		_delete(sid)
	assert ei.value.status_code == 409
	assert ei.value.detail["type"] == "archived_required"
	assert tp.is_file(), "未归档删除被拒后 transcript 必须原样保留"


def test_delete_allowed_after_archive(isolated_env: Path) -> None:
	"""归档 → 删除 → 200，transcript 与 archive sidecar 一并清理。"""
	from server.routers import sessions as sessions_module
	from server.session_pool import SessionPool
	from engine.title import archive_sidecar_path, read_archive

	sessions_module._pool = SessionPool(cwd=str(isolated_env), busy_stale_sec=600)
	sid = "sess_archived_then_deleted"
	tp = _seed_transcript(isolated_env, sid)

	# 归档（写 sidecar，不动 transcript）
	res = sessions_module.archive_session(sid)
	assert res["ok"] is True
	assert tp.is_file(), "归档本身不得删除 transcript"
	assert read_archive(sid, sessions_dir=isolated_env) is not None

	# 已归档：删除放行
	out = _delete(sid)
	assert out["ok"] is True
	assert not tp.exists(), "删除后 transcript 必须清理（否则重启会重新导入）"
	assert not archive_sidecar_path(sid, sessions_dir=isolated_env).exists()


def test_restore_rearms_delete_gate(isolated_env: Path) -> None:
	"""归档→恢复→删除：回到常态保护（409）。"""
	from server.routers import sessions as sessions_module
	from server.session_pool import SessionPool

	sessions_module._pool = SessionPool(cwd=str(isolated_env), busy_stale_sec=600)
	sid = "sess_restore_then_delete"
	tp = _seed_transcript(isolated_env, sid)

	sessions_module.archive_session(sid)
	assert sessions_module.restore_session(sid)["ok"] is True

	with pytest.raises(HTTPException) as ei:
		_delete(sid)
	assert ei.value.status_code == 409
	assert ei.value.detail["type"] == "archived_required"
	assert tp.is_file()


def test_delete_unknown_session_still_gated(isolated_env: Path) -> None:
	"""不存在的会话同样吃归档门槛（不泄露存在性、不绕道）。"""
	from server.routers import sessions as sessions_module
	from server.session_pool import SessionPool

	sessions_module._pool = SessionPool(cwd=str(isolated_env), busy_stale_sec=600)
	with pytest.raises(HTTPException) as ei:
		_delete("sess_never_existed")
	assert ei.value.status_code == 409
	assert ei.value.detail["type"] == "archived_required"
