"""`slow` 标记必须真的换来 300s 预算——pytest-timeout 只认 `timeout` 标记。

不翻译的后果不是"某条红"，而是整轮会话被 thread 法杀掉：2026-09-25 全量跑到 23%
就被 `test_budget.py::test_submit_without_limit_is_unchanged`（单例 ~98s，每轮都跑
真实 project_for_model→simulator.decide）中止，后面的用例一条没跑。
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.slow
def test_slow_marker_translates_into_a_timeout_allowance(request):
	"""本用例自己标了 slow，self-check 它同时带上了 ≥300s 的 timeout。"""
	marker = request.node.get_closest_marker("timeout")
	assert marker is not None, (
		"@pytest.mark.slow 没有被翻译成 timeout 标记：全局 60s 会杀掉整轮会话"
	)
	assert marker.args and marker.args[0] >= 300, marker.args


def test_plain_tests_keep_the_global_timeout(request):
	"""没标 slow 就不许被抬高预算，否则 long-run 检测整体失效。"""
	assert request.node.get_closest_marker("timeout") is None


def test_the_known_long_test_still_carries_the_marker():
	"""标记一旦被删，全量套件会再次在中途中止——这里先一步报出来。"""
	lines = (Path(__file__).parent / "test_budget.py").read_text(encoding="utf-8").splitlines()
	target = "async def test_submit_without_limit_is_unchanged"
	hits = [k for k, line in enumerate(lines) if line.startswith(target)]
	if not hits:
		pytest.fail(f"test_budget.py 里找不到 {target}")
	i = hits[0]
	decorators = []
	k = i - 1
	while k >= 0 and lines[k].lstrip().startswith("@"):
		decorators.append(lines[k].strip())
		k -= 1
	assert "@pytest.mark.slow" in decorators, decorators
