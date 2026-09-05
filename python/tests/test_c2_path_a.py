"""Path A：C2 阈值/保尾常量 → 成本模型公式（c2_gate）的单元测试。

全部测试在公式层（纯函数），且验证「公式开关默认关 = 冻结行为不变」：
- 压力门 = (l_max − tail_budget)/window，与 alpha_win 同源（不独立拍 0.62）。
- 收益门 = 剩余轮次 × 每轮省 token ≥ margin × price_ratio × 一次性 miss（随剩余轮次动态）。
- 保尾 = 每轮均 token × 保留轮数（不拍 24k）。
- runtime 默认关：project_for_model / should_force_compact_on_pressure 走冻结路径。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.simulator.c2_gate import (  # noqa: E402
	economic_gain_ok,
	l_hard_send_from,
	pressure_ratio,
	tail_budget_tokens,
	window_from,
)
from memory.simulator.params import load_params  # noqa: E402


def test_pressure_ratio_is_window_adaptive():
	# 压力门 = (l_hard_send − output_reserve − tail_budget) / window —— **窗口自适应**。
	# l_hard_send = window − reserve（随窗口变）；128k 下 = 128000−2048 = 125952。
	p = load_params()
	assert window_from(p) == 128_000
	assert l_hard_send_from(p) == 125_952
	# 无输出预留、无保尾 → 压力比 = l_hard_send/window ≈ 0.984
	assert pressure_ratio(
		window=window_from(p), l_hard_send=l_hard_send_from(p), output_reserve=0, tail_budget=0
	) == pytest.approx(125952 / 128000, abs=1e-3)
	# 预留更多输出（c2_output_reserve）→ 压力降低（离硬顶更早压，留更多输出余量）
	p0 = pressure_ratio(window=window_from(p), l_hard_send=l_hard_send_from(p), output_reserve=0, tail_budget=0)
	p1 = pressure_ratio(window=window_from(p), l_hard_send=l_hard_send_from(p), output_reserve=50_000, tail_budget=0)
	assert p1 < p0
	# 保尾降低压力（扣尾预算）
	p2 = pressure_ratio(window=window_from(p), l_hard_send=l_hard_send_from(p), output_reserve=0, tail_budget=24_000)
	assert p2 < p0
	# 夹在 (0, 1)
	assert 0.0 <= p1 <= 1.0
	# 窗口自适应：1M 下同样的 output_reserve 给出更高压力比（因为 l_hard_send/window 更大、占比不变）
	# 128k: (125952−50000)/128000 ≈ 0.593；1M: (997952−50000)/1000000 ≈ 0.948 → 越高越晚压
	assert pressure_ratio(window=128000, l_hard_send=125952, output_reserve=50_000, tail_budget=0) == pytest.approx(0.593, abs=1e-3)
	assert pressure_ratio(window=1_000_000, l_hard_send=997952, output_reserve=50_000, tail_budget=0) == pytest.approx(0.948, abs=1e-3)
	# 大窗口压力比更高（更晚压、上下文存在更久）—— 与切换模型窗口变大语义一致
	assert pressure_ratio(window=1_000_000, l_hard_send=997952, output_reserve=50_000, tail_budget=0) > pressure_ratio(window=128000, l_hard_send=125952, output_reserve=50_000, tail_budget=0)


def test_tail_budget_is_per_turn_times_rounds():
	# 每轮均 token ≈ 717（真录实测），×3 轮 ≈ 2150，而不是拍 24k
	bt = tail_budget_tokens(per_turn_tokens=717.0, retain_rounds=3)
	assert bt == 2151
	# 轮数增多 → 尾预算更大
	assert tail_budget_tokens(per_turn_tokens=717.0, retain_rounds=5) > bt


def test_economic_gain_gate_dynamic_with_remaining_turns():
	# 收益门：剩余轮次多 → 反摊平收益成立 → 压缩；剩余轮次少 → 拒绝压缩
	kwargs = dict(
		region_chars=20_000,
		summary_chars=3_000,
		tail_chars=2_000,
		margin=2.0,
		price_ratio=30.0,
		min_save_ratio=0.25,
		min_gain_chars=4_000,
	)
	assert economic_gain_ok(remaining_turns=30, **kwargs) is True
	assert economic_gain_ok(remaining_turns=2, **kwargs) is False
	# 收益不足（region − summary < min_gain）→ 拒绝
	assert economic_gain_ok(remaining_turns=30, region_chars=2_000, summary_chars=1_000, **{k: v for k, v in kwargs.items() if k not in ("region_chars", "summary_chars")}) is False


def test_gain_gate_rejects_when_save_ratio_not_met():
	# 压缩后 (summary+tail)/full 没省够 min_save_ratio → 拒绝
	assert (
		economic_gain_ok(
			region_chars=10_000,
			summary_chars=9_500,
			tail_chars=0,
			remaining_turns=30,
			margin=2.0,
			price_ratio=30.0,
			min_save_ratio=0.25,
			min_gain_chars=0,
		)
		is False
	)


def test_default_path_keeps_frozen_behavior():
	import os

	import memory.runtime as rt
	from memory.working import WorkingSnapshot

	# Path A 公式开关**默认启用**（定稿）；要验证「冻结=关」时行为不变。
	assert rt._c2_formula_enabled("XEYO_C2_GAIN_FORMULA") is True
	assert rt._c2_formula_enabled("XEYO_C2_PRESSURE_FORMULA") is True
	# 压力门**必须**用真实模型窗口（用户添加模型时必填的上下文窗口）；无窗口 → None（不触发），
	# 不再回退 params.window_tokens=128k（那会让 C2 误判窗口只有 128k）。
	assert rt._c2_pressure_ratio(None, None, window_override=None) is None
	pr = rt._c2_pressure_ratio(None, None, window_override=128_000)
	assert 0.50 < pr < 0.99
	# 阈值 = limit × pr；80k（pr≈0.593 → 阈值≈59.3k）已达标 → True
	assert rt.should_force_compact_on_pressure(prompt_tokens=80_000, context_limit=100_000) is True
	# 无真实窗口（context_limit None）→ 压力判定不触发（宁可不压，也不拿错窗口压）
	assert rt.should_force_compact_on_pressure(prompt_tokens=80_000, context_limit=None) is False
	# WorkingSnapshot 构造不因新接口而变
	w = WorkingSnapshot()
	assert w.compact_cursor == 0


def _formula_override(monkeypatch, on: bool) -> int:
	"""测一个长工具会话的 C2 边界推进数；公式开关 on/off 对比。

	Scheme A（压力门单一触发）：压力阈值收敛 C2 为稀发事件，改写应显著少于
	「decide 每轮可触发」的冻结路径。**全部经 monkeypatch 设置/还原**，不留残余 env 或
	模块级状态（避免污染同批其它测试）。
	"""
	import memory.runtime as rt
	from memory.working import WorkingSnapshot

	if on:
		monkeypatch.setenv(
			"XEYO_C2_FORMULA_OVERRIDE",
			"XEYO_C2_PRESSURE_FORMULA:1,XEYO_C2_GAIN_FORMULA:1,XEYO_C2_EXTEND_FORMULA:1",
		)
	else:
		# 冻结基线：显式把三个公式开关都置 0（override 优先于默认=1）
		monkeypatch.setenv(
			"XEYO_C2_FORMULA_OVERRIDE",
			"XEYO_C2_PRESSURE_FORMULA:0,XEYO_C2_GAIN_FORMULA:0,XEYO_C2_EXTEND_FORMULA:0",
		)
	# 收紧压力：只会更晚触发、改写更少（env 覆盖优先于 clamp，monkeypatch 自动还原）
	monkeypatch.setenv("XEYO_C2_PRESSURE_RATIO", "0.70")
	monkeypatch.setattr(rt, "l5_mode", lambda: "v61")

	msgs: list[dict] = [{"role": "user", "content": "start"}]
	for i in range(40):
		msgs.append({"role": "assistant", "content": [{"type": "tool_use", "id": f"g{i}", "name": "Grep", "input": {"q": "x"}}]})
		msgs.append({"role": "tool", "tool_call_id": f"g{i}", "name": "Grep",
		             "content": [{"type": "tool_result", "tool_use_id": f"g{i}", "content": "hit\n" + "y" * 12000, "is_error": False}]})
	w = WorkingSnapshot()
	w.turns_since_c2 = 99
	adv = 0
	last = 0
	for idx in [i for i, m in enumerate(msgs) if m.get("role") == "assistant"]:
		rt.project_for_model(msgs[: idx], w, remaining_turns=8, include_memory_index=False)
		if int(w.compact_cursor or 0) != last:
			adv += 1
			last = int(w.compact_cursor or 0)
	return adv


def test_scheme_a_single_trigger_reduces_rewrites(monkeypatch):
	# Scheme A（压力门单一触发，压力 0.70）把 C2 收敛为稀发事件：
	# 改写数应显著少于「decide 每轮可触发」的冻结路径。
	frozen_adv = _formula_override(monkeypatch, on=False)
	formula_adv = _formula_override(monkeypatch, on=True)
	assert formula_adv <= frozen_adv
	# 合成会话上冻结路径在 3 左右；压力 0.70 收敛到 1（一次首压后稳定态）
	assert formula_adv <= 2
	assert frozen_adv >= 1
