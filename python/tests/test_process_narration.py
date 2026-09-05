"""过程旁白：工作中可展示，工具轮落盘时剥掉。"""

from __future__ import annotations

from engine.process_narration import (
	StreamNarrationGate,
	is_process_narration,
	strip_process_narration,
)


def test_strip_chinese_narration_lines():
	raw = "让我查看工作区展开/收起按钮的具体实现:\n\n真正结论在这里。"
	assert strip_process_narration(raw) == "真正结论在这里。"


def test_strip_pure_narration_empty():
	assert strip_process_narration("让我搜索更多关于展开/收起功能的信息:") == ""
	assert is_process_narration("让我看看相关代码。")


def test_keep_normal_answer():
	text = "根据目前的实现，折叠动画依赖 grid-template-rows。"
	assert strip_process_narration(text) == text
	assert not is_process_narration(text)


def test_english_narration():
	assert is_process_narration("Let me check the expand handler.")
	assert strip_process_narration("Let me look at the file.\n\nDone.") == "Done."


def test_gate_streams_narration_live():
	"""进行中要能看到旁白。"""
	gate = StreamNarrationGate()
	assert gate.on_delta("让我") == ["让我"]
	assert gate.on_delta("看看实现:") == ["看看实现:"]
	gate.on_tool_use()
	cleaned, flush = gate.finish(has_tools=True)
	assert cleaned == ""
	assert flush == []


def test_gate_persists_final_without_tools():
	gate = StreamNarrationGate()
	assert gate.on_delta("完整答复") == ["完整答复"]
	cleaned, flush = gate.finish(has_tools=False)
	assert cleaned == "完整答复"
	assert flush == []
