"""环境事实探针（``engine/env_facts``）约束测试。

守两条底线：**不给假信息**、**不阻断主循环**。
- fail-open：单项探测抛 ⇒ 该项缺席，不抛、不影响其余项；
- 口径同源：可写面必须与写路径同一道门（workspace root 外的目录不得上报——
  实测 Write 到 ``%TEMP%`` 就是被 ``write_store._canon`` 拒成 ``path_denied`` 的）；
- 有界：单项与整段都有字符上限（路径长度不可控）；
- 布尔不吞：``elevated: false`` 是有信息量的值，不能被当成"没有值"丢掉；
- 交付合同：登记为 ``pipe=state + dedup=True`` ⇒ 折进 ``world_state`` 整段、
  值不变不重发（这是"一次交付、不每边界计费"的机制依据）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import env_facts


@pytest.fixture(autouse=True)
def _clear_cache():
	env_facts._FACTS_CACHE.clear()
	yield
	env_facts._FACTS_CACHE.clear()


def test_probe_failure_drops_only_that_item(monkeypatch, tmp_path):
	"""单项探测炸掉 ⇒ 只有它缺席，其余项照常采集（绝不整块消失）。"""

	def boom():
		raise RuntimeError("probe exploded")

	monkeypatch.setattr(env_facts, "probe_tz", boom)
	monkeypatch.setattr(env_facts, "probe_shell", lambda: "pwsh 9.9.9")
	facts = env_facts.collect(str(tmp_path))
	assert facts.get("shell") == "pwsh 9.9.9"
	assert "tz" not in facts


def test_false_is_a_value_not_absence(monkeypatch):
	monkeypatch.setattr(env_facts, "probe_elevated", lambda: False)
	assert env_facts.collect("")["elevated"] == "false"


def test_values_and_block_are_bounded(monkeypatch):
	monkeypatch.setattr(env_facts, "probe_shell", lambda: "x" * 500)
	monkeypatch.setattr(env_facts, "probe_tz", lambda: "y" * 500)
	facts = env_facts.collect("")
	assert len(facts["shell"]) <= env_facts._MAX_VALUE_CHARS
	assert len(env_facts.render("")) <= env_facts._MAX_TEXT_CHARS


def test_writable_excludes_paths_outside_workspace(monkeypatch, tmp_path):
	"""回归：workspace root 之外的目录（如 ``%TEMP%``）不得上报为可写。

	口径错一次就是往注意力里塞假信息——模型会照着写，然后撞 ``path_denied``，
	正是本模块要消灭的"先撞墙才知道"。
	"""
	workspace = tmp_path / "ws"
	outside = tmp_path / "outside"
	workspace.mkdir()
	outside.mkdir()
	monkeypatch.setattr(env_facts.tempfile, "gettempdir", lambda: str(outside))
	writable = env_facts.probe_writable(str(workspace))
	assert str(outside) not in writable
	assert str(workspace) in writable


def test_scratch_dir_reported_only_when_workspace_is_writable(monkeypatch, tmp_path):
	"""草稿目录：工作区可写时报（相对路径，省字节）；不可写时报了就是假信息。"""
	workspace = tmp_path / "ws"
	workspace.mkdir()
	monkeypatch.setattr(env_facts, "probe_shell", lambda: "pwsh")
	assert env_facts.collect(str(workspace)).get("scratch") == env_facts.SCRATCH_REL
	assert env_facts.collect(str(tmp_path / "missing")).get("scratch") is None


def test_facts_id_is_stable_across_calls(monkeypatch):
	monkeypatch.setattr(env_facts, "probe_tz", lambda: "+0000 UTC")
	assert env_facts.facts_id("") == env_facts.facts_id("")


def test_registry_entry_stays_out_of_world_state_aggregation():
	"""交付合同：常驻事实行不得进 ``world_state`` 聚合。

	进聚合会让「本轮一个状态段都没产出 ⇒ 撤回上一版」恒假（撤回是"已作废的模式
	合同离开投影"的安全网）。形态与 ``time_now`` 一致：``dedup=False`` 常驻。
	"""
	from prompt.pre_llm_inject import (
		PIPE_STATE,
		T_NOW_BLOCK_REGISTRY,
		_aggregate_state_sections,
	)

	meta = T_NOW_BLOCK_REGISTRY["env_facts"]
	assert meta["pipe"] == PIPE_STATE
	assert meta["dedup"] is False
	assert _aggregate_state_sections([("env_facts", "E")]) == [("env_facts", "E")]


def test_render_is_one_line_and_drops_default_desktop(monkeypatch):
	monkeypatch.setattr(env_facts, "probe_desktop", lambda: True)
	text = env_facts.render("")
	assert "\n" not in text
	assert "desktop:" not in text
	monkeypatch.setattr(env_facts, "probe_desktop", lambda: False)
	env_facts._FACTS_CACHE.clear()
	assert "desktop: false" in env_facts.render("")
