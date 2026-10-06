"""容器路由的退出码收尾必须与宿主等价（2026-10-05）。

修前：`BashTool.call` 的容器分支
`return BashOutput(code=out_code, stdout=out_text)` 提前返回，
跳过了宿主路径在 :830 的 `interpret_command_result` 与非零退出的
"Exit code N" 追加 ⇒ `ToolResult.is_error` 恒 False（TB 评测路由
上"失败被当成成功"，归属表同步说谎）。
"""

from __future__ import annotations

import inspect

from tools.bash_tool.bash_tool import BashTool, _finalize_docker_result


def test_nonzero_exit_is_error_with_exit_code_line() -> None:
	out = _finalize_docker_result("false", 1, "boom\n")
	assert out.is_error is True
	assert out.code == 1
	assert "Exit code 1" in out.stdout
	assert out.return_code_interpretation


def test_interpretation_semantics_shared_with_host() -> None:
	"""git diff exit 1 是"有差异"不是错误——与宿主同一条 interpret 口径。"""
	out = _finalize_docker_result("git diff HEAD~1", 1, "diff --git a b")
	assert out.is_error is False
	assert "Exit code" not in out.stdout


def test_success_untouched() -> None:
	out = _finalize_docker_result("echo hi", 0, "hi\n")
	assert out.is_error is False
	assert out.stdout == "hi\n"


def test_docker_exec_failure_surfaces() -> None:
	out = _finalize_docker_result("anything", 95, "docker exec failed: x")
	assert out.is_error is True
	assert "Exit code 95" in out.stdout


def test_container_branch_is_wired_to_finalize() -> None:
	"""接线断言：容器分支必须走 _finalize_docker_result（防回退到裸 BashOutput）。"""
	src = inspect.getsource(BashTool.call)
	assert "_finalize_docker_result(inp.command, out_code, out_text)" in src
	assert "BashOutput(code=out_code, stdout=out_text)" not in src
