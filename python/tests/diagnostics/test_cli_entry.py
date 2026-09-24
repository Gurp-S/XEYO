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
