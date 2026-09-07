"""#15 命令族默认超时映射 单元测试（纯查表）。

判定：pip/npm/编译/系统包管理 → 长于全局 120s 的家族默认；无命中 → None（回落全局）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.bash_tool.timeout_map import (
	_FAMILY_TIMEOUTS_MS,
	base_command_of,
	family_default_ms,
)


def test_pip_family_gets_long_default():
	assert family_default_ms("pip install torch") == 300_000
	assert family_default_ms("pip3 install -r requirements.txt") == 300_000


def test_node_family():
	assert family_default_ms("npm ci") == 240_000
	assert family_default_ms("yarn install") == 240_000


def test_compile_family():
	assert family_default_ms("make -j4") == 300_000
	assert family_default_ms("cargo build --release") == 420_000
	assert family_default_ms("gcc main.c -o main") == 300_000


def test_system_pkg_family():
	assert family_default_ms("apt-get update && apt-get install -y gcc") == 300_000


def test_python_m_prefix_fallback():
	assert family_default_ms("python -m pip install pandas") == 300_000


def test_unknown_family_falls_back_to_none():
	assert family_default_ms("ls -la") is None
	assert family_default_ms("echo hi") is None
	assert family_default_ms("") is None


def test_base_command_of_handles_paths_and_case():
	assert base_command_of("C:\\Python\\pip.exe install x") == "pip.exe"
	assert base_command_of("/usr/bin/pip3 --version") == "pip3"
	assert base_command_of("  Ls -la ") == "ls"


def test_all_family_defaults_exceed_legacy_120s():
	"""#15 契约：家族默认必须长于一刀切 120s，否则映射无意义。"""
	for name, ms in _FAMILY_TIMEOUTS_MS.items():
		assert ms > 120_000, f"{name} 默认 {ms} 未超过 120s 一刀切"
