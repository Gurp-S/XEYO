"""重启后从磁盘 JSONL 恢复会话（Task8 PR-A）。"""

from __future__ import annotations

from pathlib import Path

from msgtypes.message import assistant_text_message, user_message
from server.session_pool import ModelConfig, SessionPool
from session.persistence import safe_session_filename, transcript_path
from session.record_transcript import record_transcript_sync


def _cfg() -> ModelConfig:
	return ModelConfig(
		provider="deepseek",
		api_key="k",
		base_url="https://example.com/v1",
		model="m1",
	)


def test_engine_session_id_matches_pool_key(tmp_path: Path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
	eng = pool.get_or_create("ilink:u1", _cfg())
	assert eng.session_id == "ilink:u1"
	assert eng._session.session_id == "ilink:u1"


def test_resume_from_disk_roundtrip(tmp_path: Path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	sid = "ilink:u1@im.wechat"
	m1 = user_message("hello")
	m2 = assistant_text_message("hi there")
	n = record_transcript_sync([m1, m2], session_id=sid)
	assert n == 2
	path = transcript_path(sid)
	assert path.is_file()

	pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
	eng = pool.get_or_create(sid, _cfg())
	msgs = eng.mutable_messages
	assert len(msgs) == 2
	assert msgs[0].role == "user" and msgs[0].content == "hello"
	assert msgs[1].role == "assistant" and msgs[1].content == "hi there"
	assert msgs[0].id == m1.id
	assert eng.session_id == sid


def test_resume_ignores_other_session_file(tmp_path: Path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	record_transcript_sync(
		[user_message("only-b")],
		session_id="ilink:b@im.wechat",
	)
	pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
	eng = pool.get_or_create("ilink:a@im.wechat", _cfg())
	assert eng.is_empty()


def test_resume_disabled_skips_disk(tmp_path: Path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	sid = "ilink:u1"
	record_transcript_sync([user_message("secret")], session_id=sid)
	monkeypatch.setenv("XEYO_NO_SESSION_PERSISTENCE", "1")
	pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
	eng = pool.get_or_create(sid, _cfg())
	assert eng.is_empty()


def test_hydrate_skips_bad_rows() -> None:
	from session.hydrate import messages_from_rows

	rows = [
		{"role": "user", "content": "ok", "id": "1"},
		{"role": "nope", "content": "x"},
		{"not": "a message"},
		{"role": "assistant", "content": ["block"], "id": "2"},
	]
	msgs = messages_from_rows(rows)
	assert len(msgs) == 2
	assert msgs[0].content == "ok"
	assert msgs[1].content == ["block"]


def test_transcript_path_ilink_user() -> None:
	sid = "ilink:x@im.wechat"
	p1 = transcript_path(sid)
	p2 = transcript_path(sid)
	assert p1 == p2
	name = p1.name
	assert ":" not in name
	assert "@" not in name
	assert name.endswith(".jsonl")
	assert safe_session_filename(sid) == "ilink__x_im.wechat"
	assert safe_session_filename("ilink:default") == "ilink__default"
