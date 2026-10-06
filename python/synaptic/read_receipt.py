"""Native read receipt status is independent of the returned file content."""

from __future__ import annotations

from synaptic.textutil import classify_tool


def is_successful_read(block: dict, tool_name: str) -> bool:
	"""Only an explicit successful native read bypasses content heuristics."""
	return block.get("is_error") is False and tool_name in ("Read", "NotebookRead")


def is_read_semantic(block: dict, tool_name: str, *, command: str = "") -> bool:
	"""显式成功的读语义回执：Grep/Glob 搜索与 Bash 只读白名单单命令。

	它们的输出是**文件内容或命中行**，不是运行结果：正文里出现 ``Traceback``
	之类的字样只说明读到了那段文本（实测 v61_evidence_gate.py 的夹具串、被搜到的
	源码注释），不构成本次调用失败。管道/重定向/写命令与缺失显式回执的形状不在
	此列——退出码可被管道洗掉，文本升格是那类形状的唯一证据，必须保留。
	"""
	if block.get("is_error") is not False:
		return False
	if is_successful_read(block, tool_name):
		return True
	is_write, read_only, _ = classify_tool(tool_name, {"command": command} if command else {})
	return read_only and not is_write
