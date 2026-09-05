"""session.md 与 WorkingSnapshot 分家（M-L5s）。"""

from __future__ import annotations

from memory.session_md import load, maybe_update, path_for, render
from memory.working import WorkingSnapshot


def _msgs() -> list[dict]:
	return [
		{"role": "user", "content": "Fix the login bug"},
		{"role": "assistant", "content": "I will grep the auth module."},
		{
			"role": "assistant",
			"content": [
				{"type": "tool_use", "id": "c1", "name": "Grep", "input": {}},
			],
		},
		{
			"role": "tool",
			"tool_call_id": "c1",
			"content": [
				{"type": "tool_result", "tool_use_id": "c1", "content": "match"}
			],
		},
	]


def test_render_has_six_sections_no_machine_fields():
	text = render(_msgs() + [{"role": "user", "content": "also cover edge cases"}])
	for heading in (
		"## Goal",
		"## Current state",
		"## Completed",
		"## Important discoveries",
		"## Key facts",
		"## Open questions",
		"## Next action",
	):
		assert heading in text
	assert "compact_cursor" not in text
	assert "prompt_cache" not in text
	assert "- [ ]" not in text
	assert "hit_tokens" not in text


def test_maybe_update_skips_until_tool_threshold(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	working = WorkingSnapshot(session_id="s1")
	maybe_update("s1", _msgs(), min_tool_calls=8, working=working)
	assert load("s1") is None


def test_maybe_update_writes_and_throttles(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	working = WorkingSnapshot(session_id="s1")
	msgs: list[dict] = [{"role": "user", "content": "remember the goal is ship C2"}]
	for i in range(10):
		msgs.append(
			{
				"role": "tool",
				"tool_call_id": f"t{i}",
				"content": [
					{
						"type": "tool_result",
						"tool_use_id": f"t{i}",
						"content": f"out{i}",
					}
				],
			}
		)
	maybe_update("s1", msgs, min_tool_calls=8, working=working)
	text = load("s1")
	assert text is not None
	assert "ship C2" in text
	assert path_for("s1").is_file()
	mtime = path_for("s1").stat().st_mtime
	maybe_update("s1", msgs, min_tool_calls=8, working=working)
	assert path_for("s1").stat().st_mtime == mtime
	assert "compact_cursor" not in text
	assert "- [ ]" not in text
