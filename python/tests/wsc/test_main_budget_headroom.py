"""主链上限**按固定段未用量浮动**的记账守卫。

要治的事故形态（实测两批真实语料 51 会话）：固定段一个会话都没超自己的 1800
（**0/51**），主链却被判超限（**19/51**，最大超 913 tok），而**总热层 50/51 都在
``hot_budget_tokens=3000`` 以内**（median 1473 / p90 2183）。⇒ 那些超限是静态
1800/1200 拆分造成的**假超支**。

假超支为什么危险，不只是数字难看：它的"症状"和真超支一模一样，于是招来的修法是给
主链装裁剪器 —— 而主链里最大的是 ``[DECISIONS]``（**带错误签名的剪枝卡**）与
``[PRUNED]``（**句柄索引**）。拿删除 WSC 招牌信息与可恢复性去修一个记账口径，是
本末倒置。本文件钉住三件事：浮动确实发生、浮动**不新创预算**、真超限时溢出仍要报。
"""

from __future__ import annotations

from synaptic.assemble import (
	H_CONSTRAINTS,
	H_DECISIONS,
	H_MAIN,
	H_PRUNED,
	H_REQUESTS,
)
from synaptic.budget import apply_hot_budgets
from synaptic.graph import build_graph
from synaptic.types import WscParams
from tests.wsc._fixtures import msg_asst_text, msg_user


def _apply(fixed_text: str, main_text: str, *, fixed_cap=1_800, main_cap=1_200):
	msgs = [msg_user("这是一个足够长的用户问题内容"), msg_asst_text("ok")]
	graph = build_graph(msgs)
	params = WscParams(
		fixed_segment_budget_tokens=fixed_cap,
		main_segment_budget_tokens=main_cap,
		hot_budget_tokens=fixed_cap + main_cap,
	)
	_out, audit = apply_hot_budgets(
		{
			H_CONSTRAINTS: [("pin:0", fixed_text)],
			H_REQUESTS: [("req:0", "用户原话")],
			H_MAIN: [(f"main:{i}", main_text) for i in range(6)],
		},
		params,
		graph=graph,
		region_end=len(msgs),
		request_header=H_REQUESTS,
		request_skip=frozenset(),
		user_nodes=(0,),
		fixed_headers=(H_CONSTRAINTS, H_REQUESTS),
		main_headers=(H_MAIN,),
	)
	return audit


def test_unused_fixed_headroom_flows_to_main_chain() -> None:
	"""固定段没用完 ⇒ 主链的**生效**上限抬高，假超限归零。"""
	short_fixed = "目标：修超时"  # 远小于 1800
	audit = _apply(short_fixed, "决策记录 " * 120)  # 主链明显超过声明的 1200
	assert audit.main_tokens > audit.main_budget_tokens, "夹具没造出'主链超声明值'的形态"
	assert audit.main_effective_cap_tokens > audit.main_budget_tokens
	assert audit.main_headroom_from_fixed_tokens > 0
	assert audit.main_overflow_tokens == 0, (
		f"固定段还剩 {audit.main_headroom_from_fixed_tokens} tok，"
		f"却报主链超限 {audit.main_overflow_tokens} ⇒ 记账口径回退了"
	)


def test_headroom_never_invents_budget() -> None:
	"""**关键安全性质**：fixed_tokens + 生效主链上限 == hot_budget_tokens。

	浮动只是把固定段没用完的那一笔挪给主链，合计不得变大 —— 否则这条改动就变成了
	"给热层加预算"，成本口径与已发布的账全被改动。
	"""
	audit = _apply("目标：修超时", "决策记录 " * 30)
	hot_budget = audit.fixed_budget_tokens + audit.main_budget_tokens
	assert audit.fixed_tokens + audit.main_effective_cap_tokens == hot_budget
	assert audit.main_effective_cap_tokens <= hot_budget


def test_real_main_overflow_still_reported() -> None:
	"""固定段**用满**时主链再超限，就是真超限，必须照样报出来（不能被浮动掩盖）。"""
	big_fixed = "约束" * 3_000  # 远超 1800 ⇒ 无让渡额度
	audit = _apply(big_fixed, "决策记录 " * 200)
	assert audit.main_headroom_from_fixed_tokens == 0
	assert audit.main_effective_cap_tokens == audit.main_budget_tokens
	assert audit.main_overflow_tokens > 0


# ---- 可恢复性索引（剪枝卡面）单列一桶 --------------------------------------


def _apply_with_cards(card_lines: int, *, index_cap: int = 1_600, main_cap: int = 1_200):
	"""造一个「卡面很大」的投影账目：``[PRUNED]``/``[DECISIONS]`` 各若干行。"""
	msgs = [msg_user("这是一个足够长的用户问题内容"), msg_asst_text("ok")]
	graph = build_graph(msgs)
	params = WscParams(
		fixed_segment_budget_tokens=1_800,
		main_segment_budget_tokens=main_cap,
		hot_budget_tokens=1_800 + main_cap,
		index_segment_budget_tokens=index_cap,
	)
	groups = {
		H_CONSTRAINTS: [("pin:0", "目标：修超时")],
		H_REQUESTS: [("req:0", "用户原话")],
		H_MAIN: [("main:1", "主体一行")],
		H_DECISIONS: [(f"card:d{i}", f"已排除: 分支 {i} files=a.py  expand(node://{i})") for i in range(card_lines)],
		H_PRUNED: [(f"card:p{i}", f"结论 {i} files=b.py  expand(node://{100+i})") for i in range(card_lines)],
	}
	out, audit = apply_hot_budgets(
		groups,
		params,
		graph=graph,
		region_end=len(msgs),
		request_header=H_REQUESTS,
		request_skip=frozenset(),
		user_nodes=(0,),
		fixed_headers=(H_CONSTRAINTS, H_REQUESTS),
		main_headers=(H_MAIN, H_DECISIONS, H_PRUNED),
		index_headers=(H_DECISIONS, H_PRUNED),
	)
	return out, audit


def test_card_surface_is_not_counted_as_main_overflow() -> None:
	"""卡面再大也不得报"主链超限"——它是句柄出口，不是注意力内容。"""
	_out, audit = _apply_with_cards(40)
	assert audit.index_tokens > audit.main_tokens, "卡面没被分进索引桶"
	assert audit.main_overflow_tokens == 0
	assert audit.index_tokens > 0


def test_bucketing_never_drops_content() -> None:
	"""**核心安全性质**：分桶只改记账，一个字节都不删。

	没有这条，"索引超额"迟早会被后来人当成现成的裁剪入口，
	而删掉的每一行都是一个节点唯一的 expand 出路。
	"""
	# 每段 140 行 ≈ 1740 tok 卡面 > index_cap 1600，确保处在"超额"分支上。
	out, audit = _apply_with_cards(140)
	assert audit.index_overflow_tokens > 0, "夹具没造出索引超额，本测试失去意义"
	assert len(out[H_DECISIONS]) == 140
	assert len(out[H_PRUNED]) == 140


def test_hot_total_reports_true_cost() -> None:
	"""成本必须按三桶相加报，分桶不许把超出部分藏起来。"""
	_out, audit = _apply_with_cards(140)
	assert audit.hot_total_tokens == audit.fixed_tokens + audit.main_tokens + audit.index_tokens
	assert audit.hot_total_tokens > audit.fixed_budget_tokens + audit.main_budget_tokens, (
		"夹具没让真实总量超过两桶注意力额度之和，本测试失去意义"
	)
