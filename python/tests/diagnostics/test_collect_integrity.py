"""采集层的诚实性回归：真实数据普查里确认的十个缺陷。

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
8. 尾窗扫不到就把本轮判成"本轮无记录" ⇒ 分层普查 57 个真实轮次里 11 轮（19%）
   的行其实完整地在审计文件里，只是排在 4 MiB 之外。现在先在 miss 路径上扩窗
   重读一次（本机整份 11.3 MiB 多花 0.1s），扩完仍找不到才允许下这条结论，
   且两种结果各留一条缺项说明口径。
9. picker 与 detail 口径不一致 ⇒ ``list_runs`` 只看 8 MiB 尾窗，真实文件里有一个会话
   整段排在窗外（列表 0 条，而扩窗后的 ``collect_run`` 能完整诊断）。现在同一个 miss
   路径也扩窗重读，并把"读完整份还是没有"与"尾窗没盖到"分成两句话。
10. 账本的「没有这一行」说的是整份文件，而扫描只读到 61% ⇒ 缺账断言的范围不成立。
    现在账本截断且本轮确有要归账的调用时读完整份再判（本机 6.28 MB：全读 0.09s vs 尾窗 0.058s）。
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
	# 归属阶段要看护栏站在哪一道边界上：wire_drops 记的是"发射前把孤儿 tool 结果裁掉"，
	# 属适配器出口（rules.wire_gap 的结论也钉在 adapter），不能挂在「工具与权限」下，
	# 否则读的人会去权限链找一件发生在请求体组装处的事。
	gap = next(g for g in run.gaps if g.reason == "source_absent" and g.boundary == "adapter")
	assert "wire_drops" in gap.detail
	assert "openai_compat" in gap.detail, "措辞要点明这个账本只覆盖一条链路"


def test_absent_audit_file_is_not_a_small_window(tmp_path) -> None:
	run = collect_run(_SESSION, _TURN, audit_path=tmp_path / "no-audit.jsonl")

	window = run.window("audit")
	assert window is not None
	assert window.present is False and window.truncated is False and window.complete is False
	assert "不存在" in window.note and "未覆盖" not in window.note
	assert run.coverage()["audit"]["state"] == ABSENT
	assert any(g.reason == "source_absent" for g in run.gaps)


def test_truncation_is_not_reported_as_absence(write_audit) -> None:
	other = [{"ts": 5.0, "kind": "model.started", "session_id": "other", "turn_id": "ox", "model_request_id": "rx"}] * 40
	# 本轮的行留在尾窗内：尾窗外的行才是"截断"，本轮扫不到会走扩窗分支
	# （见 test_turn_outside_the_tail_window_is_recovered_by_widening），那是另一件事。
	rows = other + _model_rows("r1", 1)
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
	# 措辞要说清两种来源：这一类既可能是旧审计格式，也可能是评测/模拟器直接写入
	# （真实尾窗里 session_id 为空的行绝大多数是后者），一律写成"旧格式"是假归因。
	assert "session_id 为空" in window.note
	assert "旧审计格式" in window.note and "模拟器" in window.note


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
	"""被裁掉的行不能继续充当「已锚定」的证据 —— 但也不能反过来说结果不存在。"""
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
	gaps = {(g.boundary, g.reason): g.detail for g in run.gaps}
	assert any("1 个已结束的调用" in d for (b, _r), d in gaps.items() if b == "file_verifier"), (
		"锚不上的工具调用必须进缺项，而不是被裁掉的行掩盖"
	)
	# 载荷残缺时强度必须降一档：真实数据里这类计数最高 41 个，全部落在保留窗之前，
	# 说成「无对应结果行」就是把读不出写成没有。
	assert not any(r == "field_missing" and "无对应结果行" in d for (_b, r), d in gaps.items()), gaps
	assert ("file_verifier", "out_of_window") in gaps
	assert "配对读不出" in gaps[("file_verifier", "out_of_window")]


def test_complete_transcript_still_says_a_result_row_is_missing(write_audit) -> None:
	"""窗口完整时才有资格说「无对应结果行」：这一档是文件里真没有那一行。"""
	_write_jsonl(
		_transcript_file(),
		[_transcript_row(0, role="user"), _transcript_row(1, role="assistant")],
	)
	path = write_audit(_model_rows("r1", 1) + _tool_rows("c1", "r1"))

	run = collect_run(_SESSION, _TURN, audit_path=path)

	window = run.window("transcript")
	assert window is not None and window.complete is True and window.rows_capped == 0
	assert any(
		g.boundary == "file_verifier" and g.reason == "field_missing" and "无对应结果行" in g.detail for g in run.gaps
	)


def test_open_tool_call_is_not_counted_as_a_missing_result(write_audit) -> None:
	"""只有开始记录的调用，本就不可能有结果行：把它算进"缺结果"是把一件事报成两件。"""
	_write_jsonl(_transcript_file(), [_transcript_row(0, role="user")])
	path = write_audit(_model_rows("r1", 1) + _tool_rows("c1", "r1")[:-1])  # 丢掉 tool.finished

	run = collect_run(_SESSION, _TURN, audit_path=path)

	window = run.window("transcript")
	assert window is not None and window.complete is True
	assert not any(
		g.boundary == "file_verifier" and g.reason == "field_missing" for g in run.gaps
	), "未结束的调用不得声称缺结果行"
	assert "只有开始记录" in window.note


def test_mixed_open_and_finished_calls_count_separately(write_audit) -> None:
	"""两种情形同时出现时，两个数必须分开说，不能合并成一句"缺结果"。"""
	_write_jsonl(_transcript_file(), [_transcript_row(0, role="user")])
	rows = _model_rows("r1", 1) + _tool_rows("c1", "r1") + _tool_rows("c2", "r1", ts=3.0)
	path = write_audit(rows[: -1])  # 丢掉 c2 的 tool.finished（最后一行）

	run = collect_run(_SESSION, _TURN, audit_path=path)

	claim = [
		g.detail
		for g in run.gaps
		if g.boundary == "file_verifier" and g.reason == "field_missing"
	]
	assert len(claim) == 1, run.gaps
	assert "1 个已结束的调用在 transcript 无对应结果行" in claim[0]
	assert "另有 1 个调用只有开始记录" in claim[0]


def test_default_transcript_cap_is_a_real_window_budget() -> None:
	"""上限本身是边界预算，改它等于改载荷体积：留一条断言防止无意改动。"""
	assert _TRANSCRIPT_ROW_CAP == 400


# ---------- 6：usage 窗口要像 audit 一样说出自己的边界 ----------


def test_usage_window_states_its_truncation(write_audit, monkeypatch) -> None:
	"""截断仍要说出来 —— 即使扩窗之后仍然没读完，措辞得跟着生效口径走。

	尾窗截断现在会触发一次扩窗重读（见 test_usage_row_outside_the_ledger_window…）；
	这里把扩窗上限也压小，钉的是"读不完就继续报 partial / out_of_window，
	且说的字节数是真正用过的那个"。
	"""
	monkeypatch.setattr(collect_module, "_AUDIT_TAIL_BYTES", 512)
	monkeypatch.setattr(collect_module, "_AUDIT_WIDEN_BYTES", 800)
	_write_jsonl(_ledger_path(), [_usage_row(f"r{i}", 1, 0.01, session_id="other") for i in range(60)])
	path = write_audit(_model_rows("r1", 1))

	run = collect_run(_SESSION, _TURN, audit_path=path)

	window = run.window("usage")
	assert window is not None
	assert window.truncated is True and window.complete is False
	assert "尾窗截断" in window.note and "行未覆盖" in window.note
	assert window.rows_outside_window > 0
	assert window.rows_scanned < 60, "窗口确实读不满账本"
	gap = [g for g in run.gaps if g.boundary == "model_request" and g.reason == "out_of_window"]
	assert gap, "截断了就必须留缺项"
	assert "800 字节" in gap[0].detail, "口径要说真正用过的那个上限，不是默认尾窗"
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

	# 断的是"这一条"（折叠账本对本会话的 no_records）；no_records 这个原因码可以
	# 出现在别的边界上（working 快照没有 manifest 时也是"对本会话没有记录行"），
	# 所以过滤必须带上边界，否则别处的合法缺项会被这条测试误吞。
	assert [
		g for g in run.gaps if g.boundary == "wsc_fold" and g.reason == "no_records"
	] == []
	assert run.window("fold_events").rows_matched == 1


# ---------- 8. 尾窗之外的轮次：先扩窗重读，再谈"本轮无记录" ----------


def _filler_rows(count: int) -> list[dict[str, Any]]:
	"""别的会话的行：把本轮的行推出尾窗，模拟多个会话共用一份审计文件。"""
	return [
		{
			"ts": 500.0 + i,
			"kind": "tool.finished",
			"session_id": "other-session",
			"turn_id": f"other-turn-{i}",
			"request_id": f"oc{i}",
			"tool_name": "Read",
			"pad": "x" * 120,
		}
		for i in range(count)
	]


def _harness_rows(count: int, turn_id: str) -> list[dict[str, Any]]:
	"""评测/模拟器直写的行：没有会话身份，轮次号却和在跑的会话撞车。"""
	return [
		{
			"ts": 900.0 + i,
			"kind": "model.finished",
			"session_id": "",
			"turn_id": turn_id,
			"model_request_id": f"h{i}",
			"provider": "",
			"model": "",
			"pad": "y" * 120,
		}
		for i in range(count)
	]


def test_turn_outside_the_tail_window_is_recovered_by_widening(write_audit) -> None:
	"""真实普查里 19% 的轮次属于这一类：行都在文件里，只是排在尾窗之外。"""
	from diagnostics.rules import evaluate_run

	path = write_audit(_model_rows("r1", 1) + _filler_rows(400))
	tail = _scan_jsonl_tail(path, 2048)
	assert tail.truncated, "夹具没造出截断的尾窗"
	assert all(str(r.get("turn_id") or "") != _TURN for _, r in tail.rows), "夹具没把本轮推出尾窗"

	run = collect_run(_SESSION, _TURN, audit_path=path, max_audit_bytes=2048)

	assert [e for e in run.events if e.turn_id == _TURN], "扩窗后必须把本轮的行读回来"
	gaps = [g for g in run.gaps if g.reason == "recovered_outside_window"]
	assert gaps and "没盖到本轮" in gaps[0].detail, "扩窗找回要有口径可交代，不能悄悄多读"
	window = run.window("audit")
	assert window.rows_scanned > tail.rows_scanned
	assert [f for f in evaluate_run(run) if f.rule_id == "no_turn_records"] == []


def test_harness_row_cannot_stand_in_for_this_session(write_audit) -> None:
	"""尾窗里同轮次但没有会话身份的行，不能替本会话宣布"本轮已在窗内"。

	评测/模拟器直写的行不带 session_id，而 turn_id 只有 1、2 这种小值（真实账本
	里 122 行正是这种形状），很容易和本会话的轮次撞号。撞号就不扩窗，本会话真正
	的那一行永远读不到，诊断停在"本轮无记录"——而它本来读得到。
	"""
	path = write_audit(_model_rows("r1", 1) + _harness_rows(40, _TURN))
	tail = _scan_jsonl_tail(path, 2048)
	assert tail.truncated, "夹具没造出截断的尾窗"
	assert any(
		str(r.get("turn_id") or "") == _TURN and not str(r.get("session_id") or "").strip()
		for _, r in tail.rows
	), "夹具没把撞号的身份空白行留在尾窗里"
	assert not any(
		str(r.get("turn_id") or "") == _TURN and str(r.get("session_id") or "") == _SESSION
		for _, r in tail.rows
	), "本会话那一行必须还在窗外"

	run = collect_run(_SESSION, _TURN, audit_path=path, max_audit_bytes=2048)

	assert [e for e in run.events if e.turn_id == _TURN], (
		"身份空白的那一行不属于本会话：仍然必须扩窗把本会话的行读回来"
	)
	gaps = [g for g in run.gaps if g.reason == "recovered_outside_window"]
	assert gaps and "没盖到本轮" in gaps[0].detail


def test_scan_has_turn_needs_a_comparable_identity(tmp_path) -> None:
	"""谓词只有一种放行方式：同一会话 + 同一轮次。

	没有可比身份时返回 False（宁可多扩一次窗）。"空 session_id 匹配一切"正是上一版
	把评测行当成本会话行的入口，留着它，任何一个不带身份的调用点都会自动重新获得
	那个错答。
	"""
	from diagnostics.collect import _scan_has_turn

	blank = _write_jsonl(
		tmp_path / "blank.jsonl",
		[{"ts": 9.0, "kind": "model.finished", "session_id": "", "turn_id": _TURN}],
	)
	other = _write_jsonl(
		tmp_path / "other.jsonl",
		[{"ts": 9.0, "kind": "model.finished", "session_id": "someone-else", "turn_id": _TURN}],
	)
	blank_scan = _scan_jsonl_tail(blank, 4096)
	other_scan = _scan_jsonl_tail(other, 4096)

	# 身份空白行与别家的行都不能算本轮"已在窗内"。
	assert _scan_has_turn(blank_scan, _SESSION, _TURN) is False
	assert _scan_has_turn(other_scan, _SESSION, _TURN) is False
	# 调用方没有可比身份：一律不放行，而不是"只剩轮次号可对齐"。
	assert _scan_has_turn(other_scan, "", _TURN) is False
	assert _scan_has_turn(blank_scan, "", _TURN) is False
	# 没指定轮次时不按轮筛——那是"整会话"这个问法本身。
	assert _scan_has_turn(blank_scan, _SESSION, "") is True


def test_turn_absent_from_the_whole_file_still_says_no_records(write_audit) -> None:
	"""反面对照：扩窗读完仍然没有本轮的行，结论才允许落下，并写明读过多少。"""
	from diagnostics.rules import evaluate_run

	path = write_audit(_model_rows("r1", 1) + _filler_rows(400))
	run = collect_run(_SESSION, "t-nowhere", audit_path=path, max_audit_bytes=2048)

	assert [e for e in run.events if e.turn_id == "t-nowhere"] == []
	gaps = [g for g in run.gaps if g.reason == "not_found_in_full_file"]
	assert gaps and "仍未见" in gaps[0].detail
	findings = evaluate_run(run)
	ntr = [f for f in findings if f.rule_id == "no_turn_records"]
	assert ntr and "扫描" in ntr[0].evidence[0].detail


# ---------- 9. picker 与 detail 不得给两个答案 ----------


def test_session_outside_the_tail_window_is_still_listable(write_audit, monkeypatch) -> None:
	"""列表读不到、详情却查得到 = 同一份数据的两个入口口径不一致。

	真实审计文件里就有一个会话整段排在列表的 8 MiB 窗之外（4 个轮次，列表 0 条，
	而 collect_run 扩窗后能完整诊断）。picker 必须先跟 detail 一样肯扩窗，
	否则"这条会话没有可诊断的运行"这句话是采集范围的话，不是事实。
	"""
	from diagnostics import collect as collect_module

	path = write_audit(_model_rows("r1", 1) + _filler_rows(400))
	tail = _scan_jsonl_tail(path, 4096)
	assert tail.truncated, "夹具没造出截断的尾窗"
	assert all(str(r.get("session_id") or "") != _SESSION for _, r in tail.rows), "夹具没把本会话推出尾窗"

	monkeypatch.setattr(collect_module, "_AUDIT_TAIL_BYTES", 2048)
	sink: dict = {}
	runs = collect_module.list_runs(_SESSION, audit_path=path, coverage_sink=sink)

	assert [r["turn_id"] for r in runs] == [_TURN]
	assert "已扩到" in runs[0]["coverage_note"]
	assert "读到" in runs[0]["coverage_note"]
	# 空列表时的承载处：runs 为空就没有行可以挂 note，所以扫描口径单独出口。
	assert sink["widened"] is True and sink["present"] is True
	assert sink["rows_scanned"] > 400


def test_session_absent_from_the_whole_file_says_so_without_blaming_the_window(write_audit, monkeypatch) -> None:
	"""反面对照：读完整份都没有，就不能再拿"尾窗没盖到"当说法。"""
	from diagnostics import collect as collect_module

	path = write_audit(_model_rows("r1", 1) + _filler_rows(400))
	monkeypatch.setattr(collect_module, "_AUDIT_TAIL_BYTES", 2048)
	runs = collect_module.list_runs("s-nowhere", audit_path=path)

	assert runs == []
	# 钉的是空态的含义：扩窗读完整份之后仍然空，picker 那句"该会话没有可诊断的
	# 运行"才是事实，而不是采集范围造出来的话。正面对照：同一份文件里在窗内的
	# 会话照样列得出来。
	assert collect_module.list_runs(_SESSION, audit_path=path)


# ---------- 10. 账本"没这一行"要说整份文件，不能只说读到的那一截 ----------


def test_usage_row_outside_the_ledger_window_is_not_called_unaccounted(write_audit, monkeypatch) -> None:
	"""缺账断言的范围是整份账本：只读到 61% 时"没有这行"可能只是没读到。

	真实数据复跑（57 轮）今天 0 次误判 —— 6 条缺账证据对应的键在整份文件里也确实没有；
	但账本窗口本身是截断的（尾窗 9 927 行 / 全份 16 308 行），所以那句话今天只是
	**恰好**成立。这条用例把它变成结构上成立：把本会话的账行挤到窗户外，
	旧行为会报"这一枪没有用量账"，扩窗后不该报。
	"""
	from diagnostics import collect as collect_module
	from diagnostics.rules import evaluate_run
	from usage.ledger import record_from_openai_usage

	path = write_audit(_model_rows("r1", 1))
	record_from_openai_usage(
		provider="deepseek",
		model="m",
		api_key="k",
		usage={"prompt_tokens": 100, "completion_tokens": 5},
		session_id=_SESSION,
		request_id="r1",
		attempt=1,
	)
	for i in range(400):  # 别的会话的行把上面那行推出尾窗
		record_from_openai_usage(
			provider="deepseek",
			model="m",
			api_key="k",
			usage={"prompt_tokens": 1, "completion_tokens": 1},
			session_id="other-session",
			request_id=f"o{i}",
			attempt=1,
		)
	monkeypatch.setattr(collect_module, "_AUDIT_TAIL_BYTES", 2048)

	run = collect_run(_SESSION, _TURN, audit_path=path)
	misses = [f for f in evaluate_run(run) if f.rule_id == "usage_accounting"]
	assert not misses, f"账行只是被尾窗挡住了，却被断成缺账：{[m.phenomenon for m in misses]}"
	gap = [g for g in run.gaps if g.reason == "recovered_outside_window" and g.boundary == "model_request"]
	assert gap and "读完整份" in gap[0].detail
	window = run.window("usage")
	assert window is not None and window.truncated is False


def test_window_chain_reaches_the_rule_whole(tmp_path, monkeypatch) -> None:
	"""working 快照里的整条窗口链必须交给冻结前缀规则，不先在采集器里切掉。

	采集器曾写 ``[-50:]``：链更长时最早那段违规看不见，也没人声明"只看了最后 50 条"，
	而规则照发"不变量失败/未失败"的结论。真实数据里最长一条链有 116 条（50 个真实
	会话带非空链），这条限制不是理论上的。
	"""
	import types

	from diagnostics.collect import RunEvidence, _collect_working
	from diagnostics.rules import check_frozen_head

	chain = [{"cursor": 0, "frozen_until": 10, "summary_fp": 111}]
	chain += [{"cursor": 0, "frozen_until": 10, "summary_fp": 222}]
	for i in range(58):  # 往后每段换区间，不再制造第二处违规
		chain.append({"cursor": i + 1, "frozen_until": 20 + i, "summary_fp": 222})
	assert len(chain) == 60

	snap = types.SimpleNamespace(
		session_id="s1",
		compact_checkpoint=types.SimpleNamespace(
			anchor_cursor=0, anchor_frozen_until=10, window_chain=chain
		),
	)
	monkeypatch.setattr("memory.working.hydrate", lambda _sid: snap)

	run = RunEvidence(session_id="s1", turn_id="t1")
	_collect_working(run, "s1")

	carried = run.working["compact_checkpoint"]
	assert len(carried["window_chain"]) == 60, len(carried["window_chain"])
	assert carried["window_chain_total"] == 60

	findings = check_frozen_head(run)
	assert len(findings) == 1, "链首那处违规被采集器切掉了"
	assert "摘要长度" in findings[0].phenomenon
	assert "len(summary_text)" in findings[0].coverage_gap


def _fold_gap_detail(run, ledger: Path) -> str:
	from diagnostics.collect import _collect_folds

	_collect_folds(run, _SESSION)
	gaps = [g for g in run.gaps if g.boundary == "wsc_fold" and g.reason == "no_records"]
	assert gaps, [f"{g.boundary}/{g.reason}" for g in run.gaps]
	return gaps[0].detail


def test_fold_gap_carries_the_folding_evidence(tmp_path, monkeypatch) -> None:
	from diagnostics.collect import RunEvidence
	"""折叠账本对本会话零行时，把 working 快照里的折叠边界数一起说出来。

	全量普查（540 真实轮）里这条缺项对 539/540 同形 —— 恒真的"没记录"不携带本轮
	信息；而同一批数据里 50 个会话的快照确实带折叠边界。那部分应当变成证据。
	"""
	ledger = tmp_path / "fold_events.jsonl"
	_write_jsonl(ledger, [{"session_id": "someone-else", "fold": True}])
	monkeypatch.setattr("usage.ledger.fold_events_path", lambda: ledger)

	with_chain = RunEvidence(session_id=_SESSION, turn_id=_TURN)
	with_chain.working = {
		"locator": str(ledger),
		"compact_checkpoint": {"window_chain_total": 29},
	}
	detail = _fold_gap_detail(with_chain, ledger)
	assert "29 条折叠边界" in detail, detail

	without = RunEvidence(session_id=_SESSION, turn_id=_TURN)
	without.working = {"locator": str(ledger)}
	assert "working 快照也没有折叠边界记录" in _fold_gap_detail(without, ledger)


def _working_run(manifest: dict | None, *, turn_proj: str = "p-mine"):
	"""造一个"审计里有本轮投影 id + working 快照里有/没有 manifest"的运行视图。"""
	import types

	from diagnostics.collect import RunEvidence, _collect_working, normalize_event

	run = RunEvidence(session_id=_SESSION, turn_id=_TURN)
	run.events = [
		normalize_event(
			0, 7, {"kind": "model.started", "session_id": _SESSION, "turn_id": _TURN, "projection_id": turn_proj}
		)
	]
	snap = types.SimpleNamespace(
		session_id=_SESSION,
		last_projection_manifest=manifest,
		compact_checkpoint=None,
	)
	return run, _collect_working, snap


def test_projection_gap_names_the_real_limitation(tmp_path, monkeypatch) -> None:
	"""缺项原因必须对上事实的形状，三形三面。

 ``field_missing`` 在界面上写的是"记录里缺该字段"；而 working 快照这里字段常常是
 在的，缺的是"它属于哪一轮"的粒度 —— 全量普查（540/540 轮同形）里这条被当成
 "缺字段"报了 540 次，本轮已有自己的 manifest 时也在报。
	"""
	def patch(snap):
		monkeypatch.setattr("memory.working.hydrate", lambda _sid: snap)

	# 形一：manifest 在，但不是本轮那一份 ⇒ not_comparable
	run, collect, snap = _working_run({"projection_id": "p-other", "invariant_errors": []})
	patch(snap)
	collect(run, _SESSION)
	reasons = {(g.boundary, g.reason) for g in run.gaps}
	assert ("instruction_context", "not_comparable") in reasons, reasons
	assert ("instruction_context", "field_missing") not in reasons, reasons

	# 形二：快照里没有 manifest ⇒ no_records（不是"缺字段"）
	run2, collect2, snap2 = _working_run(None)
	patch(snap2)
	collect2(run2, _SESSION)
	r2 = {(g.boundary, g.reason) for g in run2.gaps}
	assert ("instruction_context", "no_records") in r2, r2
	assert ("instruction_context", "field_missing") not in r2, r2

	# 形三：本轮那份就在手 ⇒ 不再挂任何投影类缺项（窗口 note 已经说了范围）
	run3, collect3, snap3 = _working_run({"projection_id": "p-mine", "invariant_errors": []})
	patch(snap3)
	collect3(run3, _SESSION)
	assert not [
		g for g in run3.gaps
		if g.boundary == "instruction_context" and g.reason in {"field_missing", "not_comparable", "no_records"}
	], [(g.reason, g.detail) for g in run3.gaps]


def test_add_gap_tags_session_scope_by_boundary_reason_pair():
	"""缺项按 (边界, 原因) 精确标会话级；同因不同边界不得连带误标。"""
	from diagnostics.collect import RunEvidence, SESSION_CONSTANT_GAPS

	run = RunEvidence(session_id="s", turn_id="t")
	# 三条已实测"逐会话全有或全无"的会话级项：no_records 落在 instruction_context 上是会话姿态。
	run.add_gap("instruction_context", "no_records", "x")
	run.add_gap("model_request", "out_of_window", "o")
	run.add_gap("instruction_context", "recovered_outside_window", "r")
	# 同因不同边界的反例：source_absent 挂在 model_request 上仍属本轮事实（只在 adapter 那侧才是会话级）。
	run.add_gap("model_request", "source_absent", "y")
	# 真随轮变化的会话级"同名不同义"反例：not_comparable 只有 13.7%，不在折叠集里。
	run.add_gap("instruction_context", "not_comparable", "n")
	by_pair = {(g.boundary, g.reason): g.scope for g in run.gaps}
	assert by_pair[("instruction_context", "no_records")] == "session"
	assert by_pair[("model_request", "out_of_window")] == "session"
	assert by_pair[("instruction_context", "recovered_outside_window")] == "session"
	assert by_pair[("model_request", "source_absent")] == "per_turn"
	assert by_pair[("instruction_context", "not_comparable")] == "per_turn"
	# 声明集合里的每一条 add_gap 后都必须是 session（防声明与实现漂移）。
	for pair in SESSION_CONSTANT_GAPS:
		g = run.add_gap(pair[0], pair[1], "d")
		assert g.scope == "session", pair
	assert run.to_dict()["gaps"][0]["scope"] == "session"
