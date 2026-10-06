"""Bash 输出里的 CSI 转义：剥噪声、不碰正文。

取证（2026-10-03 会话 sess_mur8ilhk_zz7jt9 行 3 / 行 9）：PowerShell 的 SGR 序列
原样进了模型可见文本， ``\\x1b[31;1m`` 把错误消息切碎、把表头渲染成不可解析的碎串。

两头都校：
- 正向——CSI 不进模型可见输出（含真实产物文本、经 ``_decode`` 缝、真机 pwsh 跑一遍）；
- 反向——无转义的文本逐字不变、OSC 内的 URL 不丢、孤立 ESC 不吞（剥它们=丢正文）。

编码档位（UTF-8 优先把 GBK 双字节对静默解成乱码）不在此刀内，见文末 xfail。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.bash_tool.ansi import strip_ansi
from tools.bash_tool.runner import _decode, build_shell_argv, run_command

# 真实产物：会话行 3（pwsh 错误流，Exit code 1）
_REAL_ERROR = (
	"\x1b[31;1mGet-ChildItem: \x1b[31;1m找不到路径“D:\\lea\\XenYon code\\%USERPROFILE%\\Desktop”，"
	"因为该路径不存在。\x1b[0m"
)

# 真实产物：会话行 9（Get-ChildItem 的彩色表头）
_REAL_TABLE = (
	"[shell: pwsh 7.6.6]\n\n    目录:C:\\Users\\48522\\Desktop\n\n"
	"\x1b[32;1mMode   \x1b[0m\x1b[32;1m              LastWriteTime\x1b[0m"
	"\x1b[32;1m         Length\x1b[0m\x1b[32;1m Name\x1b[0m\n"
	"\x1b[32;1m----   \x1b[0m \x1b[32;1m             -------------\x1b[0m"
)


def test_strip_real_error_keeps_body() -> None:
	out = strip_ansi(_REAL_ERROR)
	assert "\x1b" not in out
	assert "Get-ChildItem" in out
	assert "找不到路径" in out


def test_strip_real_table_keeps_columns() -> None:
	out = strip_ansi(_REAL_TABLE)
	assert "\x1b" not in out
	assert "LastWriteTime" in out
	assert "Name" in out
	assert "C:\\Users\\48522\\Desktop" in out


def test_no_escape_input_is_byte_identical() -> None:
	# 反向：没有 ESC 时不得有任何改动，否则就是「把重复修成丢失」。
	for text in (
		"hello [31m world\n目录",
		"echo [0;32m\n",
		"",
		"rg --color=always pattern\n",
	):
		assert strip_ansi(text) == text


def test_osc_hyperlink_target_survives() -> None:
	# 反向：OSC 的目标 URL 只存在于序列内部，剥它=丢正文。
	text = "看这里 \x1b]8;;https://example.com/deep/a\x07链接\x1b]8;;\x07结束"
	out = strip_ansi(text)
	assert "https://example.com/deep/a" in out
	assert "链接" in out


def test_lone_escape_survives() -> None:
	assert strip_ansi("a\x1bb") == "a\x1bb"


def test_decode_seam_strips() -> None:
	assert _decode(b"\x1b[31mred\x1b[0m\n") == "red\n"
	assert _decode(b"plain\n") == "plain\n"


def _pwsh_available() -> bool:
	if os.name != "nt":
		return False
	_exe, kind = build_shell_argv("")
	return kind == "pwsh"


def test_live_pwsh_output_has_no_escape() -> None:
	"""真机两趟：先证刺激到达（原始字节里确有 ESC），再证引擎侧已剥干净。"""
	if not _pwsh_available():
		pytest.skip("本机没有 pwsh 7，彩色表头这一族无法复现")
	cmd = 'Get-ChildItem | Out-String; Write-Host "`e[31mlive-marker`e[0m"'
	argv, _kind = build_shell_argv(cmd)
	raw = subprocess.run([*argv, cmd], capture_output=True, timeout=60)
	if b"\x1b" not in raw.stdout:
		pytest.skip("pwsh 这次没吐 CSI，刺激未到达，本档不成立")
	res = run_command(cmd, cwd=str(Path(__file__).resolve().parents[1]), timeout_ms=60_000)
	assert res.code == 0
	assert "\x1b" not in res.stdout
	assert "live-marker" in res.stdout
	assert "Mode" in res.stdout


@pytest.mark.xfail(
	strict=True,
	reason=(
		"UTF-8 优先链会把 GBK 双字节对静默解成乱码：``目录`` 的 GBK 字节 C4BF C2BC 恰是"
		"合法 UTF-8（→ U+013F U+00BC ``Ŀ¼``），回退分支永远走不到。归属=宿主 Bash 输出"
		"编码档位（tools/bash_tool/runner.py 的 _decode + 子进程 [Console]::OutputEncoding），"
		"源头修法要改每条命令的 shell 调用面、会影响原生 cp936 工具的字节透传，2026-10-03 "
		"未裁定。修好后本档必须删。"
	),
)
def test_gbk_cp_pair_silently_decodes_as_utf8() -> None:
	assert _decode("目录".encode("gbk")) == "目录"
