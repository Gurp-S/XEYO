"""pwsh 控制台编码修复：默认 gb2312 的中文输出是"静默有损"，前缀钉成 UTF-8。

现场（sess_musrbw08_n9tly2）：工具结果里 `"label": "读上下文 �?决策"`（→ 变 �?）
与两次 `python -c` 的 `OSError: [Errno 22]`——同一处不匹配的两种症状（能编的字节
静默乱码，编不了的直接报错）。
"""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

from tools.bash_tool.bash_tool import BashInput, BashTool
from tools.bash_tool.runner import _UTF8_PREFIX, apply_utf8_command, build_shell_argv

win_only = pytest.mark.skipif(sys.platform != "win32", reason="pwsh 编码现实只在 Windows")


def _default_console_encoding() -> str:
	argv, _ = build_shell_argv("")
	p = subprocess.run([*argv, "[Console]::OutputEncoding.WebName"], capture_output=True)
	return (p.stdout or b"").decode("utf-8", "replace").strip()


def _console_codepage() -> int:
	p = subprocess.run(["cmd", "/c", "chcp"], capture_output=True)
	m = re.search(rb"(\d+)\s*$", p.stdout or b"")
	return int(m.group(1)) if m else 0


def test_prefix_applied_on_windows():
	if sys.platform == "win32":
		assert apply_utf8_command("Get-Content x").startswith(_UTF8_PREFIX)
	else:
		assert apply_utf8_command("Get-Content x") == "Get-Content x"


def test_param_headed_command_not_prefixed():
	"""param( 起头拼接后会静默改变语义（退出码仍 0）⇒ 不加前缀。"""
	if sys.platform != "win32":
		pytest.skip("Windows 专用守卫")
	assert apply_utf8_command("param($a) Write-Output $a") == "param($a) Write-Output $a"
	assert apply_utf8_command("  param($a) x") == "  param($a) x"


def test_env_can_disable(monkeypatch):
	monkeypatch.setenv("XEYO_PWSH_UTF8", "0")
	assert apply_utf8_command("Get-Content x") == "Get-Content x"


def test_empty_command_untouched():
	assert apply_utf8_command("") == ""
	assert apply_utf8_command("   ") == "   "


@win_only
def test_real_pwsh_chinese_output_is_utf8(tmp_path):
	"""真机：经 BashTool 跑中文输出——修后到达的是「目录」。"""
	tool = BashTool(cwd=str(tmp_path))
	got = tool.call(BashInput(command="Write-Output '目录'"), cwd=str(tmp_path))
	assert "目录" in got.stdout, got.stdout


@win_only
def test_without_prefix_the_bug_is_reproducible(tmp_path, monkeypatch):
	"""对照：关掉前缀时在 gb2312 控制台下复现旧症状（证明修复对着真靶）。

	卫生说明：``[Console]::OutputEncoding`` 的 setter 会**改共享控制台**的输出
	代码页（.NET 在 Windows 上的已知行为）——上一条真机用例跑完后控制台可能已是
	UTF-8 并残留。这里先显式设回 gb2312、结束时恢复原值；否则会污染后续用例
	（本测试自己就踩过：残留的 65001 让探测看到 utf-8 而误跳）。
	"""
	if sys.platform != "win32":
		pytest.skip("pwsh 编码现实只在 Windows")
	old = _console_codepage()
	subprocess.run(["cmd", "/c", "chcp", "936"], capture_output=True)
	try:
		if _default_console_encoding().lower() in ("utf-8", "utf8"):
			pytest.skip("控制台代码页未能设为 gb2312")
		monkeypatch.setenv("XEYO_PWSH_UTF8", "0")
		tool = BashTool(cwd=str(tmp_path))
		got = tool.call(BashInput(command="Write-Output '目录'"), cwd=str(tmp_path))
		assert "目录" not in got.stdout, "旧症状没复现——对照无效"
	finally:
		if old:
			subprocess.run(["cmd", "/c", "chcp", str(old)], capture_output=True)
