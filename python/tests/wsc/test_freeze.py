from __future__ import annotations

from synaptic.freeze import freeze_working_set
from synaptic.assemble import H_CONSTRAINTS, H_REQUESTS
from synaptic.budget import apply_hot_budgets
from synaptic.graph import build_graph
from synaptic.project import project
from synaptic.types import FileState, WscParams
from wsc._fixtures import msg_asst_text, msg_user


def _state(path: str, digest: str, *, last_read: int = 1) -> FileState:
	return FileState(
		path=path,
		observed_hash=digest,
		last_read_idx=last_read,
		read_ranges=((1, 2),),
	)


def test_working_set_reuses_unchanged_file_version_object():
	old = _state("src/a.py", "same", last_read=3)
	now = _state("src/a.py", "same", last_read=9)
	out = freeze_working_set((old,), (now,))
	assert out == (old,)
	assert out[0] is old


def test_working_set_refreshes_changed_file_version():
	old = _state("src/a.py", "old")
	now = _state("src/a.py", "new")
	out = freeze_working_set((old,), (now,))
	assert out == (now,)
	assert out[0] is now


def test_project_freeze_reuses_main_decision_inside_same_phase():
	params = WscParams(
		freeze_main_chain=True,
		freeze_working_set=True,
		journal_layout=False,
	).for_level("Medium+")
	first = [msg_user("完成任务"), msg_asst_text("阶段一")]
	second = first + [msg_user("继续补充上下文"), msg_asst_text("阶段二")]
	p1 = project(second[:2], region_end=2, params=params, session="freeze-test")
	p2 = project(second, region_end=4, params=params, prev=p1.state, session="freeze-test")
	assert p1.state.frozen_phase_signature
	assert p2.state.frozen_phase_signature == p1.state.frozen_phase_signature
	assert p2.state.frozen_region_end == 4
	assert p2.state.frozen_kept == p1.state.frozen_kept


def test_request_floor_takes_space_before_fixed_facts():
	msgs = [msg_user("这是一个足够长的用户问题内容"), msg_asst_text("ok")]
	graph = build_graph(msgs)
	params = WscParams(fixed_segment_budget_tokens=1_800, main_segment_budget_tokens=1_200)
	out, audit = apply_hot_budgets(
		{
			H_CONSTRAINTS: [("pin:0", "约束" * 4_000)],
			H_REQUESTS: [("req:0", "用户原话")],
		},
		params,
		graph=graph,
		region_end=len(msgs),
		request_header=H_REQUESTS,
		request_skip=frozenset(),
		user_nodes=(0,),
		fixed_headers=(H_CONSTRAINTS, H_REQUESTS),
		main_headers=(),
	)
	assert audit.request_reserved_tokens == 1_000
	assert audit.request_mode == "full"
	assert audit.request_tokens > 0
	assert audit.fixed_tokens <= audit.fixed_budget_tokens
	assert H_REQUESTS in out
