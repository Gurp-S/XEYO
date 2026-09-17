from __future__ import annotations

from synaptic.graph import build_graph
from synaptic.retrieval import (
	HistoryQuery,
	build_current_state,
	build_history_query,
	discover_history,
	render_history_hints,
)
from synaptic.seeds import Seeds
from synaptic.types import FileState
from wsc._fixtures import msg_asst_use, msg_tool, msg_user


def _fs(path: str, *, stale: bool = False) -> FileState:
	return FileState(path, "hash", 3, ((1, 2),), stale=stale)


def _messages() -> list[dict]:
	return [
		msg_user("修复 src/auth.py 的登录超时，不要修改数据库表结构"),
		msg_asst_use("u1", "Read", {"path": "src/auth.py"}),
		msg_tool("u1", "Read", "auth evidence"),
		msg_asst_use("u2", "pytest", {"command": "pytest src/auth.py"}),
		msg_tool("u2", "pytest", "FAILED src/auth.py::test_timeout", is_error=True),
	]


def _query(graph, *, max_candidates: int = 64) -> HistoryQuery:
	seeds = Seeds(
		goal="修复登录超时",
		original_task="修复 src/auth.py 的登录超时，不要修改数据库表结构",
		constraints=("不要修改数据库表结构",),
		# 查询使用 graph 提取出的稳定错误签名，而不是工具输出的整行文本。
		unresolved_errors=("src/auth.py::test_timeout",),
		pin_nodes=(0, 4),
		user_nodes=(0,),
	)
	state = build_current_state(
		seeds,
		{"src/auth.py": _fs("src/auth.py", stale=True)},
		working_paths=("src/auth.py",),
	)
	return build_history_query(state, region_end=len(graph.nodes), max_candidates=max_candidates)


def test_current_state_is_built_without_selection_output():
	graph = build_graph(_messages())
	query = _query(graph)
	assert query.paths == ("src/auth.py",)
	assert query.constraints == ("不要修改数据库表结构",)
	assert query.unresolved_errors == ("src/auth.py::test_timeout",)
	assert query.request_nodes == (0,)
	assert query.anchor_nodes == (0, 4)


def test_discovery_uses_explicit_path_error_and_hard_provenance():
	graph = build_graph(_messages(), include_soft_edges=True)
	items = discover_history(graph, _query(graph))
	by_idx = {item.idx: item for item in items}
	assert {0, 1, 2, 3, 4}.issubset(by_idx)
	assert "state_anchor" in by_idx[0].reasons
	assert "unresolved_error_exact" in by_idx[4].reasons
	assert "working_path_exact" in by_idx[1].reasons
	assert "hard_provenance" in by_idx[3].reasons
	assert by_idx[3].handle == "node://3"


def test_discovery_is_deterministic_and_region_bounded():
	graph = build_graph(_messages(), include_soft_edges=True)
	query = _query(graph, max_candidates=3)
	assert discover_history(graph, query) == discover_history(graph, query)
	assert len(discover_history(graph, query)) == 3
	assert all(item.idx < query.region_end for item in discover_history(graph, query))


def test_discovery_does_not_use_soft_edges_as_provenance():
	graph = build_graph(_messages(), include_soft_edges=True)
	query = HistoryQuery(region_end=len(graph.nodes), anchor_nodes=(4,))
	items = discover_history(graph, query)
	assert all(
		item.idx not in {0, 1, 2, 3} or "hard_provenance" in item.reasons or item.idx == 4
		for item in items
	)


def test_explicit_working_paths_do_not_expand_to_all_file_states():
	seeds = Seeds(goal="g", original_task="g", pin_nodes=(0,), user_nodes=(0,))
	state = build_current_state(
		seeds,
		{"src/a.py": _fs("src/a.py"), "src/old.py": _fs("src/old.py")},
		working_paths=("src/a.py",),
	)
	assert state.working_paths == ("src/a.py",)


def test_history_hints_are_fact_only_bounded_and_readable():
	graph = build_graph(_messages())
	items = discover_history(graph, _query(graph))
	lines = render_history_hints(graph, items, budget_tokens=2000, max_items=3)
	assert lines
	text = "\n".join(line for _key, line in lines)
	assert "event=" in text
	assert "match=path:src/auth.py" in text
	assert "detail=expand(node://" in text
	assert "建议" not in text
	assert "应该" not in text
	assert len(lines) <= 3
