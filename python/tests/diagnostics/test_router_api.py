"""诊断路由的行为：分页可见、缺项不补值、固定证据能进规则、费用未知不是 0。"""

from __future__ import annotations

import copy
import json

import pytest
from fastapi.testclient import TestClient

from audit.log import AuditLog, reset_default_audit_log
from server.app import app

_ROWS = [
	{"kind": "model.started", "ts": 1.0, "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "projection_id": "p1"},
	{"kind": "model.finished", "ts": 1.1, "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "ok", "projection_id": "p1"},
	{"kind": "tool.started", "ts": 1.2, "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Read", "model_request_id": "r1"},
	{"kind": "tool.finished", "ts": 1.3, "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Read", "is_error": True, "error_kind": "NOT_FOUND", "model_request_id": "r1"},
]


@pytest.fixture
def client():
	reset_default_audit_log()
	yield TestClient(app)
	reset_default_audit_log()


@pytest.fixture
def seed_audit(tmp_path):
	def _seed(rows=None) -> AuditLog:
		reset_default_audit_log()
		log = AuditLog(tmp_path / "audit.jsonl")
		import audit.log as mod

		mod._default = log
		for row in rows if rows is not None else _ROWS:
			payload = dict(copy.deepcopy(row))
			log.record(payload.pop("kind"), **payload)
		return log

	return _seed


def test_runs_list_shape(client, seed_audit) -> None:
	seed_audit()
	body = client.get("/v1/diagnostics/runs", params={"session_id": "s1"}).json()
	assert body["count"] == 1
	run = body["runs"][0]
	assert run["turn_id"] == "t1"
	assert set(run["boundaries"]) == {"model_request", "tool_permission"}
	assert isinstance(body["complete"], bool)


def test_run_detail_paginates_events_and_shows_cursor(client, seed_audit) -> None:
	seed_audit()
	first = client.get("/v1/diagnostics/runs/t1", params={"session_id": "s1", "event_limit": 2}).json()
	assert first["event_total"] == 4
	assert len(first["events"]) == 2
	assert first["events_complete"] is False
	assert first["next_event_cursor"] == "2"
	second = client.get(
		"/v1/diagnostics/runs/t1", params={"session_id": "s1", "event_limit": 2, "event_offset": 2}
	).json()
	assert second["events_complete"] is True
	assert second["next_event_cursor"] == ""
	kinds = {e["kind"] for e in first["events"] + second["events"]}
	assert kinds == {"model.started", "model.finished", "tool.started", "tool.finished"}


def test_run_detail_does_not_invent_missing_identity(client, seed_audit) -> None:
	seed_audit()
	body = client.get("/v1/diagnostics/runs/t1", params={"session_id": "s1"}).json()
	tool = body["tool_calls"][0]
	assert tool["projection_id"] == ""
	assert body["identity"]["approval_ids"] == []
	assert body["coverage"]["captures"]["state"] in {"absent", "partial"}
	assert any(g["reason"] == "not_captured" for g in body["gaps"])
	assert body["versions"]["commit"] != ""


def test_usage_gap_survives_to_report(client, seed_audit) -> None:
	seed_audit()
	body = client.get("/v1/diagnostics/runs/t1", params={"session_id": "s1"}).json()
	usage = body["usage_summary"]
	assert usage["unknown_cost_attempts"] == 1
	assert usage["estimated_total_cny"] == 0.0
	assert "费用未知" in usage["statement"]
	assert body["attribution"]["first_anomaly_boundary"] == "model_request"


def test_every_finding_carries_evidence(client, seed_audit) -> None:
	seed_audit()
	body = client.get("/v1/diagnostics/runs/t1", params={"session_id": "s1"}).json()
	assert body["findings"]
	for item in body["findings"]:
		assert item["evidence"] or item["status"] == "unknown", item["rule_id"]
		assert item["coverage_gap"], item["rule_id"]
		assert item["allowed_conclusion"], item["rule_id"]


def test_pin_and_verifier_reach_the_rules(client, seed_audit) -> None:
	seed_audit()
	pinned = client.post(
		"/v1/diagnostics/runs/t1/pin",
		params={"session_id": "s1"},
		json={"note": "结果不对", "expected": "应该先修引用"},
	).json()
	assert pinned["ok"] is True
	assert pinned["pin"]["kind"] == "run_mark"
	unrun = client.get("/v1/diagnostics/runs/t1", params={"session_id": "s1"}).json()
	# 只有 run_mark 类 pin、没有 verifier 类 pin：这是采集缺项，不是一条逐轮结论。
	assert [f for f in unrun["findings"] if f["rule_id"] == "verifier"] == []
	assert [
		g
		for g in unrun["gaps"]
		if g["boundary"] == "file_verifier" and g["reason"] == "not_recorded"
	]
	zero = client.post(
		"/v1/diagnostics/runs/t1/verifier",
		params={"session_id": "s1"},
		json={"name": "pytest tests/diagnostics", "command": "pytest", "exit_code": 0},
	).json()
	assert zero["ok"] is True
	body = client.get("/v1/diagnostics/runs/t1", params={"session_id": "s1"}).json()
	ver = [f for f in body["findings"] if f["rule_id"] == "verifier"]
	assert ver and "通过" in ver[0]["phenomenon"]
	assert all(f["status"] != "confirmed_fault" for f in ver)
	two = client.post(
		"/v1/diagnostics/runs/t1/verifier",
		params={"session_id": "s1"},
		json={"name": "pytest 全量", "exit_code": 1},
	).json()
	assert two["ok"] is True
	body = client.get("/v1/diagnostics/runs/t1", params={"session_id": "s1"}).json()
	ver = [f for f in body["findings"] if f["rule_id"] == "verifier"]
	assert any(f["status"] == "confirmed_fault" for f in ver)
	assert any("退出码 0 只证明" in f["coverage_gap"] for f in ver)
	assert client.delete(f"/v1/diagnostics/pins/{pinned['pin']['pin_id']}", params={"session_id": "s1"}).json() == {"ok": True}


def test_pin_requires_note(client, seed_audit) -> None:
	seed_audit()
	res = client.post("/v1/diagnostics/runs/t1/pin", params={"session_id": "s1"}, json={"note": "  "})
	assert res.status_code == 200
	assert res.json()["ok"] is False


def test_capture_toggle_and_capture_body(client, seed_audit) -> None:
	seed_audit()
	before = client.get("/v1/diagnostics/capture", params={"session_id": "s1"}).json()
	assert before["enabled"] is False
	client.post("/v1/diagnostics/capture", json={"session_id": "s1", "enabled": True})
	after = client.get("/v1/diagnostics/capture", params={"session_id": "s1"}).json()
	assert after["enabled"] is True
	assert after["quota_bytes"] > 0
	body = client.get("/v1/diagnostics/runs/t1", params={"session_id": "s1"}).json()
	assert body["captures"] == []
	missing = client.get("/v1/diagnostics/captures/" + "0" * 64).json()
	assert missing["state"] == "not_captured"


def test_fact_chain_over_http(client, seed_audit) -> None:
	seed_audit()
	doc = client.get(
		"/v1/diagnostics/runs/t1/fact", params={"session_id": "s1", "needle": "NOT_FOUND"}
	).json()
	assert len(doc["stages"]) == 7
	assert doc["stages"][0]["state"] in {"absent", "not_captured", "unreadable"}
	assert "不等于" in doc["caveat"] or "不能排除" in doc["statement"]


def test_markdown_export_is_rendered_from_same_structure(client, seed_audit) -> None:
	seed_audit()
	md = client.get("/v1/diagnostics/runs/t1/report.md", params={"session_id": "s1"}).json()["markdown"]
	assert "# XEYO 诊断报告" in md
	assert "覆盖缺口" in md
	assert "按 usage 估算" in md or "无可依据的用量" in md
	saved = client.post("/v1/diagnostics/reports", params={"session_id": "s1", "turn_id": "t1"}).json()
	assert saved["ok"] is True and saved["report_id"].startswith("rep_")
	loaded = client.get(f"/v1/diagnostics/reports/{saved['report_id']}").json()
	assert loaded["ok"] is True
	assert loaded["report"]["turn_id"] == "t1"


def test_message_body_endpoint_reports_missing_transcript(client, seed_audit) -> None:
	seed_audit()
	res = client.get("/v1/diagnostics/messages/m1", params={"session_id": "no_such_session"}).json()
	assert res["ok"] is False
	assert res["error"] == "no_transcript"


def test_a0_plan_is_free_and_reports_no_model_calls(client, seed_audit) -> None:
	seed_audit()
	res = client.post("/v1/diagnostics/experiments/plan", json={"mode": "a0"}).json()
	assert res["ok"] is True
	plan = res["plan"]
	assert plan["billable"] is False
	assert plan["cost_basis"] == "无模型调用"
	assert plan["model_requests"] == 0


def test_unknown_mode_is_rejected_without_starting_anything(client, seed_audit) -> None:
	seed_audit()
	res = client.post(
		"/v1/diagnostics/experiments",
		json={"mode": "A9", "idempotency_key": "router-test-key"},
	).json()
	assert res["ok"] is False
	assert "a0" in res["error"]


def test_runs_envelope_carries_the_scan_coverage_for_the_empty_case(client, seed_audit) -> None:
	"""空列表必须自带口径：读完整份没有 ≠ 尾窗没盖到 ≠ 文件不存在。

	runs 的 coverage_note 挂在每一条 run 上，零条时没有承载处 —— 界面就只剩一句
	"该会话在审计尾窗内没有轮次记录"，而扩窗之后这句话多半是错的。
	"""
	seed_audit()
	body = client.get("/v1/diagnostics/runs", params={"session_id": "s1"}).json()
	assert body["count"] == 1
	cov = body["coverage"]
	assert cov["present"] is True and cov["truncated"] is False
	assert cov["complete"] is True and cov["widened"] is False

	missing = client.get("/v1/diagnostics/runs", params={"session_id": "s-nope"}).json()
	assert missing["count"] == 0
	assert missing["coverage"]["present"] is True, "文件在，就不能推给「审计不存在」"
	assert missing["coverage"]["truncated"] is False, "已读完整份，就不能推给尾窗"
	assert missing["coverage"]["rows_scanned"] >= 4


def test_run_detail_transports_the_current_vocabulary(client, seed_audit) -> None:
	"""新枚举必须真能走通 HTTP：单测与界面 fixture 都看不见传输层。

	钉三样今天改过的东西：归因字段改名（last_normal_* → last_evidenced_*）、
	任务结局新增的 self_reported_unverified、以及从厂商失败里拆出来的
	request_shape_rejected。路由若在别处按白名单拷字段，这里就会红。
	"""
	from session.persistence import transcript_path

	seed_audit(
		[
			{"kind": "model.started", "ts": 1.0, "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "projection_id": "p1"},
			{"kind": "model.finished", "ts": 1.1, "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "protocol_fallback", "error_code": "HTTP_400", "projection_id": "p1"},
		]
	)
	path = transcript_path("s1")
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(
		"".join(
			json.dumps(row, ensure_ascii=False) + "\n"
			for row in (
				{"id": "m1", "role": "user", "ts": 0.9, "content": "改完必须跑 pytest"},
				{"id": "m2", "role": "assistant", "ts": 1.2, "content": "已完成，测试通过"},
			)
		),
		encoding="utf-8",
	)

	body = client.get("/v1/diagnostics/runs/t1", params={"session_id": "s1"}).json()
	att = body["attribution"]
	assert "last_evidenced_boundary" in att
	assert "last_normal_boundary" not in att and "last_normal_label" not in att
	fault = body["fault"]
	assert fault["task_outcome"] == "self_reported_unverified"
	codes = [c["code"] for c in fault["causes"]]
	assert "request_shape_rejected" in codes, codes


def test_sessions_endpoint_lists_ledger_only_sessions(client, seed_audit) -> None:
	"""会话选择器的候选不能只有聊天列表：账本里有证据的会话要列得出来。

	聊天列表按 ``sessions/*.jsonl`` 枚举，所以"转录丢了"与"子代理会话"两类
	在选择器里一个都点不到 —— 实测 29%（45/155）的轮次报告属于前者。
	"""
	seed_audit(
		[
			{"kind": "model.started", "ts": 1.0, "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
			{"kind": "model.finished", "ts": 1.1, "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "ok"},
			{"kind": "tool.started", "ts": 5.0, "session_id": "ghost_agent", "turn_id": "g1", "request_id": "c1", "tool_name": "Read"},
		]
	)
	body = client.get("/v1/diagnostics/sessions").json()
	assert body["schema_version"]
	by_id = {r["session_id"]: r for r in body["sessions"]}
	assert set(by_id) == {"s1", "ghost_agent"}
	assert by_id["s1"]["event_rows"] == 2 and by_id["s1"]["turn_count"] == 1
	assert by_id["ghost_agent"]["event_rows"] == 1
	assert body["count"] == 2 and body["complete"] is True
	assert body["coverage"]["total_sessions"] == 2 and body["coverage"]["note"] == ""
	# 最近在前：面板里默认露出的是刚跑过的那批
	assert body["sessions"][0]["session_id"] == "ghost_agent"


def test_sessions_endpoint_does_not_pass_a_cut_list_as_the_total(client, seed_audit) -> None:
	"""limit 砍掉时 complete 必须翻假并给出总会话数：条数不是总数。"""
	seed_audit(
		[
			{"kind": "model.started", "ts": 1.0, "session_id": "a", "turn_id": "ta", "model_request_id": "ra", "attempt": 1},
			{"kind": "model.started", "ts": 2.0, "session_id": "b", "turn_id": "tb", "model_request_id": "rb", "attempt": 1},
			{"kind": "model.started", "ts": 3.0, "session_id": "c", "turn_id": "tc", "model_request_id": "rc", "attempt": 1},
		]
	)
	body = client.get("/v1/diagnostics/sessions", params={"limit": 2}).json()
	assert body["count"] == 2
	assert body["complete"] is False
	assert body["coverage"]["total_sessions"] == 3
	assert "共 3 个，只返回最近 2 个" in body["coverage"]["note"], body["coverage"]["note"]


def test_a_ledger_only_session_is_then_diagnosable(client, seed_audit) -> None:
	"""列出来的唯一目的是选得到：拿到 id 后轮次列表必须真的能开。"""
	seed_audit(
		[
			{"kind": "model.started", "ts": 4.0, "session_id": "ghost", "turn_id": "g1", "model_request_id": "r1", "attempt": 1},
			{"kind": "model.started", "ts": 5.0, "session_id": "ghost", "turn_id": "g2", "model_request_id": "r2", "attempt": 1},
		]
	)
	sessions = client.get("/v1/diagnostics/sessions").json()["sessions"]
	assert [s["session_id"] for s in sessions] == ["ghost"]
	runs = client.get("/v1/diagnostics/runs", params={"session_id": "ghost"}).json()
	assert runs["count"] == 2, runs
	assert {r["turn_id"] for r in runs["runs"]} == {"g1", "g2"}
