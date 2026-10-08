"""CLI settings and retry remain attached to the intended session."""
from __future__ import annotations


import pytest

from cli import chat_cmd
from permissions.policy import permission_mode


async def replay(monkeypatch, lines):
	builds, turns = [], []

	def build(**kwargs):
		builds.append((kwargs["session_id"], kwargs["model"]))

		class Engine:
			session_id = kwargs["session_id"]

			async def submit(self, text, options):
				turns.append((self.session_id, text, permission_mode()))
				if False:
					yield None

		return Engine(), 0

	inputs = iter(lines)

	def read(mode):
		try:
			return next(inputs)
		except StopIteration:
			raise EOFError

	monkeypatch.setattr(chat_cmd, "ensure_utf8_stdio", lambda: None)
	monkeypatch.setattr(chat_cmd, "resolve_cwd", lambda cwd, persist: cwd)
	monkeypatch.setattr(chat_cmd, "build_chat_engine", build)
	monkeypatch.setattr(chat_cmd, "_read_repl_line", read)
	assert await chat_cmd.chat_async(
		prompt=None, cwd=".", session_id="original", provider="fake", model="model-A",
		api_key="", base_url="", permission_mode="risk", agent_mode="agent",
		print_mode=False, json_mode=True,
	) == 0
	return builds, turns


@pytest.mark.asyncio
async def test_approval_mode_applies_to_following_turns(monkeypatch):
	_, turns = await replay(monkeypatch, ["/approval always", "first", "second", "/approval never", "third"])
	assert [turn[2] for turn in turns] == ["always", "always", "never"]


@pytest.mark.asyncio
async def test_model_switch_preserves_session_and_retry(monkeypatch):
	builds, turns = await replay(monkeypatch, ["old task", "/model model-B", "/retry"])
	assert builds == [("original", "model-A"), ("original", "model-B")]
	assert [turn[:2] for turn in turns] == [("original", "old task"), ("original", "old task")]


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/clear", "/load another"])
async def test_session_switch_does_not_retry_old_task(monkeypatch, command):
	_, turns = await replay(monkeypatch, ["old task", command, "/retry", "new task"])
	assert [turn[1] for turn in turns] == ["old task", "new task"]
	assert turns[0][0] != turns[1][0]
