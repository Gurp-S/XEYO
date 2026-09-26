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


def _attributable(run):
	"""把留存投影的时刻钉回本运行：发射级的"落空"只有在归属核得上时才有结论资格。

	生产里审计行带着 projection_id、working 带着那份投影的 created_at；两者都对不上时
	判据说不出"丢在发射之前"（#68），所以断言这条结论的夹具必须先把这一枪摆实。
	"""
	run.projections = [{"projection_id": "p1", "created_at": 1.0}]
	return run


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
	doc = trace_fact(_attributable(_run(tmp_path)), "部署前先跑迁移")
	states = _states(doc)
	assert states["source_history"] == FOUND
	assert states["emitted"] == ABSENT
	assert doc["verdict"] == "lost_before:emitted"
	assert "没有落盘账本" in doc["statement"]
	assert set(doc["unprovable_stages"]) >= {"candidate", "selected"}


def test_folded_out_is_distinguished_from_never_emitted(tmp_path, monkeypatch) -> None:
	"""折叠游标把"被折掉"和"从未进入投影"分开 —— 用既有记录，不新建账本。"""
	constraint = "部署前先跑迁移"
	_transcript("s1", [{"id": f"m{i}", "role": "user", "ts": 0.1 * i, "content": constraint if i == 2 else "无关"} for i in range(1, 8)])
	_working("s1", {"session_id": "s1", "last_x_sent": json.dumps([{"content": "无关"}], ensure_ascii=False), "compact_cursor": 5})
	import diagnostics.collect as coll

	run = _attributable(_run(tmp_path))
	# collect 只在 in-run 行上留正文，这里直接补一份等价视图
	run.transcript_rows = [
		{"id": "m2", "role": "user", "line_no": 2, "content": constraint, "locator": "s1.jsonl"},
	]
	run.working["compact_cursor"] = 5
	assert run.working.get("compact_cursor") == 5
	doc = trace_fact(run, constraint)
	stage = next(s for s in doc["stages"] if s["stage"] == "emitted")
	assert stage["state"] == "folded_out"
	assert doc["verdict"] == "folded_out_of_projection"
	assert "折叠" in doc["statement"]
	# 游标口径变化时必须自我怀疑
	assert "前提是 transcript 行序与游标同为消息序号" in stage["note"]


def test_after_cursor_hit_is_still_never_emitted(tmp_path, monkeypatch) -> None:
	constraint = "部署前先跑迁移"
	run = _attributable(_run(tmp_path))
	run.transcript_rows = [{"id": "m9", "role": "user", "line_no": 9, "content": constraint, "locator": "s1.jsonl"}]
	run.working["compact_cursor"] = 5
	_stub_last_sent(monkeypatch, json.dumps([{"content": "无关"}], ensure_ascii=False))
	doc = trace_fact(run, constraint)
	stage = next(s for s in doc["stages"] if s["stage"] == "emitted")
	assert stage["state"] == "absent"
	assert doc["verdict"] == "lost_before:emitted"


def _stub_last_sent(monkeypatch, sent: str) -> None:
	"""换掉发射级读的那份投影，用完必须自动还原。

	原先这是一句裸赋值（``lc._last_sent_projection = lambda …``）：模块级补丁不随用例
	还原，后面每条用例读到的都是这里塞进去的那一份 —— 新用例会在别人的桩上"通过"，
	断言的其实不是自己的夹具。
	"""
	import diagnostics.loss_chain as lc

	monkeypatch.setattr(lc, "_last_sent_projection", lambda sid: (sent, "working.json"))


def test_unbound_miss_does_not_localize_to_emission(tmp_path) -> None:
	"""发射级落空但归属核不上 ⇒ 只能停在无法归因，不能写成"丢在发射之前"。

	working 里的 last_x_sent 是整会话最后发射的那一份，可能出自更晚的一轮；拿它判
	某一枪"没送到"，把更晚几轮的内容当成这一枪的输入。命中是自证的，落空不是。
	"""
	constraint = "部署前先跑迁移"
	_transcript("s1", [{"id": "m1", "role": "user", "ts": 0.5, "content": constraint}])
	_working("s1", {"session_id": "s1", "last_x_sent": json.dumps([{"content": "无关内容"}], ensure_ascii=False)})
	run = _run(tmp_path)
	# 留存投影的创建时刻晚于本轮最后一条记录：它不是这一枪发出去的那一份
	run.projections = [{"projection_id": "p9", "created_at": 9_000.0}]
	doc = trace_fact(run, constraint)
	assert _states(doc)["emitted"] == ABSENT
	assert doc["verdict"] == "unknown"
	assert "无从核对它属不属于这个范围" in doc["statement"]
	# 两头都不许替引擎或事实认账：既不定位到哪一级丢的，也不排除"这份本来就早于它"
	assert "既不能定位" in doc["statement"] and "也不能排除" in doc["statement"]


def test_unbound_hit_is_still_kept_through(tmp_path) -> None:
	"""门只关落空那一支：命中带的是投影正文本身，归属核不上也改不了事实。

	#62 交过学费 —— 一把闸把 302 条自证命中一起关掉，覆盖率退步比准确率修得更多。
	"""
	constraint = "部署前先跑迁移"
	_transcript("s1", [{"id": "m1", "role": "user", "ts": 0.5, "content": constraint}])
	_working("s1", {"session_id": "s1", "last_x_sent": json.dumps([{"content": constraint}], ensure_ascii=False)})
	run = _run(tmp_path)
	run.projections = [{"projection_id": "p9", "created_at": 9_000.0}]
	doc = trace_fact(run, constraint)
	assert _states(doc)["emitted"] == FOUND
	assert doc["verdict"] == "kept_through"


def test_gate_opens_on_the_projection_manifest_producers_actually_write(tmp_path) -> None:
	"""归属判据吃的 created_at 必须是生产者真写的那个字段，不能是夹具造的。

	ProjectionManifest.created_at（engine/projection_manifest.py）经
	snap.last_projection_manifest 落进 working.json，collect 再灌进 run.projections。
	这条走完整 collect 路径：字段改名时它会先红，而不是让门悄悄关上。
	"""
	constraint = "部署前先跑迁移"
	_transcript("s1", [{"id": "m1", "role": "user", "ts": 0.5, "content": constraint}])
	_working(
		"s1",
		{
			"session_id": "s1",
			"last_x_sent": json.dumps([{"content": "无关内容"}], ensure_ascii=False),
			"last_projection_manifest": {"projection_id": "p1", "created_at": 1.0, "messages_kept": 1},
		},
	)
	doc = trace_fact(_run(tmp_path), constraint)
	assert _states(doc)["emitted"] == ABSENT
	assert doc["verdict"] == "lost_before:emitted"


def test_empty_needle_is_rejected(tmp_path) -> None:
	import pytest

	with pytest.raises(ValueError):
		trace_fact(_run(tmp_path), "   ")


def test_hit_survives_reflow_and_json_escaping() -> None:
	"""用户消息自带换行时，投影里的原文不得判成"没送到"。

	真实数据实测（150 轮）：5 轮的约束就在发射投影里，只因排版差异被判 absent，
	其中 3 轮已据此产出 context_dropped_constraint（已确认 + 定责引擎）。
	"""
	from diagnostics.loss_chain import _hit

	needle = "改完必须跑 pytest" + chr(10) + "然后才能说完成"
	# 投影里换行被排版成空格
	assert _hit(needle, "x 改完必须跑 pytest 然后才能说完成 y")
	# 投影里留着 JSON 的字面 \n（反斜杠 + n），出现在短语中间与结尾各一例
	assert _hit(needle, "x 改完必须跑\\npytest 然后才能说完成 y")
	assert _hit(needle, "x 改完必须跑 pytest\\n然后才能说完成 y")
	# 中文被 ensure_ascii 转成 \\uXXXX 时也要能对上（既有那条能力不得丢）
	escaped = "改完必须跑 pytest\n然后才能说完成".encode("unicode_escape").decode("ascii")
	assert _hit(needle, "prefix " + escaped + " suffix")


def test_hit_does_not_become_whitespace_blind() -> None:
	"""放宽只能折叠空白，不能删空白：否则"没送到"会被反过来掩盖成"送到了"。"""
	from diagnostics.loss_chain import _hit

	assert not _hit("x y", "xy z")
	assert not _hit("ab", "a b")
	assert not _hit("必须跑测试", "必须 跑 测试 别的")
