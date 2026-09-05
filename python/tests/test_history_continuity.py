"""#2 / #6：客户端 hydrate + ModelConfig 重建后保留历史。"""

from __future__ import annotations

from msgtypes.message import Message, user_message
from server.app import ChatMessage, _split_prior_and_user
from server.session_pool import ModelConfig, SessionPool


def _cfg(model: str = "m1") -> ModelConfig:
	return ModelConfig(
		provider="deepseek",
		api_key="k",
		base_url="https://example.com/v1",
		model=model,
	)


def test_split_prior_excludes_trailing_user():
	msgs = [
		ChatMessage(role="user", content="u1"),
		ChatMessage(role="assistant", content="a1"),
		ChatMessage(role="user", content="u2"),
	]
	prior, user, last_user_id = _split_prior_and_user(msgs)
	assert user == "u2"
	assert last_user_id is None
	assert len(prior) == 2
	assert prior[0].role == "user" and prior[0].content == "u1"
	assert prior[1].role == "assistant" and prior[1].content == "a1"


def test_split_prior_preserves_client_message_ids():
	msgs = [
		ChatMessage(role="user", content="u1", id="fe-u1"),
		ChatMessage(role="assistant", content="a1", id="fe-a1"),
		ChatMessage(role="user", content="u2", id="fe-u2"),
	]
	prior, user, last_user_id = _split_prior_and_user(msgs)
	assert user == "u2"
	assert last_user_id == "fe-u2"
	assert prior[0].id == "fe-u1"
	assert prior[1].id == "fe-a1"


def test_cold_start_seeds_from_client_prior():
	pool = SessionPool(cwd=".", busy_stale_sec=600)
	prior = [user_message("hello"), Message(role="assistant", content="hi")]
	eng = pool.get_or_create("s1", _cfg(), initial_messages=prior)
	assert len(eng.mutable_messages) == 2
	# 已种子化 — 后续客户端 prior 不得 wipe 实时历史。
	eng2 = pool.get_or_create(
		"s1",
		_cfg(),
		initial_messages=[user_message("only")],
	)
	assert eng2 is eng
	assert len(eng2.mutable_messages) == 2


def test_empty_engine_hydrates_from_client():
	pool = SessionPool(cwd=".", busy_stale_sec=600)
	eng = pool.get_or_create("s1", _cfg())
	assert eng.is_empty()
	prior = [user_message("hello"), Message(role="assistant", content="hi")]
	eng2 = pool.get_or_create("s1", _cfg(), initial_messages=prior)
	assert eng2 is eng
	assert len(eng2.mutable_messages) == 2


def test_model_change_preserves_messages():
	pool = SessionPool(cwd=".", busy_stale_sec=600)
	prior = [user_message("hello"), Message(role="assistant", content="hi")]
	eng1 = pool.get_or_create("s1", _cfg("m1"), initial_messages=prior)
	eng2 = pool.get_or_create("s1", _cfg("m2"))
	assert eng2 is not eng1
	msgs = eng2.mutable_messages
	assert len(msgs) == 2
	assert msgs[0].content == "hello"
	assert msgs[1].content == "hi"


def test_set_cwd_does_not_evict_engines(tmp_path):
	pool = SessionPool(cwd=str(tmp_path), busy_stale_sec=600)
	prior = [user_message("hello"), Message(role="assistant", content="hi")]
	eng1 = pool.get_or_create("s1", _cfg(), initial_messages=prior)
	other = tmp_path / "other"
	other.mkdir()
	pool.set_cwd(str(other))
	eng2 = pool.get_or_create("s1", _cfg())
	assert eng2 is eng1
	assert len(eng2.mutable_messages) == 2
