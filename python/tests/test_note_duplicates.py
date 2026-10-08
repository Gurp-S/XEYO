"""同一 ``note_key`` 多版本的计数事实（③ 的"仍在发生"指标）。

事故形态（2026-10-08 本会话实测）：同回合内该行数字逐枪变 ⇒ 旧副本撤不掉、新片段照发，
模型同时看到两份。冻结治因；本模块把"仍在发生"变成可数事实。
"""

from __future__ import annotations

from prompt import note_duplicates
from prompt.state_emission import select_rendered_state


def test_two_versions_count_once() -> None:
	note_duplicates.reset()
	rows = [
		{"note_key": "world_state", "content": "本会话上下文: 120k"},
		{"note_key": "world_state", "content": "本会话上下文: 121k"},
	]
	assert note_duplicates.observe(rows, where="t") == 1
	assert note_duplicates.snapshot()["events"]["t"] == 1


def test_same_text_is_not_two_versions() -> None:
	note_duplicates.reset()
	rows = [
		{"note_key": "world_state", "content": "same"},
		{"note_key": "world_state", "content": "same"},
	]
	assert note_duplicates.observe(rows, where="t") == 0
	assert note_duplicates.snapshot()["events"].get("t", 0) == 0


def test_rows_without_note_key_are_ignored() -> None:
	note_duplicates.reset()
	rows = [{"content": "a"}, {"content": "b"}]
	assert note_duplicates.observe(rows, where="t") == 0


def test_projection_records_duplicates_and_keeps_one() -> None:
	"""投影侧回归：两个版本并存时只留最新那份，并且计数一次（原先无人可数）。"""
	note_duplicates.reset()
	old = {"role": "user", "content": "…120k…", "note_key": "world_state"}
	new = {"role": "user", "content": "…121k…", "note_key": "world_state"}
	current = {"world_state": {"role": "user", "content": "…121k…"}}
	kept = select_rendered_state([], [old, new], current, "notice_fragment")
	assert [row["content"] for row in kept] == ["…121k…"]
	assert note_duplicates.snapshot()["events"]["select_rendered_state"] == 1


def test_projection_single_version_records_nothing() -> None:
	note_duplicates.reset()
	new = {"role": "user", "content": "…121k…", "note_key": "world_state"}
	current = {"world_state": {"role": "user", "content": "…121k…"}}
	kept = select_rendered_state([], [new], current, "notice_fragment")
	assert len(kept) == 1
	assert note_duplicates.snapshot()["events"].get("select_rendered_state", 0) == 0
