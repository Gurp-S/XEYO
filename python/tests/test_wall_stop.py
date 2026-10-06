import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from engine.budget import BudgetTracker, wall_hard_stop_from_env


# ====== R1'：墙钟硬停 ======

def test_wall_stop_default_unarmed_no_hard_stop():
	"""默认（不武装）：墙钟走尽只播报提醒，grace 不因墙钟启动 → 不硬停。"""
	b = BudgetTracker(max_turns=100)
	b.set_wall_deadline(100.0, started_ts=0.0)
	# 未调用 arm_wall_stop → wall_hard_stop=False
	assert b.wall_hard_stop is False
	assert b.check_wall_deadline(now=50.0) is None  # 50% 未到阈值不播
	assert b.check_wall_deadline(now=90.0) is not None  # 90% 播报(既有语义)
	# 走尽 100%
	b.check_wall_deadline(now=1000.0)
	assert b.grace_started is False  # 不因墙钟进 grace
	assert b.prepare_next_turn() is True  # 回合配额仍在 → 继续


def test_wall_stop_armed_triggers_grace_at_100():
	"""显式武装：100% 走尽 → 进入共享收尾窗口（grace），回合不归零也不继续无限。"""
	b = BudgetTracker(max_turns=100)
	b.set_wall_deadline(100.0, started_ts=0.0)
	b.arm_wall_stop(True)
	assert b.check_wall_deadline(now=99.0) is not None  # 99% 先播 90% 提醒(既有)
	b.check_wall_deadline(now=100.0)
	assert b.grace_started is True
	assert b.grace_reason == "wall"


def test_wall_stop_grace_exhausts_to_false_with_wall_reason():
	"""武装 + 100% → grace 3 轮后 prepare_next_turn 返回 False,hard_stop_reason=wall。"""
	b = BudgetTracker(max_turns=100)
	b.set_wall_deadline(100.0, started_ts=0.0)
	b.arm_wall_stop(True)
	b.check_wall_deadline(now=100.0)  # 触发 grace
	# MAX_GRACE_TURNS=3：前 3 轮放行，之后 False
	results = []
	for _ in range(5):
		results.append(b.prepare_next_turn())
		if results[-1]:
			b.begin_turn()
	assert results[:3] == [True, True, True]
	assert results[3] is False
	assert b.hard_stop_reason == "wall"


def test_wall_stop_unarmed_100_percent_no_grace():
	"""不武装：100% 走尽也不进 grace；是否停止只由回合预算(max_turns grace)决定。"""
	b = BudgetTracker(max_turns=2)
	b.set_wall_deadline(100.0, started_ts=0.0)
	# 不 arm
	b.check_wall_deadline(now=200.0)
	assert b.grace_started is False  # 墙钟没触发 grace
	# 回合预算走到上限：先开 grace（3 轮），全用完才 False——与墙钟无关。
	for _ in range(2):
		assert b.prepare_next_turn() is True
		b.begin_turn()
	assert b.prepare_next_turn() is True  # max_turns grace 开始,仍放行
	assert b.grace_reason == "max_turns"


def test_wall_stop_env_default_off(monkeypatch):
	monkeypatch.delenv("XEYO_WALL_HARD_STOP", raising=False)
	assert wall_hard_stop_from_env() is False


def test_wall_stop_env_opt_in(monkeypatch):
	monkeypatch.setenv("XEYO_WALL_HARD_STOP", "1")
	assert wall_hard_stop_from_env() is True


def test_wall_stop_arm_none_follows_env(monkeypatch):
	monkeypatch.setenv("XEYO_WALL_HARD_STOP", "1")
	b = BudgetTracker()
	b.arm_wall_stop(None)
	assert b.wall_hard_stop is True
	monkeypatch.setenv("XEYO_WALL_HARD_STOP", "0")
	b2 = BudgetTracker()
	b2.arm_wall_stop(None)
	assert b2.wall_hard_stop is False


def test_wall_notice_queued_on_grace():
	"""进入 wall grace 时排队一次性收尾提醒（consume 一次后消失）。"""
	b = BudgetTracker(max_turns=100)
	b.set_wall_deadline(100.0, started_ts=0.0)
	b.arm_wall_stop(True)
	b.check_wall_deadline(now=100.0)
	notice = b.consume_runtime_notice()
	assert notice and "时间预算已到上限" in notice
	assert b.consume_runtime_notice() is None or "时间预算已到上限" not in (
		b.consume_runtime_notice() or ""
	)


# ====== 80%/90% 播报的消费端（2026-10-02 回归）====================
#
# 事故形态：``check_wall_deadline`` 把播报**正文**传给了只认 reason 名的私有
# ``_queue_notice``（reason 白名单之外的字符串直接 ``return``）⇒ 播报从未进入
# ``_pending_notices``，``prepare_next_turn`` 又丢弃返回值 ⇒ 整条时间感通道是死的。
# 旧用例只断言 producer 返回值非空，所以整轮测试全绿也照不出。
# 规则：播报类判据必须落在**消费点**（``consume_runtime_notice``），不落在生成点。

def test_wall_80_notice_reaches_runtime_notice_channel():
	"""经生产入口 prepare_next_turn：越过 80% ⇒ 播报能在下一轮被模型读到。"""
	now = time.time()
	b = BudgetTracker(max_turns=100)
	b.set_wall_deadline(now + 15.0, started_ts=now - 85.0)  # 总 100s，已用 85s
	assert b.prepare_next_turn() is True
	notice = b.consume_runtime_notice()
	assert notice and "时间预算已用 80%" in notice


def test_wall_90_notice_reaches_runtime_notice_channel():
	"""越过 90% ⇒ 90% 播报同样走 runtime notice 通道（与 USD 水位同口径）。"""
	now = time.time()
	b = BudgetTracker(max_turns=100)
	b.set_wall_deadline(now + 5.0, started_ts=now - 95.0)  # 总 100s，已用 95s
	assert b.prepare_next_turn() is True
	notice = b.consume_runtime_notice()
	assert notice and "时间预算已用 90%" in notice


def test_wall_threshold_notice_is_one_shot():
	"""同一阈值只播一次：第二次检查不得重复排队。"""
	b = BudgetTracker(max_turns=100)
	b.set_wall_deadline(100.0, started_ts=0.0)
	assert b.check_wall_deadline(now=85.0) is not None
	assert b.consume_runtime_notice() == "时间预算已用 80%，剩余约 0 分钟。"
	assert b.check_wall_deadline(now=86.0) is None
	assert b.consume_runtime_notice() is None
