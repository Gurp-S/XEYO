from __future__ import annotations

from engine.trace_graph import TraceGraph


def test_trace_graph_links_projection_model_tool_and_action_without_payloads() -> None:
	graph = TraceGraph.from_audit_rows(
		[
			{
				"ts": 2,
				"kind": "tool.finished",
				"session_id": "s1",
				"turn_id": "t1",
				"request_id": "call1",
				"tool_name": "Bash",
				"action_id": "act1",
				"model_request_id": "model1",
				"projection_id": "proj1",
				"command_summary": "secret should not be copied",
				"content": "result should not be copied",
			},
			{
				"ts": 1,
				"kind": "model.started",
				"session_id": "s1",
				"turn_id": "t1",
				"model_request_id": "model1",
				"projection_id": "proj1",
			},
		],
		max_events=20,
	)
	snapshot = graph.snapshot()
	ids = {node["id"] for node in snapshot["nodes"]}
	assert {"session:s1", "projection:proj1", "model:model1", "tool:call1", "action:act1"} <= ids
	assert all("content" not in node["fields"] for node in snapshot["nodes"])
	assert all("command_summary" not in node["fields"] for node in snapshot["nodes"])
	assert {edge["kind"] for edge in snapshot["edges"]} >= {
		"produced",
		"emitted",
		"dispatches",
	}


def test_trace_graph_filters_session_and_bounds_events() -> None:
	graph = TraceGraph.from_audit_rows(
		[
			{"ts": 1, "kind": "model.started", "session_id": "other", "request_id": "x"},
			{"ts": 2, "kind": "model.started", "session_id": "s1", "request_id": "a"},
			{"ts": 3, "kind": "model.finished", "session_id": "s1", "request_id": "a"},
		],
		session_id="s1",
		max_events=1,
	)
	snapshot = graph.snapshot()
	assert snapshot["session_id"] == "s1"
	assert snapshot["node_counts"].get("event") == 1
	assert all(node["fields"].get("request_id") != "x" for node in snapshot["nodes"])
