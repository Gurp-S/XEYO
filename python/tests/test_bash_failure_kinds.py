"""B-5-A：Bash 失败结果的 error_kind 组成映射（只补 kind，不改模型可见呈现）。

台账切片（近 10 天真实口径）：Bash 失败 218/1683=13.0% 全落 INTERNAL，组成=POSIX
命令打非 POSIX 壳（"不会被识别"）/ ParserError / 泛 exit 1。本档钉两件事：
1) 映射本身（单位级）；2) 真实工具端到端两例——缺命令 → COMMAND_NOT_FOUND，
   泛 exit≠0 → 保持 INTERNAL（不硬归责）。
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from engine.abort import AbortController
from permissions.filesystem import mark_permission_preapproved
from tools.bash_tool.bash_tool import BashOutput, BashTool, classify_failure_kind


def _out(**kw) -> BashOutput:
	base = dict(code=1, stdout="", is_error=True)
	base.update(kw)
	return BashOutput(**base)


def test_timeout_and_abort_kinds() -> None:
	assert classify_failure_kind(_out(timed_out=True), "x") == "TIMEOUT"
	assert classify_failure_kind(_out(interrupted=True), "x") == "ABORTED"


def test_command_not_found_by_exit_code_and_text() -> None:
	assert classify_failure_kind(_out(code=127), "sh: foo: not found") == "COMMAND_NOT_FOUND"
	zh = "head: 术语 'head' 不会被识别为 cmdlet、函数、脚本文件或可执行程序的名称。"
	assert classify_failure_kind(_out(), zh) == "COMMAND_NOT_FOUND"
	en = "'foo' is not recognized as an internal or external command"
	assert classify_failure_kind(_out(), en) == "COMMAND_NOT_FOUND"


def test_parse_error_is_invalid_argument() -> None:
	assert classify_failure_kind(_out(), "ParserError: \nLine |\n   1 | ...") == "INVALID_ARGUMENT"
	assert classify_failure_kind(_out(), "bash: syntax error near unexpected token") == "INVALID_ARGUMENT"


def test_generic_nonzero_stays_unattributed() -> None:
	assert classify_failure_kind(_out(code=1), "Exit code 1") is None
	assert classify_failure_kind(_out(code=2), "pytest: 1 failed") is None


win_only = pytest.mark.skipif(sys.platform != "win32", reason="真实壳行为只在 Windows 本机钉")


@win_only
def test_real_missing_command_kind_end_to_end(tmp_path) -> None:
	tool = BashTool(cwd=str(tmp_path))
	# 生产由 registry 包裹 preapprove（策略 ASK→放行）；直连 execute 需自备同一环。
	with mark_permission_preapproved(True):
		res = asyncio.run(
			tool.execute({"command": "xeyo_definitely_missing_cmd_987"}, AbortController())
		)
	assert res.is_error
	assert res.error_kind == "COMMAND_NOT_FOUND", res.content[:200]


@win_only
def test_real_generic_failure_stays_internal(tmp_path) -> None:
	tool = BashTool(cwd=str(tmp_path))
	with mark_permission_preapproved(True):
		res = asyncio.run(tool.execute({"command": "exit 3"}, AbortController()))
	assert res.is_error
	assert res.error_kind == "INTERNAL", res.content[:200]
