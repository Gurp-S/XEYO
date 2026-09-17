from __future__ import annotations

from synaptic.graph import build_graph
from synaptic.project import project
from synaptic.rehydrate import (
	decay_leases,
	leased_paths,
	plan_working_set_rehydration,
	renew_leases,
	working_set_paths,
)
from synaptic.types import FileState, WscParams
from wsc._fixtures import msg_asst_use, msg_tool, msg_user


def _state(path: str) -> FileState:
	return FileState(path, "hash", 3, ((1, 2),))


def _messages() -> list[dict]:
	return [
		msg_user("修复 src/a.py 和 src/b.py"),
		msg_asst_use("r1", "Read", {"path": "src/a.py"}),
		msg_tool("r1", "Read", "a evidence"),
		msg_asst_use("r2", "Read", {"path": "src/b.py"}),
		msg_tool("r2", "Read", "b evidence"),
	]


def test_rehydration_is_path_exact_and_deterministic():
	g = build_graph(_messages())
	states = (_state("src/a.py"), _state("src/b.py"))
	a = plan_working_set_rehydration(g, states, region_end=len(g.nodes), budget_tokens=100)
	b = plan_working_set_rehydration(g, states, region_end=len(g.nodes), budget_tokens=100)
	assert a == b
	assert a.paths == ("src/a.py", "src/b.py")
	assert set(a.nodes) == {0, 1, 2, 3, 4}


def test_rehydration_covers_each_path_before_filling_budget():
	g = build_graph(_messages())
	states = (_state("src/a.py"), _state("src/b.py"))
	plan = plan_working_set_rehydration(g, states, region_end=len(g.nodes), budget_tokens=3)
	assert len(plan.nodes) == 1
	assert plan.nodes[0] in {2, 4}


def test_rehydration_respects_region_and_exclusions():
	g = build_graph(_messages())
	states = (_state("src/a.py"), _state("src/b.py"))
	plan = plan_working_set_rehydration(
		g, states, region_end=4, budget_tokens=100, exclude={2}
	)
	assert 2 not in plan.nodes
	assert all(idx < 4 for idx in plan.nodes)
	assert set(plan.nodes) == {0, 1, 3}


def test_working_set_paths_deduplicates_without_sorting():
	assert working_set_paths((_state("b"), _state("a"), _state("b"))) == ("b", "a")


def test_rehydration_lease_preserves_working_set_and_expires_elsewhere():
	first = renew_leases((), selected_paths=("src/a.py",), initial_lease=3, refresh_lease=5)
	assert first == (("src/a.py", 3),)
	assert decay_leases(first, working_paths=("src/a.py",)) == (("src/a.py", 3),)
	refreshed = renew_leases(
		decay_leases(first, working_paths=()),
		selected_paths=("src/a.py",),
		initial_lease=3,
		refresh_lease=5,
	)
	assert refreshed == (("src/a.py", 5),)
	assert leased_paths(decay_leases(first, working_paths=())) == ("src/a.py",)
	assert leased_paths(decay_leases((("src/a.py", 1),), working_paths=())) == ()


def test_rehydration_lease_deduplicates_append_only_recall():
	msgs = _messages()
	params = WscParams(
		main_segment_budget_tokens=300,
		auto_rehydrate_working_set=True,
		rehydrate_budget_tokens=100,
		journal_layout=True,
	)
	first = project(
		msgs,
		region_end=len(msgs),
		params=params,
		rehydrate_paths=("src/a.py",),
		session="lease-test",
	)
	second = project(
		msgs + [msg_user("继续")],
		region_end=len(msgs) + 1,
		params=params,
		prev=first.state,
		cold=first.cold,
		session="lease-test",
	)
	assert first.result.hot.rehydrated_nodes
	assert second.state.rehydration_leases
	assert second.text.count("a evidence") == first.text.count("a evidence")


def test_project_rehydrates_only_when_opted_in():
	msgs = _messages()
	base = project(msgs, region_end=len(msgs))
	on = project(
		msgs,
		region_end=len(msgs),
		params=WscParams(
			main_segment_budget_tokens=300,
			auto_rehydrate_working_set=True,
			rehydrate_budget_tokens=100,
		),
		rehydrate_paths=("src/a.py", "src/b.py"),
	)
	assert base.result.hot.rehydrated_nodes == ()
	assert on.result.hot.rehydrated_nodes
	assert "[REHYDRATED]" in on.text
