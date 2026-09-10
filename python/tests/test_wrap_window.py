"""D3 收尾窗口：信号语义 + 长命令后台化决策 + 收益测量。

收益口径：**收尾窗内长命令交还控制权的时间**（修复前 = promote 阈值，默认 45s；
修复后 ≈ 0s），这段时间正是用来落盘已登记产物的。窗口外行为必须字节级不变。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.budget import BudgetTracker  # noqa: E402
from engine.wrap_window import (  # noqa: E402
	clear_wrap_window,
	in_wrap_window,
	set_wrap_window,
	wrap_remaining_s,
	wrap_state,
)
from tools.bash_tool.bash_tool import BashInput, BashTool, effective_promote_ms  # noqa: E402
from tools.bash_tool.timeout_map import family_default_ms  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_wrap_window():
	clear_wrap_window()
	yield
	clear_wrap_window()


# ---------------------------------------------------------------- 信号语义


def test_default_is_inactive():
	assert in_wrap_window() is False
	assert wrap_remaining_s() is None
	assert wrap_state().active is False


def test_set_and_clear():
	set_wrap_window(True, 42.5)
	assert in_wrap_window() is True
	assert wrap_remaining_s() == 42.5
	clear_wrap_window()
	assert in_wrap_window() is False
	assert wrap_remaining_s() is None


def test_remaining_none_when_inactive_even_if_value_given():
	set_wrap_window(False, 10.0)
	assert in_wrap_window() is False
	assert wrap_remaining_s() is None


def test_budget_wall_remaining():
	budget = BudgetTracker()
	assert budget.wall_remaining_s() is None
	budget.set_wall_deadline(time.time() + 60)
	left = budget.wall_remaining_s()
	assert left is not None and 55 <= left <= 60
	budget.set_wall_deadline(time.time() - 5)
	assert budget.wall_remaining_s() == 0.0


# ---------------------------------------------------------------- 决策


def test_family_probe_shapes():
	assert family_default_ms("echo hi") is None
	assert family_default_ms("ls -la") is None
	assert family_default_ms("pip install requests") is not None
	assert family_default_ms("make -j4") is not None


def test_promote_ms_unchanged_outside_window():
	assert effective_promote_ms("pip install requests", 45_000) == 45_000
	assert effective_promote_ms("echo hi", 45_000) == 45_000


def test_promote_ms_immediate_in_window_only_for_long_family():
	set_wrap_window(True, 60.0)
	assert effective_promote_ms("pip install requests", 45_000) == 1
	assert effective_promote_ms("make -j4", 45_000) == 1
	# 短命令不受影响：收尾的落盘动作永远可用
	assert effective_promote_ms("echo hi", 45_000) == 45_000
	assert effective_promote_ms("cat out.json", 45_000) == 45_000


def test_promote_ms_unchanged_when_window_has_room():
	"""剩余时间充裕时不动：可能在窗口内跑完的长命令照常前台等结果。"""

	set_wrap_window(True, 600.0)
	assert effective_promote_ms("pip install requests", 45_000) == 45_000
	set_wrap_window(True, 120.0)  # 闸门边界（>= 视为充裕）
	assert effective_promote_ms("pip install requests", 45_000) == 45_000
	set_wrap_window(True, 119.9)
	assert effective_promote_ms("pip install requests", 45_000) == 1


def test_promote_ms_immediate_when_remaining_unknown():
	"""配额型收尾窗（无墙钟死线 → 剩余未知）同样短：立即交还控制权。"""

	set_wrap_window(True, None)
	assert effective_promote_ms("pip install requests", 45_000) == 1


def test_promote_ms_zero_stays_zero():
	set_wrap_window(True, 30.0)
	assert effective_promote_ms("pip install requests", 0) == 0


# ---------------------------------------------------------------- 收益测量（端到端）


def _family_cmd() -> str:
	"""一个确定命中「长命令族」且能快速结束的真实命令（pytest 家族）。"""

	return f'"{sys.executable}" -m pytest --version'


def test_benefit_wrap_window_returns_control_fast(tmp_path):
	"""收益测量：窗口外等命令跑完；窗口内立即交还控制权（后台 job）。

	窗口外 elapsed ≈ 命令启动耗时（pytest --version ~1s）；
	窗口内 elapsed ≈ 0（promote_ms=1 → 立刻后台化），模型拿回时间用于落盘。
	"""

	assert family_default_ms(_family_cmd()) is not None, "前置：该命令须命中长命令族"

	os.environ["XEYO_BASH_PROMOTE_MS"] = "20000"
	try:
		tool = BashTool(cwd=str(tmp_path))
		inp = BashInput(command=_family_cmd(), timeout_ms=30_000)

		t0 = time.monotonic()
		out_before = tool.call(inp)
		elapsed_before = time.monotonic() - t0
		assert not out_before.background_task_id  # 窗口外：前台跑完

		set_wrap_window(True, 60.0)
		t1 = time.monotonic()
		out_in = tool.call(inp)
		elapsed_in = time.monotonic() - t1

		assert out_in.background_task_id, "窗口内应后台化并交还控制权"
		assert elapsed_in < elapsed_before or elapsed_in < 0.5
		print(
			f"\n[收益] 收尾窗内长命令交还控制权: "
			f"{elapsed_before:.2f}s → {elapsed_in:.2f}s"
		)
	finally:
		os.environ.pop("XEYO_BASH_PROMOTE_MS", None)


def _emitted_strings(module_path: Path) -> list[str]:
	"""模块里**会输出给模型**的字符串字面量（跳过文档字符串与注释）。"""

	import ast

	tree = ast.parse(module_path.read_text(encoding="utf-8"))
	docstrings: set[int] = set()
	for node in ast.walk(tree):
		if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
			body = getattr(node, "body", [])
			if (
				body
				and isinstance(body[0], ast.Expr)
				and isinstance(body[0].value, ast.Constant)
				and isinstance(body[0].value.value, str)
			):
				docstrings.add(id(body[0].value))
	return [
		node.value
		for node in ast.walk(tree)
		if isinstance(node, ast.Constant)
		and isinstance(node.value, str)
		and id(node) not in docstrings
	]


def test_no_wrap_branch_in_engine_source():
	"""红线自查：收尾窗信号不得成为评测特判；输出的文本不得含劝告措辞。"""

	module = Path(__file__).resolve().parents[1] / "engine" / "wrap_window.py"
	source = module.read_text(encoding="utf-8")
	assert "BENCH_MINIMAL" not in source
	assert "is_benchmark" not in source
	for text in _emitted_strings(module):
		for banned in ("请", "应该", "建议", "务必", "记得", "优先"):
			assert banned not in text
