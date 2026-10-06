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

def test_xml_arg_coercion_does_not_reshape_digits() -> None:
	# 带前导零的串被 int() 吞掉 = 模型请求的检索词/文件名被静默换掉（"007" → 7）。
	open_t = "<" + "tool_call>"
	close_t = "<" + "/tool_call>"
	key_t = "<" + "arg_key>"
	kend_t = "<" + "/arg_key>"
	val_t = "<" + "arg_value>"
	vend_t = "<" + "/arg_value>"

	def one(tool: str, key: str, val: str) -> str:
		return open_t + tool + key_t + key + kend_t + val_t + val + vend_t + close_t

	uses, _cleaned = extract_xml_tool_calls(one("Grep", "pattern", "007"))
	assert uses[0].input["pattern"] == "007"
	uses, _ = extract_xml_tool_calls(one("Grep", "pattern", "0042"))
	assert uses[0].input["pattern"] == "0042"

	# 规范数字与布尔口径照旧（这条测试不是把整条 coercion 拆掉）。
	uses, _ = extract_xml_tool_calls(one("Read", "limit", "20"))
	assert uses[0].input["limit"] == 20
	uses, _ = extract_xml_tool_calls(one("Read", "offset", "-150"))
	assert uses[0].input["offset"] == -150
	uses, _ = extract_xml_tool_calls(one("Read", "ratio", "1.5"))
	assert uses[0].input["ratio"] == 1.5
	uses, _ = extract_xml_tool_calls(one("Grep", "i", "true"))
	assert uses[0].input["i"] is True
	uses, _ = extract_xml_tool_calls(one("Grep", "glob", "null"))
	assert uses[0].input["glob"] is None

	# 非规范数值一律原样交回工具，由工具自己的类型层判。
	uses, _ = extract_xml_tool_calls(one("Bash", "command", "pip show pkg==1.2.3"))
	assert uses[0].input["command"] == "pip show pkg==1.2.3"
	uses, _ = extract_xml_tool_calls(one("Read", "limit", "3."))
	assert uses[0].input["limit"] == "3."
	uses, _ = extract_xml_tool_calls(one("Read", "limit", "+5"))
	assert uses[0].input["limit"] == "+5"
