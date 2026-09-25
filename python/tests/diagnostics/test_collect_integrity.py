"""采集层的诚实性回归：真实数据普查里确认的七个缺陷。

每一条都对应一份真实产品数据上跑出来的错账：

1. ``_merge`` 早于账本采集 ⇒ per-attempt 用量恒空，界面逐次显示费用未知，
   而用量汇总同时声称都有账。
2. ``str.splitlines()`` 连 U+0085 / U+2028 也算换行 ⇒ 真实 transcript 里
   一行被劈成两半，行少一行、之后所有证据指针 L<n> 集体错位。
3. 文件不存在被返回成「截断」⇒ 本机没有 wire_drops 账本时，每个运行详情
   都说覆盖不全；没有审计文件时说窗口太小，而根本没有东西可截断。
4. 解不出的行悄悄丢弃 ⇒ 半行（进程被杀的典型尾行）消失后载荷仍写
   ``state=full / complete=true``，「没发现异常」建立在扔掉证据之上。
5. transcript 行列表虚报 ⇒ 上限裁到 400 行之后仍写 rows=463。
6. usage 窗口对自己的边界一言不发 ⇒ ``complete=false`` 却没有 ``note``。
7. 会话级的"没记账"被规则层当成轮次性质重复报出 ⇒ 折叠账本对本会话零行
   （行内不带轮次身份）现在只在缺项清单里说一次。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from diagnostics import collect as collect_module
from diagnostics.collect import (
	_TRANSCRIPT_ROW_CAP,
	_scan_jsonl_tail,
	_tail_jsonl,
	collect_run,
	list_runs,
)
from diagnostics.identity import ABSENT, COMPLETE, PARTIAL

# ---------- 夹具形状：与真实审计 / transcript / 用量账本同形 ----------

_SESSION = "s1"
_TURN = "t1"


def _write_jsonl(path: Path, rows: list[Any]) -> Path:
	"""按真实落盘方式写 JSONL：``ensure_ascii=False``，正文里的 C1 控制符保持原始字节。"""
	path.parent.mkdir(parents=True, exist_ok=True)
	payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
	path.write_bytes(payload.encode("utf-8"))
	return path


def _append_raw(path: Path, text: str) -> None:
	with path.open("a", encoding="utf-8") as handle:
		handle.write(text)


def _model_rows(request_id: str, attempt: int, *, ts: float = 1.0, session_id: str = _SESSION) -> list[dict[str, Any]]:
	return [
		{
			"ts": ts,
			"kind": "model.started",
			"session_id": session_id,
			"turn_id": _TURN,
			"model_request_id": request_id,
			"request_id": request_id,
			"attempt": attempt,
			"provider": "deepseek",
			"model": "deepseek-v4-flash",
			"projection_id": "p1",
		},
		{
			"ts": ts + 0.4,
			"kind": "model.finished",
			"session_id": session_id,
			"turn_id": _TURN,
			"model_request_id": request_id,
			"request_id": request_id,
			"attempt": attempt,
			"provider": "deepseek",
			"model": "deepseek-v4-flash",
			"status": "ok",
			"duration_ms": 400,
		},
	]


def _tool_rows(tool_use_id: str, request_id: str, *, ts: float = 2.0) -> list[dict[str, Any]]:
	return [
		{
			"ts": ts,
			"kind": "tool.started",
			"session_id": _SESSION,
			"turn_id": _TURN,
			"request_id": tool_use_id,
			"tool_name": "Bash",
			"model_request_id": request_id,
		},
		{
			"ts": ts + 0.1,
			"kind": "tool.finished",
			"session_id": _SESSION,
			"turn_id": _TURN,
			"request_id": tool_use_id,
			"tool_name": "Bash",
			"is_error": False,
			"model_request_id": request_id,
		},
	]


def _usage_row(request_id: str, attempt: int, cost: float | None, *, session_id: str = _SESSION) -> dict[str, Any]:
	row: dict[str, Any] = {
		"ts": 1790089468.5,
		"day": "2026-09-25",
		"provider": "deepseek",
		"vendor": "deepseek",
		"model": "deepseek-v4-flash",
		"session_id": session_id,
		"key_fp": "k522a",
		"prompt_tokens": 11689,
		"completion_tokens": 328,
		"cache_hit": 8960,
		"cache_miss": 2729,
		"output": 328,
		"tokens": 12017,
		"cost_source": "estimate",
		"request_id": request_id,
		"attempt": attempt,
		"kind": "turn",
	}
	if cost is not None:
		row["cost_cny"] = cost
	return row


def _transcript_row(index: int, **extra: Any) -> dict[str, Any]:
	row: dict[str, Any] = {
		"id": f"m{index}",
		"role": "assistant" if index % 2 else "user",
		"ts": f"{index}.0",
		"content": f"正文 {index}",
	}
	row.update(extra)
	return row


def _ledger_path() -> Path:
	from usage.ledger import events_path

	return events_path()


def _wire_drops_path() -> Path:
	from usage.ledger import wire_drops_path

	return wire_drops_path()


def _fold_events_path() -> Path:
	from usage.ledger import fold_events_path

	return fold_events_path()


def _transcript_file(session_id: str = _SESSION) -> Path:
	from session.persistence import transcript_path

	return transcript_path(session_id)


# ---------- 1：per-attempt 用量必须在读到账本之后才挂 ----------


def test_attempt_usage_join_sees_the_ledger(write_audit) -> None:
	"""挂载早于采集时，每次尝试的用量都是空表：真实回合 159 次尝试全部丢账。"""
	path = write_audit(_model_rows("r1", 1) + _model_rows("r1", 2) + _model_rows("r2", 1, ts=5.0))
	_write_jsonl(_ledger_path(), [_usage_row("r1", 1, 0.25), _usage_row("r1", 2, 0.3), _usage_row("r2", 1, 0.4)])

	run = collect_run(_SESSION, _TURN, audit_path=path)

	by_request = {m.model_request_id: m.usage_by_attempt for m in run.model_requests}
	assert sorted(by_request) == ["r1", "r2"]
	assert sorted(by_request["r1"]) == ["r1#1", "r1#2"], "两次重试都要挂上账，不得互相覆盖"
	assert by_request["r1"]["r1#1"]["cost_cny"] == 0.25
	assert by_request["r2"]["r2#1"]["cost_cny"] == 0.4


def test_attempt_usage_matches_every_ledger_row(write_audit) -> None:
	"""有账的尝试键与挂载结果必须一一对应：两边说的是同一件事。"""
	path = write_audit(_model_rows("r1", 1) + _tool_rows("c1", "r1"))
	_write_jsonl(_ledger_path(), [_usage_row("r1", 1, 0.25), _usage_row("r9", 1, 0.7)])

	run = collect_run(_SESSION, _TURN, audit_path=path)

	carried_keys = {r["attempt_key"] for r in run.usage_rows}
	attached = {key for m in run.model_requests for key in m.usage_by_attempt}
	assert attached == carried_keys & {key for m in run.model_requests for key in m.attempt_ids()}
	assert "r9#1" in carried_keys, "账本里属于别次请求的行仍留在账本视图，不冒充挂载"
	doc = run.to_dict()
	payload = {m["model_request_id"]: m["usage_by_attempt"] for m in doc["model_requests"]}
	assert list(payload["r1"]) == ["r1#1"]


def test_missing_ledger_row_stays_absent_not_zero(write_audit) -> None:
	"""没有账的尝试不得挂载，也不得被写成 0 元。"""
	path = write_audit(_model_rows("r1", 1))
	_write_jsonl(_ledger_path(), [_usage_row("r9", 1, 0.7, session_id="other")])

	run = collect_run(_SESSION, _TURN, audit_path=path)

	assert run.model_requests[0].usage_by_attempt == {}


# ---------- 2：切行只认换行符 ----------


def test_tail_reader_splits_on_newline_only(tmp_path) -> None:
	"""正文里合法出现的 U+0085 / U+2028 不是换行：splitlines 会吃掉一行并错位行号。"""
	path = tmp_path / "transcript.jsonl"
	rows = [_transcript_row(i) for i in range(8)]
	rows[1]["content"] = "ELF 段转储前 \u0085 转储后"
	rows[4]["content"] = "行分隔符 \u2028 之后"
	_write_jsonl(path, rows)

	assert b"\xc2\x85" in path.read_bytes(), "夹具必须落成原始字节，才与真实 transcript 同形"

	entries, _read, truncated = _tail_jsonl(path, 1024 * 1024)
	assert truncated is False
	assert [no for no, _row in entries] == [1, 2, 3, 4, 5, 6, 7, 8], "行号必须等于物理行号"
	assert entries[1][1]["id"] == "m1"
	assert "\u0085" in entries[1][1]["content"]
	assert entries[4][1]["id"] == "m4"
	assert "\u2028" in entries[4][1]["content"]

	scan = _scan_jsonl_tail(path, 1024 * 1024)
	physical = len([chunk for chunk in path.read_bytes().split(b"\n") if chunk.strip()])
	assert scan.rows_scanned == physical == 8
	assert scan.rows_unparsable == 0


def test_evidence_line_numbers_survive_a_raw_nel_row(write_audit) -> None:
	"""错位一旦发生了整条链：审计行的 L<n> 必须仍指向物理行。"""
	rows = _model_rows("r1", 1) + _model_rows("r2", 1, ts=9.0)
	# 在第 1 与第 2 行之间塞进一行正文含原始 U+0085 的其他会话记录。
	injected = {"ts": 3.0, "kind": "notice.channel", "session_id": "other", "text": "x \u0085 y"}
	path = write_audit([rows[0], injected] + rows[1:])

	run = collect_run(_SESSION, _TURN, audit_path=path)

	assert [event.line_no for event in run.events] == [1, 3, 4, 5]
	assert run.window("audit").rows_scanned == 5


def test_transcript_evidence_pointers_stay_physical(write_audit) -> None:
	"""transcript 的行号是回读入口：NEL 之后错位等于把读者指向另一条消息。"""
	rows = [_transcript_row(i) for i in range(6)]
	rows[1]["content"] = "ELF 段转储 \u0085 尾部"
	_write_jsonl(_transcript_file(), rows)
	path = write_audit(_model_rows("r1", 1) + _tool_rows("c1", "r1"))

	run = collect_run(_SESSION, _TURN, audit_path=path)

	carried = run.transcript_rows
	assert [row["line_no"] for row in carried] == [1, 2, 3, 4, 5, 6]
	assert [row["id"] for row in carried] == ["m0", "m1", "m2", "m3", "m4", "m5"]
	assert carried[1]["body_state"] == "inline"
	window = run.window("transcript")
	assert window is not None and window.rows_scanned == 6 and window.rows_unparsable == 0


# ---------- 3：缺失 / 截断 / 完整是三件事 ----------


def test_missing_file_is_not_truncation(tmp_path) -> None:
	missing = tmp_path / "nope.jsonl"
	entries, read_bytes, truncated = _tail_jsonl(missing, 4096)
	assert entries == [] and read_bytes == 0
	assert truncated is False, "没有内容可截断"

	scan = _scan_jsonl_tail(missing, 4096)
	assert scan.present is False and scan.truncated is False


def test_absent_wire_drops_is_reported_as_absent(write_audit) -> None:
	"""本机没有 wire_drops 账本时，运行详情不得说覆盖不全。"""
	assert _wire_drops_path().is_file() is False
	path = write_audit(_model_rows("r1", 1) + _tool_rows("c1", "r1"))

	run = collect_run(_SESSION, _TURN, audit_path=path)

	window = run.window("wire_drops")
	assert window is not None
	assert window.present is False and window.truncated is False
	assert "不存在" in window.note
	assert "未覆盖" not in window.note, "缺失不得写成尾窗截断"
	assert run.coverage()["wire_drops"]["state"] == ABSENT
	assert any(g.boundary == "tool_permission" and g.reason == "source_absent" for g in run.gaps)


def test_absent_audit_file_is_not_a_small_window(tmp_path) -> None:
	run = collect_run(_SESSION, _TURN, audit_path=tmp_path / "no-audit.jsonl")

	window = run.window("audit")
	assert window is not None
	assert window.present is False and window.truncated is False and window.complete is False
	assert "不存在" in window.note and "未覆盖" not in window.note
	assert run.coverage()["audit"]["state"] == ABSENT
	assert any(g.reason == "source_absent" for g in run.gaps)


def test_truncation_is_not_reported_as_absence(write_audit) -> None:
	rows = _model_rows("r1", 1) + [{"ts": 5.0, "kind": "model.started", "session_id": "other", "turn_id": "ox", "model_request_id": "rx"}] * 40
	path = write_audit(rows)

	run = collect_run(_SESSION, _TURN, audit_path=path, max_audit_bytes=400)

	window = run.window("audit")
	assert window.present is True and window.truncated is True
	assert "尾窗截断" in window.note and "行未覆盖" in window.note
	assert "不存在" not in window.note
	assert window.rows_outside_window > 0
	assert run.coverage()["audit"]["state"] == PARTIAL
	assert any(g.reason == "out_of_window" for g in run.gaps)


def test_absent_usage_ledger_is_absent_not_a_window(write_audit) -> None:
	path = write_audit(_model_rows("r1", 1))

	run = collect_run(_SESSION, _TURN, audit_path=path)

	window = run.window("usage")
	assert window is not None
	assert window.present is False and window.truncated is False
	assert "不存在" in window.note
	assert run.coverage()["usage"]["state"] == ABSENT
	assert any(g.boundary == "model_request" and g.reason == "source_absent" for g in run.gaps)


def test_full_scan_claims_full_and_says_nothing_about_windows(write_audit) -> None:
	path = write_audit(_model_rows("r1", 1))
	_write_jsonl(_ledger_path(), [_usage_row("r1", 1, 0.25)])
	_write_jsonl(_fold_events_path(), [{"session_id": _SESSION, "arm": "v1", "accepted": True}])

	run = collect_run(_SESSION, _TURN, audit_path=path)

	for source in ("audit", "usage", "fold_events"):
		window = run.window(source)
		assert window is not None, source
		assert window.present is True, source
		assert window.complete is True and window.truncated is False, source
		assert window.note == "", source
		assert run.coverage()[source]["state"] == COMPLETE, source
	# 同一份数据里没被创建的两个来源必须说「不存在」，而不是说窗口太小。
	for source in ("transcript", "wire_drops"):
		window = run.window(source)
		assert window is not None, source
		assert window.present is False and window.truncated is False, source
		assert "不存在" in window.note and "未覆盖" not in window.note, source
		assert run.coverage()[source]["state"] == ABSENT, source


# ---------- 4：丢过的行必须留下账 ----------


def test_half_written_tail_line_cannot_be_reported_as_full(write_audit) -> None:
	"""进程被杀留下的半行是最常见的丢行原因：不能扔完还写 complete=true。"""
	rows = [
		{"ts": float(i), "kind": "model.started", "session_id": _SESSION, "turn_id": _TURN, "model_request_id": f"r{i}", "attempt": 1}
		for i in range(30)
	]
	path = write_audit(rows)
	_append_raw(path, '{"ts": 99.0, "kind": "model.star')

	scan = _scan_jsonl_tail(path, 8 * 1024 * 1024)
	assert scan.rows_scanned == 31 and scan.rows_unparsable == 1
	assert len(scan.rows) == 30

	run = collect_run(_SESSION, _TURN, audit_path=path)

	window = run.window("audit")
	assert window.rows_unparsable == 1 and window.rows_scanned == 31
	assert window.complete is False
	coverage = run.coverage()["audit"]
	assert coverage["state"] != COMPLETE and coverage["rows_unparsable"] == 1
	assert "1 行" in window.note


def test_json_that_is_not_an_object_is_counted(tmp_path) -> None:
	path = tmp_path / "audit.jsonl"
	path.write_text('{"session_id": "s1"}\n[1, 2, 3]\n"a string"\n7\n\n', encoding="utf-8")

	scan = _scan_jsonl_tail(path, 8192)

	assert scan.rows_scanned == 4
	assert scan.rows_unparsable == 3
	assert [no for no, _row in scan.rows] == [1]


def test_rows_without_session_id_are_machine_readable(write_audit) -> None:
	"""缺 session_id 的行原先只活在一句中文说明里：计数必须进字段。"""
	path = write_audit(
		[
			{"ts": 1.0, "kind": "llm.failure", "code": "conn", "attempt": 1, "status": 500},
			*_model_rows("r1", 1),
		]
	)

	run = collect_run(_SESSION, _TURN, audit_path=path)

	window = run.window("audit")
	assert window.rows_unattributed == 1
	assert window.rows_matched == 2
	assert window.complete is False
	assert run.coverage()["audit"]["rows_unattributed"] == 1
	assert "1 行缺 session_id" in window.note


def test_other_sessions_are_counted_without_being_called_dropped(write_audit) -> None:
	"""归到别的会话是正常过滤，不是丢证据：计数要有，状态不得因此降级。"""
	path = write_audit([{"ts": 1.0, "kind": "model.started", "session_id": "other", "turn_id": "o1", "model_request_id": "rx"}] + _model_rows("r1", 1))

	run = collect_run(_SESSION, _TURN, audit_path=path)

	window = run.window("audit")
	assert window.rows_other_session == 1
	assert window.rows_dropped == 0
	assert window.complete is True


def test_run_list_does_not_claim_completeness_over_dropped_rows(write_audit) -> None:
	path = write_audit(_model_rows("r1", 1))
	_append_raw(path, '{"ts": 99.0, "kind": "model.fin')

	runs = list_runs(_SESSION, audit_path=path)

	assert runs
	item = runs[0]
	assert item["coverage_note"]
	assert item["coverage"]["present"] is True
	assert item["coverage"]["truncated"] is False
	assert item["coverage"]["rows_unparsable"] == 1
	assert item["coverage"]["complete"] is False


def test_run_list_says_absent_when_there_is_no_audit_file(tmp_path) -> None:
	assert list_runs(_SESSION, audit_path=tmp_path / "nope.jsonl") == []


# ---------- 5：transcript 行数要说载荷实际带了多少 ----------


def test_transcript_row_count_matches_the_payload(write_audit, monkeypatch) -> None:
	"""上限裁掉的行不得再被 rows_matched 声称在内。"""
	monkeypatch.setattr(collect_module, "_TRANSCRIPT_ROW_CAP", 4)
	_write_jsonl(_transcript_file(), [_transcript_row(i) for i in range(10)])
	path = write_audit(_model_rows("r1", 1) + _tool_rows("c1", "r1"))

	run = collect_run(_SESSION, _TURN, audit_path=path)

	window = run.window("transcript")
	assert window is not None
	assert window.rows_scanned == 10
	assert window.rows_matched == len(run.transcript_rows) == 4
	assert window.rows_capped == 6
	assert window.complete is False
	coverage = run.coverage()["transcript"]
	assert coverage["rows"] == len(run.transcript_rows)
	assert coverage["state"] == PARTIAL and coverage["rows_capped"] == 6
	assert len(run.to_dict()["transcript"]) == 4
	assert [row["id"] for row in run.transcript_rows] == ["m6", "m7", "m8", "m9"], "保留的必须是最近的行"


def test_capped_transcript_rows_stop_linking_results(write_audit, monkeypatch) -> None:
	"""被裁掉的行不能继续充当「已锚定」的证据：缺的就是缺。"""
	monkeypatch.setattr(collect_module, "_TRANSCRIPT_ROW_CAP", 2)
	_write_jsonl(
		_transcript_file(),
		[_transcript_row(0, role="tool", tool_call_id="c1", name="Bash", content="结果正文")]
		+ [_transcript_row(i) for i in range(1, 6)],
	)
	path = write_audit(_model_rows("r1", 1) + _tool_rows("c1", "r1"))

	run = collect_run(_SESSION, _TURN, audit_path=path)

	window = run.window("transcript")
	assert window is not None and window.rows_capped == 4
	assert run.tool_calls[0].result_message_id == ""
	assert any(
		g.boundary == "file_verifier" and g.reason == "field_missing" and "1 个工具调用" in g.detail for g in run.gaps
	), "锚不上的工具调用必须进缺项，而不是被裁掉的行掩盖"


def test_default_transcript_cap_is_a_real_window_budget() -> None:
	"""上限本身是边界预算，改它等于改载荷体积：留一条断言防止无意改动。"""
	assert _TRANSCRIPT_ROW_CAP == 400


# ---------- 6：usage 窗口要像 audit 一样说出自己的边界 ----------


def test_usage_window_states_its_truncation(write_audit, monkeypatch) -> None:
	monkeypatch.setattr(collect_module, "_AUDIT_TAIL_BYTES", 512)
	_write_jsonl(_ledger_path(), [_usage_row(f"r{i}", 1, 0.01, session_id="other") for i in range(60)])
	path = write_audit(_model_rows("r1", 1))

	run = collect_run(_SESSION, _TURN, audit_path=path)

	window = run.window("usage")
	assert window is not None
	assert window.truncated is True and window.complete is False
	assert "尾窗截断" in window.note and "行未覆盖" in window.note
	assert window.rows_outside_window > 0
	assert window.rows_scanned < 60, "窗口确实读不满账本"
	assert any(g.boundary == "model_request" and g.reason == "out_of_window" for g in run.gaps)
	assert run.coverage()["usage"]["state"] == PARTIAL


def test_fold_window_states_its_truncation(write_audit, monkeypatch) -> None:
	monkeypatch.setattr(collect_module, "_AUDIT_TAIL_BYTES", 512)
	from usage.ledger import fold_events_path

	_write_jsonl(fold_events_path(), [{"session_id": "other", "arm": "v1", "i": i} for i in range(60)])
	path = write_audit(_model_rows("r1", 1))

	run = collect_run(_SESSION, _TURN, audit_path=path)

	window = run.window("fold_events")
	assert window is not None and window.truncated is True and window.complete is False
	assert "尾窗截断" in window.note


def test_wire_drops_window_states_its_truncation(write_audit, monkeypatch) -> None:
	monkeypatch.setattr(collect_module, "_AUDIT_TAIL_BYTES", 512)
	_write_jsonl(_wire_drops_path(), [{"ts": float(i), "ids": [f"call_{i}"], "target": "wire"} for i in range(60)])
	path = write_audit(_model_rows("r1", 1) + _tool_rows("call_59", "r1"))

	run = collect_run(_SESSION, _TURN, audit_path=path)

	window = run.window("wire_drops")
	assert window is not None and window.truncated is True and window.complete is False
	assert "尾窗截断" in window.note
	assert run.coverage()["wire_drops"]["state"] == PARTIAL


# ---------- 合起来：只要丢过行，就没有来源可以声称完整 ----------


def test_no_window_claims_full_while_dropping_rows(write_audit) -> None:
	path = write_audit(_model_rows("r1", 1))
	_append_raw(path, '{"ts": 99.0, "kind": "notice')
	_append_raw(path, "\n[not json\n")
	_write_jsonl(_ledger_path(), [_usage_row("r1", 1, 0.25), "账本里的一行垃圾"])

	run = collect_run(_SESSION, _TURN, audit_path=path, max_audit_bytes=1024)

	# 只有真正扫过文件的来源才有「缺失 / 截断」这套措辞；进程内快照另说。
	file_sources = {"audit", "usage", "fold_events", "transcript", "wire_drops"}
	for window in run.windows:
		if window.rows_dropped:
			assert window.complete is False, window.source
			assert run.coverage()[window.source]["state"] != COMPLETE, window.source
		if window.truncated:
			assert window.note, window.source
			assert window.present and window.complete is False, window.source
		if window.source in file_sources and not window.present:
			assert "不存在" in window.note and "未覆盖" not in window.note, window.source
			assert run.coverage()[window.source]["state"] == ABSENT, window.source


def test_fold_ledger_with_no_rows_for_this_session_says_so_once(write_audit) -> None:
	"""折叠账本可读、窗口完整，但本会话零行：这一级没有可核对的记录。
	必须说，但要说在采集缺项里 —— 折叠事件按会话写、行内不带轮次身份，
	这条对本会话的每一轮都同形（真实数据曾把它写成 27/40 轮的"本轮未定"）。"""
	from usage.ledger import fold_events_path, record_fold_event

	record_fold_event(session_id="another-session", arm="c2")
	assert fold_events_path().is_file()

	run = collect_run(_SESSION, _TURN, audit_path=write_audit(_model_rows("r1", 1)))

	gaps = [g for g in run.gaps if g.boundary == "wsc_fold" and g.reason == "no_records"]
	assert gaps, "账本没有本会话的记录行，要留在缺项清单里"
	assert "没有可核对的记录" in gaps[0].detail
	window = run.window("fold_events")
	assert window.present and window.complete and window.rows_matched == 0


def test_fold_ledger_rows_for_this_session_do_not_trigger_the_gap(write_audit) -> None:
	"""反面对照：账本里有本会话的行时不得再发这条缺项，否则它又是一条恒真措辞。"""
	from usage.ledger import fold_events_path, record_fold_event

	record_fold_event(session_id=_SESSION, arm="c2")
	assert fold_events_path().is_file()

	run = collect_run(_SESSION, _TURN, audit_path=write_audit(_model_rows("r1", 1)))

	assert [g for g in run.gaps if g.reason == "no_records"] == []
	assert run.window("fold_events").rows_matched == 1
