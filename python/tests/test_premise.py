"""`assert_premise` 的形状契约（#15 / P1）。"""

from __future__ import annotations

import pytest

from tests.premise import assert_premise


def test_passing_premise_is_silent() -> None:
	"""成立就什么都不发生（不打印、不改控制流）。"""
	assert assert_premise(True, "永远成立") is None


def test_failing_premise_says_it_is_a_premise() -> None:
	"""失败消息必须自报家门：第一眼就能分清"产品坏了"还是"我假设错了"。"""
	with pytest.raises(AssertionError) as exc:
		assert_premise(False, "该 env 本应漂移工具面")
	msg = str(exc.value)
	assert msg.startswith("前提失败："), msg
	assert "该 env 本应漂移工具面" in msg


def test_premise_treats_falsy_as_failure() -> None:
	"""空串/0/None 都算不成立（不能只判 `is False`）。"""
	for falsy in ("", 0, None, [], {}):
		with pytest.raises(AssertionError):
			assert_premise(falsy, "falsy 一律不成立")
