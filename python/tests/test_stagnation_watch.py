import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.budget import BudgetTracker
from engine.stagnation_watch import (
	NO_CONTRACT_CALLS,
	NUDGE_TURNS,
	RUBBER_STAMP_ITEMS,
	STUCK_CALLS,
	THRASH_TIMES,
	StagnationWatch,
	clear_stall_advice,
	current_stall_advice,
	stagnation_enabled,
)
import os

import pytest


def _todo(tid: str, status: str, content: str = "a") -> dict:
	return {"todos": [{"id": tid, "content": content, "activeForm": "a", "status": status}]}


@pytest.fixture(autouse=True)
def _bench_env(monkeypatch):
	"""测试默认开启 bench 档案（watch 启用前提）；用例内可再覆盖。"""
	monkeypatch.setenv("XEYO_BENCH_MINIMAL", "1")
	monkeypatch.delenv("XEYO_TODO_CONTRACT", raising=False)
	clear_stall_advice()
	yield
	clear_stall_advice()


# ====== 开关语义 ======

def test_disabled_without_bench_profile(monkeypatch):
	"""非 bench 档案：observe 直接返回，永不产提醒（GUI 零影响）。"""
	monkeypatch.delenv("XEYO_BENCH_MINIMAL", raising=False)
	w = StagnationWatch(BudgetTracker(max_turns=999, max_tool_calling=9999))
	for _ in range(NO_CONTRACT_CALLS + 5):
		w.observe("Bash", {"command": "true"})
	assert current_stall_advice() == ""


def test_kill_switch(monkeypatch):
	"""XEYO_TODO_CONTRACT=0 一键关闭（应急回滚开关）。"""
	monkeypatch.setenv("XEYO_TODO_CONTRACT", "0")
	assert stagnation_enabled() is False


# ====== 信号 1：无契约启动 ======

def test_no_contract_fires_at_wall_half(monkeypatch):
	"""预算过半仍无 TodoWrite → 一次性提醒。"""
	b = BudgetTracker(max_turns=999, max_tool_calling=9999)
	monkeypatch.setattr(b, "wall_deadline_ts", 1000.0, raising=False)
	monkeypatch.setattr(b, "wall_started_ts", 0.0, raising=False)
	w = StagnationWatch(b)
	monkeypatch.setattr("engine.stagnation_watch._now", lambda: 600.0)  # 60% > 50%
	w.observe("Bash", {"command": "true"})
	assert "无 todo 清单" in current_stall_advice()
	# 一次性：再次触发不重复发布新内容（fired 集合去重）。
	w.observe("Bash", {"command": "true"})
	assert current_stall_advice().count("无 todo 清单") == 1


def test_contract_written_never_fires_no_contract():
	"""一旦写过清单，无契约信号永久熄火（回退阈值路径）。"""
	w = StagnationWatch(None)
	for _ in range(5):  # 未达回退阈值：只有 nudge，无 no_contract 话术
		w.observe("Bash", {"command": "true"})
	assert "无 todo 清单" not in current_stall_advice()
	w.observe("TodoWrite", _todo("1", "pending"))
	for _ in range(NO_CONTRACT_CALLS + 5):
		w.observe("Bash", {"command": "true"})
	assert "无 todo 清单" not in current_stall_advice()


# ====== 信号 2：卡死（双条件） ======

def test_stuck_requires_calls_and_wall(monkeypatch):
	"""工具调用数够但墙钟进度不足 → 不触发（宁漏勿误）。"""
	b = BudgetTracker(max_turns=999, max_tool_calling=9999)
	monkeypatch.setattr(b, "wall_deadline_ts", 1000.0, raising=False)
	monkeypatch.setattr(b, "wall_started_ts", 0.0, raising=False)
	w = StagnationWatch(b)
	w.observe("TodoWrite", _todo("1", "in_progress"))
	monkeypatch.setattr("engine.stagnation_watch._now", lambda: 100.0)  # 10% < 30%
	for _ in range(STUCK_CALLS + 5):
		w.observe("Bash", {"command": "true"})
	assert current_stall_advice() == ""


# ====== 信号 3：震荡（completed→重开） ======

def test_thrash_fires_on_repeated_reopen():
	w = StagnationWatch(None)
	w.observe("TodoWrite", _todo("1", "completed"))
	w.observe("TodoWrite", _todo("1", "in_progress"))
	assert current_stall_advice() == ""  # 第 1 次重开：安静
	w.observe("TodoWrite", _todo("1", "completed"))
	w.observe("TodoWrite", _todo("1", "pending"))  # 第 2 次重开：触发
	assert "反复完成又重开" in current_stall_advice()


# ====== 信号 4：走过场（创建即完成） ======

def test_rubber_stamp_fires_on_instant_complete():
	w = StagnationWatch(None)
	for i in range(RUBBER_STAMP_ITEMS):
		w.observe("TodoWrite", _todo(str(i), "completed"))
	assert "创建即完成" in current_stall_advice()


def test_normal_completion_never_fires():
	"""先 pending 后 completed（有中间状态）不算走过场。"""
	w = StagnationWatch(None)
	for i in range(RUBBER_STAMP_ITEMS + 2):
		w.observe("TodoWrite", _todo(str(i), "pending"))
		w.observe("Bash", {"command": "true"})
		w.observe("TodoWrite", _todo(str(i), "completed"))
	assert current_stall_advice() == ""


# ====== 契约 nudge（recency 窗口）======

def test_nudge_persists_until_contract_or_signal():
	"""窗口内开始注入；槽位持久=之后每轮请求都注入；契约建立即清空。"""
	w = StagnationWatch(None)
	w.observe("Bash", {"command": "true"})
	assert "工作契约尚未建立" in current_stall_advice()
	for _ in range(NUDGE_TURNS + 3):
		w.observe("Bash", {"command": "true"})
	assert "工作契约尚未建立" in current_stall_advice()  # 持久，直到契约/信号
	w.observe("TodoWrite", _todo("1", "in_progress"))
	assert "工作契约尚未建立" not in current_stall_advice()


def test_nudge_cleared_once_contract_written():
	"""契约建立 → 残留 nudge 立即清空。"""
	w = StagnationWatch(None)
	w.observe("Bash", {"command": "true"})
	assert "工作契约尚未建立" in current_stall_advice()
	w.observe("TodoWrite", _todo("1", "in_progress"))
	assert "工作契约尚未建立" not in current_stall_advice()


def test_nudge_does_not_suppress_later_signals():
	"""nudge 窗口后触发的 no_contract 不被 nudge 顶掉（信号优先于提醒）。"""
	w = StagnationWatch(None)
	for _ in range(NUDGE_TURNS):
		w.observe("Bash", {"command": "true"})
	for _ in range(NO_CONTRACT_CALLS):
		w.observe("Bash", {"command": "true"})
	assert "无 todo 清单" in current_stall_advice()
