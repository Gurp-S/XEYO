"""投影 dump 通道（16 条缺陷 #14）：实发头文本按开关落盘，不重算、不重放。"""

from __future__ import annotations

from memory.wsc_projection import _dump_emission


def test_dump_writes_emitted_head_when_enabled(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path))
	monkeypatch.setenv("XEYO_WSC_DUMP", "1")
	_dump_emission("[CONSTRAINTS] 目标: 甲\n[MAIN] #1 ok")
	out = tmp_path / "wsc_dump" / "emissions.txt"
	text = out.read_text(encoding="utf-8")
	assert "[CONSTRAINTS] 目标: 甲" in text
	assert "#1 ok" in text


def test_dump_appends_across_shots(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path))
	monkeypatch.setenv("XEYO_WSC_DUMP", "1")
	_dump_emission("第一枪")
	_dump_emission("第二枪")
	text = (tmp_path / "wsc_dump" / "emissions.txt").read_text(encoding="utf-8")
	assert text.index("第一枪") < text.index("第二枪")


def test_dump_silent_by_default(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path))
	monkeypatch.delenv("XEYO_WSC_DUMP", raising=False)
	_dump_emission("不该落盘")
	assert not (tmp_path / "wsc_dump").exists()


def test_dump_failure_never_breaks_main_chain(tmp_path, monkeypatch):
	"""落盘失败静默（调试钩子不许影响主链）。"""
	blocker = tmp_path / "afile"
	blocker.write_text("x", encoding="utf-8")
	monkeypatch.setenv("XEYO_WSC_DUMP", "1")
	monkeypatch.setenv("XEYO_HOME", str(blocker))  # 目标父路径是文件 ⇒ mkdir 必失败
	_dump_emission("x")  # 不抛异常即通过
