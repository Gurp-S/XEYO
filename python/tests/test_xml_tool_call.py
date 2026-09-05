"""XML tool_call recovery (glm-style plain-text tools)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.xml_tool_call import extract_xml_tool_calls, looks_like_raw_tool_markup
from engine.subagent_runner import _usable_conclusion
from msgtypes.message import assistant_text_message


SAMPLE = """
I'll read the file next.
<tool_call>Read
<arg_key>file_path</arg_key>
<arg_value>D:\\lea\\XenYon code\\python\\permissions\\filesystem.py</arg_value>
<arg_key>limit</arg_key>
<arg_value>20</arg_value>
<arg_key>offset</arg_key>
<arg_value>150</arg_value>
</tool_call>
"""


def test_extract_xml_tool_calls_read():
	uses, cleaned = extract_xml_tool_calls(SAMPLE)
	assert len(uses) == 1
	assert uses[0].name == "Read"
	assert uses[0].input["file_path"].endswith("filesystem.py")
	assert uses[0].input["limit"] == 20
	assert uses[0].input["offset"] == 150
	assert "<tool_call>" not in cleaned
	assert "I'll read the file next." in cleaned


def test_looks_like_raw_tool_markup():
	only = (
		"<tool_call>Read\n"
		"<arg_key>file_path</arg_key>\n"
		"<arg_value>a.py</arg_value>\n"
		"</tool_call>"
	)
	assert looks_like_raw_tool_markup(only)
	assert not looks_like_raw_tool_markup("正常总结，没有工具调用")


def test_usable_conclusion_falls_back():
	msgs = [
		assistant_text_message("记忆系统分 L3/L4，索引在 MEMORY.md。"),
		assistant_text_message(
			"<tool_call>Read\n"
			"<arg_key>file_path</arg_key>\n"
			"<arg_value>a.py</arg_value>\n"
			"</tool_call>"
		),
	]
	out = _usable_conclusion(
		msgs,
		"<tool_call>Read\n<arg_key>file_path</arg_key>\n"
		"<arg_value>a.py</arg_value>\n</tool_call>",
	)
	assert "MEMORY.md" in out
	assert "<tool_call>" not in out
