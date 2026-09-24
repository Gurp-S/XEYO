"""信息丢失定位链：没记账的级别必须挡住归因。"""

from __future__ import annotations

import json

from diagnostics.collect import collect_run
from diagnostics.loss_chain import ABSENT, FOUND, NOT_CAPTURED, NOT_RECORDED, UNREADABLE, trace_fact
from session.persistence import transcript_path


def _transcript(session_id: str, rows: list[dict]) -> None:
	path = transcript_path(session_id)
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def _working(session_id: str, payload: dict) -> None:
	from memory.working import path_for

	path = path_for(session_id)
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _run(tmp_path, session_id: str = "s1", turn_id: str = "t1"):
	path = tmp_path / "audit.jsonl"
	path.write_text(
		json.dumps(
			{
				"ts": 1.0,
				"kind": "model.started",
				"session_id": session_id,
				"turn_id": turn_id,
				"model_request_id": "r1",
				"attempt": 1,
				"projection_id": "p1",
			}
		)
		+ "\n",
		encoding="utf-8",
	)
	return collect_run(session_id, turn_id, audit_path=path)


def _states(doc: dict) -> dict[str, str]:
	return {s["stage"]: s["state"] for s in doc["stages"]}


def test_missing_transcript_is_not_reported_as_absent(tmp_path) -> None:
	doc = trace_fact(_run(tmp_path), "部署前先跑迁移")
	assert doc["stages"][0]["state"] == NOT_CAPTURED
	assert doc["verdict"] == "unknown"
	assert "不得报「不存在」" in doc["stages"][0]["note"]


def test_fact_in_source_and_emitted_is_kept_through(tmp_path) -> None:
	sent = json.dumps([{"role": "user", "content": "部署前先跑迁移"}], ensure_ascii=False)
	_transcript("s1", [{"id": "m1", "role": "user", "ts": 0.5, "content": "部署前先跑迁移"}])
	_working("s1", {"session_id": "s1", "last_x_sent": sent})
	doc = trace_fact(_run(tmp_path), "部署前先跑迁移")
	states = _states(doc)
	assert states["source_history"] == FOUND and states["emitted"] == FOUND
	assert doc["verdict"] == "kept_through"
	assert "不能排除" in doc["statement"]
	assert "不等于" in doc["caveat"]


def test_lost_in_source_history_is_a_real_negative(tmp_path) -> None:
	_transcript("s1", [{"id": "m1", "role": "user", "ts": 0.5, "content": "换个别的话题"}])
	doc = trace_fact(_run(tmp_path), "部署前先跑迁移")
	assert _states(doc)["source_history"] == ABSENT
	assert doc["verdict"] == "not_in_source_history"
	assert "不是这次压缩丢的" in doc["statement"]


def test_candidate_and_selected_have_no_ledger(tmp_path) -> None:
	_transcript("s1", [{"id": "m1", "role": "user", "ts": 0.5, "content": "部署前先跑迁移"}])
	states = _states(trace_fact(_run(tmp_path), "部署前先跑迁移"))
	assert states["candidate"] == NOT_RECORDED
	assert states["selected"] in {NOT_RECORDED, "not_captured"}


def test_unreadable_blob_blocks_the_chain(tmp_path) -> None:
	path = transcript_path("s1")
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(
		json.dumps({"id": "m1", "role": "user", "ts": 0.5, "content_ref": "m1.json", "content_hash": "sha256:x"}) + "\n",
		encoding="utf-8",
	)
	doc = trace_fact(_run(tmp_path), "部署前先跑迁移")
	assert doc["stages"][0]["state"] == UNREADABLE
	assert doc["verdict"] == "unknown"


def test_fact_visible_only_in_structured_state(tmp_path) -> None:
	_transcript("s1", [{"id": "m1", "role": "user", "ts": 0.5, "content": "无关内容"}])
	_working("s1", {"session_id": "s1", "todos": [{"content": "部署前先跑迁移", "status": "pending"}]})
	doc = trace_fact(_run(tmp_path), "部署前先跑迁移")
	states = _states(doc)
	assert states["source_history"] == ABSENT
	assert states["structured_state"] == FOUND
	assert doc["verdict"] == "not_in_source_history"


def test_in_source_but_not_emitted_localizes_to_emission(tmp_path) -> None:
	"""源历史有、发射投影没有 ⇒ 定位到发射级，并说明中间两级没有账本。"""
	sent = json.dumps([{"role": "user", "content": "无关内容"}], ensure_ascii=False)
	_transcript("s1", [{"id": "m1", "role": "user", "ts": 0.5, "content": "部署前先跑迁移"}])
	_working("s1", {"session_id": "s1", "last_x_sent": sent})
	doc = trace_fact(_run(tmp_path), "部署前先跑迁移")
	states = _states(doc)
	assert states["source_history"] == FOUND
	assert states["emitted"] == ABSENT
	assert doc["verdict"] == "lost_before:emitted"
	assert "没有落盘账本" in doc["statement"]
	assert set(doc["unprovable_stages"]) >= {"candidate", "selected"}


def test_empty_needle_is_rejected(tmp_path) -> None:
	import pytest

	with pytest.raises(ValueError):
		trace_fact(_run(tmp_path), "   ")
