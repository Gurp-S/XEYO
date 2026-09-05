# -*- coding: utf-8 -*-
"""一次性:catalog.py 移除脚手架机械与未用引擎导入。"""
from __future__ import annotations

import ast
import re
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "tools" / "catalog.py"
text = p.read_text(encoding="utf-8")

SCAFFOLD_MODULES = [
	"agent_tool", "enter_plan_mode_tool", "exit_plan_mode_tool",
	"list_mcp_resources_tool", "lsp_tool", "notebook_edit_tool",
	"read_mcp_resource_tool", "send_message_tool", "skill_tool",
	"task_create_tool", "task_get_tool", "task_list_tool",
	"task_output_tool", "task_stop_tool", "task_update_tool",
	"web_fetch_tool", "web_search_tool",
]

# 1) 删脚手架 import 行
lines = text.splitlines()
keep = [
	ln for ln in lines
	if not any(f"tools.{m} import" in ln or f"import tools.{m}" in ln for m in SCAFFOLD_MODULES)
]
text = "\n".join(keep)

# 2) 删未用引擎直接导入(Memory 包装后 catalog 不再需要)
text = re.sub(
	r"from tools\.memory_forget import MemoryForgetTool\n"
	r"from tools\.memory_write import MemoryUpdateTool, MemoryWriteTool\n",
	"", text)

# 3) 删对应工厂函数(def 块到下一个顶层定义前)
FACTORY_NAMES = [
	"_agent", "_enter_plan", "_exit_plan", "_notebook_edit", "_web_fetch",
	"_web_search", "_skill", "_send_message", "_list_mcp", "_read_mcp",
	"_lsp", "_task_create", "_task_get", "_task_update", "_task_list",
	"_task_stop", "_task_output",
]
for name in FACTORY_NAMES:
	text = re.sub(
		rf"\ndef {name}\(_cwd: str\) -> Tool:\n(?:\t[^\n]*\n)+\n",
		"\n", text)

# 4) 删 SCAFFOLD_TOOLS 段(注释块+赋值)
text = re.sub(
	r"# ={10,}\n# 脚手架工具矩阵[\s\S]*?\nSCAFFOLD_TOOLS: Sequence\[ToolFactory\] = \([\s\S]*?\n\)\n",
	"", text)

# 5) 删两个脚手架函数
text = re.sub(
	r"\ndef build_full_scaffold_registry\([\s\S]*?\n\ndef scaffold_tool_names[\s\S]*?\n\treturn \[factory\(cwd\)\.name for factory in SCAFFOLD_TOOLS\]\n",
	"\n", text)

# 6) 头部 docstring 更新
text = text.replace(
	'工作流：\n  1. 在 tools/<name>_tool.py（或 tools/<pkg>/）中实现 execute()\n'
	'  2. 将工厂函数从 SCAFFOLD_TOOLS 移到 ENABLED_TOOLS\n\n'
	'脚手架工具不会注册（模型尚无法调用）。\n',
	'工作流：在 tools/<name>_tool/ 包内实现 execute() 与 prompt.py，'
	'然后把工厂加入 ENABLED_TOOLS。（脚手架空壳已于 2026-08 清理）\n')

ast.parse(text)
p.write_text(text, encoding="utf-8", newline="")
print("catalog cleaned; syntax ok")
