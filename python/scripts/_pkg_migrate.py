# -*- coding: utf-8 -*-
"""一次性迁移:单文件工具 → grep_tool 式包结构;删除脚手架空壳。"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

# ---------- 1) 单文件 → 包(包名==旧模块名,外部导入零改动) ----------
SIMPLE = {
	# pkg: (impl_module_name, class, name_consts, old_desc_literal 或 None)
	"echo": ("echo_tool", "EchoTool", [], '"Echo text back"'),
	"get_time": ("get_time_tool", "GetTimeTool", [], '"Get the current local date and time as YYYY-MM-DD HH:MM:SS"'),
}

PAREN = {
	"screenshot_tool": ("screenshot_tool", "ScreenshotTool", ["SCREENSHOT_TOOL_NAME"]),
	"send_to_wechat_tool": ("send_to_wechat_tool", "SendToWeChatTool", ["SEND_TO_WECHAT_TOOL_NAME"]),
	"ask_user_question_tool": (
		"ask_user_question_tool",
		"AskUserQuestionTool",
		["ASK_USER_TOOL_NAME", "ASK_REQUEST_ID_KEY"],
	),
}

for pkg, spec in {**SIMPLE, **PAREN}.items():
	impl, cls, consts = spec[0], spec[1], spec[2]
	pkg_dir = TOOLS / pkg
	pkg_dir.mkdir(exist_ok=True)
	src = TOOLS / f"{pkg}.py"
	if not src.is_file():
		print("skip(no src)", pkg)
		continue
	text = src.read_text(encoding="utf-8")

	if pkg in SIMPLE:
		desc_lit = SIMPLE[pkg][3]
		assert desc_lit in text, pkg
		description = desc_lit.strip('"')
		text = text.replace(desc_lit, "DESCRIPTION")
	else:
		m = re.search(r"\t{2,3}\"description\": \([\s\S]*?\n\t{2,3}\),", text)
		assert m, f"paren desc not found: {pkg}"
		block = m.group(0)
		# 抽取括号内所有字符串字面量拼接为 DESCRIPTION 文本
		strings = re.findall(r'"((?:[^"\\]|\\.)*)"', block)
		description = "".join(strings)
		text = text.replace(block, '\t\t\t"description": DESCRIPTION,')

	const_names = ", ".join(["DESCRIPTION", *consts])
	text = text.rstrip() + "\n"
	anchor = "from tools.base_tool import ToolResult"
	assert anchor in text, f"base_tool anchor missing: {pkg}"
	text = text.replace(
		anchor,
		anchor + "\n" + "\n".join(f"from tools.{pkg}.prompt import {c}" for c in ["DESCRIPTION", *consts]),
		1,
	)
	(TOOLS / pkg / f"{impl}.py").write_text(text, encoding="utf-8", newline="")

	prompt_lines = [
		f'"""{pkg} 描述文本(grep_tool 式结构)。"""',
		"",
		"DESCRIPTION = (",
	]
	body = description.replace('"""', '\\"\\"\\"')
	prompt_lines.append(f'\t"{body}"')
	prompt_lines.append(")")
	(TOOLS / pkg / "prompt.py").write_text("\n".join(prompt_lines) + "\n", encoding="utf-8", newline="")

	init_exports = [f"from tools.{pkg}.prompt import DESCRIPTION", f"from tools.{pkg}.{impl} import {cls}"]
	for c in consts:
		init_exports.insert(1, f"from tools.{pkg}.{impl} import {c}")
	(init := TOOLS / pkg / "__init__.py").write_text(
		'"""' + pkg + ' — re-exports。"""\n\n' + "\n".join(init_exports) + "\n",
		encoding="utf-8", newline="")
	src.unlink()
	print("packaged", pkg)

# ---------- 2) memory_tool.py → memory_tool 包 ----------
mpkg = TOOLS / "memory_tool"
mpkg.mkdir(exist_ok=True)
msrc = TOOLS / "memory_tool.py"
if msrc.is_file():
	text = msrc.read_text(encoding="utf-8")
	# 动态 description 块替换为 prompt.build_description
	m = re.search(r"\t\t\t\"description\": \([\s\S]*?\n\t\t\t\),", text)
	assert m, "memory desc block"
	text = text.replace(m.group(0), '\t\t\t"description": build_description(mem, sess),')
	text = text.replace(
		"from tools.memory_forget import MemoryForgetTool\nfrom tools.memory_write import MemoryUpdateTool, MemoryWriteTool",
		"from tools.memory_forget import MemoryForgetTool\nfrom tools.memory_write import MemoryUpdateTool, MemoryWriteTool\nfrom tools.memory_tool.prompt import build_description",
	)
	(mpkg / "memory_tool.py").write_text(text, encoding="utf-8", newline="")
	msrc.unlink()
	(mpkg / "prompt.py").write_text(
		'"""memory_tool 描述文本(动态路径由 tool 注入)。"""\n\n'
		'def build_description(mem: str, sess: str) -> str:\n'
		'\treturn (\n'
		'\t\t"Workspace long-term memory (write path). "\n'
		'\t\t"action=write: persist a durable fact the user asked to remember "\n'
		'\t\t"(type/content required; preferences, project constraints, confirmed feedback). "\n'
		'\t\t"action=update: modify an existing note by id. "\n'
		'\t\t"action=forget: forget by id (tombstone; must never be restored). "\n'
		'\t\t"Do not store directory trees or one-off plans as notes. "\n'
		'\t\tf"To READ memory use Grep directly on the memory dir: {mem} "\n'
		'\t\t"(MEMORY.md is a navigation index only; details live in topics/*.md). "\n'
		'\t\tf"Current session transcript is greppable at: {sess}"\n'
		'\t)\n',
		encoding="utf-8", newline="")
	(mpkg / "__init__.py").write_text(
		'"""memory_tool — re-exports。"""\n\n'
		"from tools.memory_tool.memory_tool import MemoryTool\n\n"
		'__all__ = ["MemoryTool"]\n',
		encoding="utf-8", newline="")
	print("packaged memory_tool")

# ---------- 3) 删除脚手架空壳 ----------
SCAFFOLDS = [
	"agent_tool", "enter_plan_mode_tool", "exit_plan_mode_tool", "notebook_edit_tool",
	"web_fetch_tool", "web_search_tool", "skill_tool", "send_message_tool",
	"list_mcp_resources_tool", "read_mcp_resource_tool", "lsp_tool",
	"task_create_tool", "task_get_tool", "task_update_tool", "task_list_tool",
	"task_stop_tool", "task_output_tool",
]
for s in SCAFFOLDS:
	p = TOOLS / f"{s}.py"
	if p.is_file():
		p.unlink()
		print("deleted scaffold", s)
print("--- done")
