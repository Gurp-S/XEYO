"""CLI 入口：只读命令不得写产物，pin/verifier 只写索引。"""

from __future__ import annotations

import json

from diagnostics import store
from diagnostics.__main__ import main
from diagnostics.capture import capture_enabled


def _seed(tmp_path, monkeypatch):
	audit = tmp_path / "audit.jsonl"
	audit.write_text(
		json.dumps({"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1}) + "\n"
		+ json.dumps({"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "ok"}) + "\n",
		encoding="utf-8",
	)
	import audit.log as mod

	monkeypatch.setattr(mod, "_default", mod.AuditLog(audit))
	return audit


def test_read_only_commands_write_nothing(tmp_path, monkeypatch, capsys) -> None:
	audit = _seed(tmp_path, monkeypatch)
	assert main(["runs", "--session", "s1"]) == 0
	assert main(["report", "--session", "s1", "--turn", "t1"]) == 0
	assert main(["fact", "--session", "s1", "--turn", "t1", "--needle", "model.started"]) == 0
	assert main(["disk"]) == 0
	assert main(["capture", "--session", "s1"]) == 0
	out = capsys.readouterr().out
	assert "已确认" in out or "未定" in out
	assert not store.diagnostics_root().exists() or store.dir_size(store.diagnostics_root()) == 0
	assert audit.read_text(encoding="utf-8").count("\n") == 2, "只读命令不得写审计"


def test_text_report_prints_the_evidence_behind_a_cause(tmp_path, monkeypatch, capsys) -> None:
	"""text 输出也要印出原因的证据：指针只留在 --format json 里，读终端的人拿不到。"""
	audit = tmp_path / "audit.jsonl"
	rows = [
		{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1},
		{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "ok"},
		{"ts": 1.2, "kind": "tool.started", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Bash"},
		{"ts": 1.3, "kind": "tool.finished", "session_id": "s1", "turn_id": "t1", "request_id": "c1", "tool_name": "Bash", "is_error": True, "status": "error", "error_kind": "INTERNAL"},
	]
	audit.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
	import audit.log as mod

	monkeypatch.setattr(mod, "_default", mod.AuditLog(audit))
	assert main(["report", "--session", "s1", "--turn", "t1"]) == 0
	out = capsys.readouterr().out
	assert "证据：audit:" in out, "定责的原因要在终端里也指回那条审计行"


def test_json_and_md_formats(tmp_path, monkeypatch, capsys) -> None:
	_seed(tmp_path, monkeypatch)
	assert main(["report", "--session", "s1", "--turn", "t1", "--format", "json", "--save"]) == 0
	saved_line = capsys.readouterr().out.splitlines()[0]
	assert saved_line.startswith("已保存：")
	assert main(["report", "--session", "s1", "--turn", "t1", "--format", "md"]) == 0
	md = capsys.readouterr().out
	assert "# XEYO 诊断报告" in md
	assert list(store.reports_dir().glob("*.json"))


def test_pin_and_verifier_via_cli(tmp_path, monkeypatch, capsys) -> None:
	_seed(tmp_path, monkeypatch)
	assert main(["pin", "--session", "s1", "--turn", "t1", "--note", "结果不对", "--expected", "应先跑测试"]) == 0
	assert main(["verifier", "--session", "s1", "--turn", "t1", "--name", "pytest"]) == 0
	out = capsys.readouterr().out
	assert "未运行" in out
	from diagnostics.pins import pins_for_run

	rows = pins_for_run("s1", "t1")
	assert {r["kind"] for r in rows} == {"run_mark", "verifier"}


def test_capture_toggle_requires_one_direction(tmp_path, monkeypatch, capsys) -> None:
	_seed(tmp_path, monkeypatch)
	assert capture_enabled("s1") is False
	assert main(["capture", "--session", "s1", "--on"]) == 0
	assert capture_enabled("s1") is True
	assert main(["capture", "--session", "s1", "--off"]) == 0
	assert capture_enabled("s1") is False
	assert main(["capture", "--session", "s1"]) == 0
	assert "关" in capsys.readouterr().out


def test_fact_output_is_chinese_not_machine_enums(tmp_path, monkeypatch, capsys) -> None:
	"""CLI 的 fact 正文只印中文：枚举值留给结构化字段，不该出现在终端正文里。

	report 那条命令早就按 `*_label` 印中文，fact 一直把 `absent` /
	`lost_before:emitted` 原样丢给人读 —— 同一个工具里两套口径。
	"""
	audit = tmp_path / "audit.jsonl"
	rows = [
		{"ts": 1.0, "kind": "model.started", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "projection_id": "p1"},
		{"ts": 1.1, "kind": "model.finished", "session_id": "s1", "turn_id": "t1", "model_request_id": "r1", "attempt": 1, "status": "ok", "projection_id": "p1"},
	]
	audit.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
	import audit.log as mod

	monkeypatch.setattr(mod, "_default", mod.AuditLog(audit))

	from memory.working import path_for
	from session.persistence import transcript_path

	tt = transcript_path("s1")
	tt.parent.mkdir(parents=True, exist_ok=True)
	tt.write_text(
		json.dumps({"id": "m1", "role": "user", "ts": 0.5, "content": "部署前先跑迁移"}, ensure_ascii=False) + "\n",
		encoding="utf-8",
	)
	wp = path_for("s1")
	wp.parent.mkdir(parents=True, exist_ok=True)
	wp.write_text(
		json.dumps(
			{
				"session_id": "s1",
				"last_x_sent": json.dumps([{"content": "无关内容"}], ensure_ascii=False),
				"last_projection_manifest": {"projection_id": "p1", "created_at": 1.0, "messages_kept": 1},
			},
			ensure_ascii=False,
		),
		encoding="utf-8",
	)

	assert main(["fact", "--session", "s1", "--turn", "t1", "--needle", "部署前先跑迁移"]) == 0
	out = capsys.readouterr().out
	assert "丢在发射之前" in out, out
	for raw in ("lost_before:emitted", "not_in_source_history", "absent", "not_recorded", "not_captured"):
		assert raw not in out, (raw, out)


def test_sessions_command_lists_ledger_only_sessions_and_stays_readable(tmp_path, monkeypatch, capsys) -> None:
	"""CLI 的发现面：``runs`` 要先知道 session id，账本独有的会话此前无从查起。"""
	audit = tmp_path / "audit.jsonl"
	rows = [
		{"ts": 1.0, "kind": "model.started", "session_id": "ghost", "turn_id": "g1", "model_request_id": "r1", "attempt": 1},
		{"ts": 2.0, "kind": "tool.started", "session_id": "other", "turn_id": "o1", "request_id": "c1", "tool_name": "Read"},
		{"ts": 3.0, "kind": "model.started"},
	]
	audit.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
	import audit.log as mod

	monkeypatch.setattr(mod, "_default", mod.AuditLog(audit))
	assert main(["sessions"]) == 0
	out = capsys.readouterr().out
	assert "ghost" in out and "other" in out
	assert "轮次1个" in out, out
	# 缺身份的那行必须报数：静默少列会让清单看着"再没有别的会话"
	assert "1 行缺 session_id" in out, out
	# 列出来的目的是问得到：同一个 id 接得上 runs
	assert main(["runs", "--session", "ghost"]) == 0
	assert "g1" in capsys.readouterr().out


def test_sessions_command_says_a_missing_ledger_is_not_an_empty_one(tmp_path, monkeypatch, capsys) -> None:
	import audit.log as mod

	monkeypatch.setattr(mod, "_default", mod.AuditLog(tmp_path / "absent.jsonl"))
	assert main(["sessions"]) == 0
	out = capsys.readouterr().out
	assert "审计文件不存在" in out, out
