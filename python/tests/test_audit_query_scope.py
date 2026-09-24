"""审计查询的作用域必须能被调用方读出来：一个空格不能把"这个会话的证据"变成整库导出。

``AuditLog.query`` 把 strip 后为空的 session_id 当作"不过滤"，而
``/v1/audit/trace`` 还把未 strip 的原值再交给 TraceGraph 比对——两处口径不一致时，
前者跨会话泄数据、后者交出空快照。现在边缘统一 422。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from audit.log import AuditLog, reset_default_audit_log
from server.app import app


@pytest.fixture
def client():
	reset_default_audit_log()
	yield TestClient(app)
	reset_default_audit_log()


@pytest.fixture
def seed(tmp_path):
	reset_default_audit_log()
	log = AuditLog(tmp_path / "audit.jsonl")
	import audit.log as mod

	mod._default = log
	for sid in ("alpha", "bravo"):
		log.record("model.started", session_id=sid, turn_id=f"{sid}-t1", ts=1.0)
		log.record("model.finished", session_id=sid, turn_id=f"{sid}-t1", ts=1.1, status="ok")
	return log


@pytest.mark.parametrize("blank", [" ", "  ", "\t"])
def test_blank_session_id_is_refused_not_widened(client, seed, blank: str) -> None:
	res = client.get("/v1/audit/events", params={"session_id": blank})
	assert res.status_code == 422, f"空白值曾把查询放大成整库：{res.status_code}"
	res = client.get("/v1/audit/trace", params={"session_id": blank})
	assert res.status_code == 422


def test_per_session_query_returns_only_that_session(client, seed) -> None:
	res = client.get("/v1/audit/events", params={"session_id": "alpha"})
	assert res.status_code == 200
	body = res.json()
	assert body["scope"] == "session"
	assert {e["session_id"] for e in body["events"]} == {"alpha"}
	assert body["count"] == 2


def test_omitting_the_key_is_still_a_store_wide_query(client, seed) -> None:
	res = client.get("/v1/audit/events")
	assert res.status_code == 200
	body = res.json()
	assert body["scope"] == "all_sessions"
	assert body["session_id"] == ""
	assert {e["session_id"] for e in body["events"]} == {"alpha", "bravo"}


@pytest.mark.parametrize("alias", ["alpha.", ".alpha", "al:pha", "alpha\x00", "a/b"])
def test_aliasing_session_ids_are_refused(client, seed, alias: str) -> None:
	res = client.get("/v1/audit/events", params={"session_id": alias})
	assert res.status_code == 422, f"{alias!r} 与 alpha 清洗后同名却未被拒绝"
	res = client.get("/v1/audit/trace", params={"session_id": alias})
	assert res.status_code == 422


def test_blank_kind_is_refused(client, seed) -> None:
	res = client.get("/v1/audit/events", params={"session_id": "alpha", "kind": "  "})
	assert res.status_code == 422


def test_prefix_kind_still_works(client, seed) -> None:
	res = client.get("/v1/audit/events", params={"session_id": "alpha", "kind": "model."})
	assert res.status_code == 200
	assert res.json()["count"] == 2


def test_trace_for_real_session_is_not_empty(client, seed) -> None:
	res = client.get("/v1/audit/trace", params={"session_id": "bravo"})
	assert res.status_code == 200
	# 旧实现在这里把 "bravo" 与 strip 后的值分两路传下去；任何一侧带空白都会得到空快照。
	assert res.json().get("session_id", "bravo") == "bravo"
