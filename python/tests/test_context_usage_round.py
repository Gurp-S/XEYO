"""上下文行的**轮内冻结**（③）：同一用户回合内该行逐字节恒定，换回合才更新。

事故形态（2026-10-08 本会话实测）：同一回合里每个请求都把更大的数印一遍
（74k→77k→78k→83k→84k→87k），于是这行每枪都变 ⇒ 整段重渲染每次产出新片段，
同一轮里 world_state 出现两份。"一个回合内涨 5k"不构成任何决策依据，
代价却是每次都多一次差分 + 一个回声副本。

方向性都钉：
- 同键复用首枪文本（即使 usage 变了）；
- 换键（新回合）必须更新——否则变成"冻结成常量"，比不冻结更坏；
- 压缩后（:func:`forget_round`）必须重算——那时"已收纳 N 段"是新事实；
- 开关 ``XEYO_CONTEXT_USAGE_ROUND_FREEZE=0`` 回到每枪重算。
"""

from __future__ import annotations

import pytest

from prompt import context_usage


@pytest.fixture(autouse=True)
def _clear_rounds():
	context_usage.forget_round("sess_a")
	context_usage.forget_round("sess_b")
	yield
	context_usage.forget_round("sess_a")
	context_usage.forget_round("sess_b")


def _line(tokens: int, *, round_key: str, folds: dict | None = None) -> str:
	return context_usage.render(
		[{"role": "user", "content": "x"}],
		{"prompt_tokens": tokens},
		folds,
		window_tokens=1_000_000,
		round_key=round_key,
	)


def test_same_round_reuses_first_shot_text() -> None:
	first = _line(74_000, round_key="sess_a:t1")
	again = _line(87_000, round_key="sess_a:t1")
	assert first == again
	assert "74k" in first


def test_new_round_updates() -> None:
	assert "74k" in _line(74_000, round_key="sess_a:t1")
	assert "87k" in _line(87_000, round_key="sess_a:t2")


def test_compaction_releases_the_freeze() -> None:
	before = _line(74_000, round_key="sess_a:t1")
	assert "已收纳" not in before
	context_usage.forget_round("sess_a")
	after = _line(74_000, round_key="sess_a:t1", folds={"folds": 3, "last_subject": "a.py"})
	assert "早期内容已收纳 3 段" in after


def test_release_is_scoped_to_one_session() -> None:
	_line(74_000, round_key="sess_a:t1")
	other = _line(74_000, round_key="sess_b:t1")
	context_usage.forget_round("sess_a")
	assert _line(87_000, round_key="sess_b:t1") == other


def test_switch_off_means_per_shot(monkeypatch) -> None:
	monkeypatch.setenv(context_usage.ENV_ROUND_FREEZE, "0")
	assert _line(74_000, round_key="sess_a:t1") != _line(87_000, round_key="sess_a:t1")


def test_empty_round_key_means_no_freeze() -> None:
	assert _line(74_000, round_key="") != _line(87_000, round_key="")
