"""β1：GET /v1/audit/events 契约测试。

覆盖：空日志、按 session_id/kind 筛选、limit/offset、坏行容忍、自举可读 permission/tool 事件。
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
	sys.path.insert(0, str(_ROOT))

from fastapi.testclient import TestClient

from audit.log import AuditLog, reset_default_audit_log
from server.app import app


def _client() -> TestClient:
	return TestClient(app)


def _inject_audit(tmp_path) -> AuditLog:
	reset_default_audit_log()
	log = AuditLog(tmp_path / "audit.jsonl")
	import audit.log as mod

	mod._default = log
	return log


def test_audit_events_empty(tmp_path, monkeypatch) -> None:
	_inject_audit(tmp_path)
	c = _client()
	r = c.get("/v1/audit/events")
	assert r.status_code == 200
	body = r.json()
	assert body["events"] == []
	assert body["count"] == 0
	assert body["limit"] == 100
	assert body["offset"] == 0


def test_audit_events_filter_session_kind_and_pagination(tmp_path) -> None:
	log = _inject_audit(tmp_path)
	log.record("tool.started", session_id="s1", tool_name="Write")
	log.record("tool.finished", session_id="s1", tool_name="Write", duration_ms=2)
	log.record("permission.pending", session_id="s2", tool_name="Bash")
	log.record("tool.started", session_id="s1", tool_name="Read")

	c = _client()
	r = c.get("/v1/audit/events", params={"session_id": "s1", "kind": "tool.started"})
	assert r.status_code == 200
	body = r.json()
	# 新→旧
	kinds = [e["kind"] for e in body["events"]]
	sessions = {e["session_id"] for e in body["events"]}
	assert kinds == ["tool.started", "tool.started"]
	assert sessions == {"s1"}
	assert body["count"] == 2

	r2 = c.get(
		"/v1/audit/events",
		params={"session_id": "s1", "kind": "tool.started", "limit": 1, "offset": 1},
	)
	assert r2.status_code == 200
	page = r2.json()
	assert page["count"] == 1
	assert page["events"][0]["tool_name"] == "Write"
	assert page["limit"] == 1
	assert page["offset"] == 1


def test_audit_events_kind_prefix_and_since(tmp_path) -> None:
	log = _inject_audit(tmp_path)
	log.record("permission.pending", session_id="s", tool_name="Write", ts=100.0)
	# record() 会覆盖 ts；直接写文件控制时间戳
	log.path.write_text(
		'{"ts":100.0,"kind":"permission.pending","session_id":"s","tool_name":"Write"}\n'
		'{"ts":200.0,"kind":"permission.resolved","session_id":"s","outcome":"user_decided"}\n'
		'{"ts":300.0,"kind":"tool.started","session_id":"s","tool_name":"Read"}\n',
		encoding="utf-8",
	)

	c = _client()
	r = c.get("/v1/audit/events", params={"kind": "permission.", "since_ts": 150})
	assert r.status_code == 200
	body = r.json()
	assert [e["kind"] for e in body["events"]] == ["permission.resolved"]


def test_audit_events_tolerates_bad_lines(tmp_path) -> None:
	log = _inject_audit(tmp_path)
	log.record("tool.finished", session_id="s", tool_name="Grep")
	with log.path.open("a", encoding="utf-8") as fh:
		fh.write("not-json\n")
	c = _client()
	r = c.get("/v1/audit/events")
	assert r.status_code == 200
	assert r.json()["count"] == 1


def test_audit_events_bootstrap_after_permission_and_tool(tmp_path) -> None:
	"""终验 #13 自举：写入 permission/tool 事件后 API 能查到。"""
	log = _inject_audit(tmp_path)
	log.record(
		"permission.pending",
		session_id="boot",
		tool_name="Write",
		reason="needs_confirmation",
	)
	log.record(
		"permission.resolved",
		session_id="boot",
		tool_name="Write",
		outcome="user_decided",
		actor="desktop",
	)
	log.record("tool.started", session_id="boot", tool_name="Write")
	log.record("tool.finished", session_id="boot", tool_name="Write", duration_ms=5)

	c = _client()
	r = c.get("/v1/audit/events", params={"session_id": "boot"})
	assert r.status_code == 200
	kinds = [e["kind"] for e in r.json()["events"]]
	assert kinds == [
		"tool.finished",
		"tool.started",
		"permission.resolved",
		"permission.pending",
	]
