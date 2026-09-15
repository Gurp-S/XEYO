"""反向闭包与确定性背包选择测试。"""

from __future__ import annotations

from synaptic.closure import (
	backward_closure,
	knapsack_select,
	plan_selection,
	selection_digest,
)
from synaptic.filestate import build_file_states
from synaptic.graph import build_graph
from synaptic.seeds import collect_seeds
from synaptic.types import WscParams
from wsc._fixtures import synth_session


def _setup(turns: int = 6, **kw):
	msgs = synth_session(turns=turns, **kw)
	g = build_graph(msgs)
	fs = build_file_states(g, msgs)
	seeds = collect_seeds(g, msgs, fs)
	return msgs, g, fs, seeds


def test_backward_closure_only_walks_predecessors():
	g = build_graph(synth_session(turns=3))
	# 节点 2 是 tool_result，1 是它的 tool_use（use 边 1->2）
	seen = backward_closure(g, (2,), 1)
	assert 2 in seen and 1 in seen


def test_must_keep_survives_zero_budget():
	"""PIN / 未解决错误节点在预算为 0 时也必须留在 kept 里。"""
	_, g, _, seeds = _setup()
	sel = plan_selection(
		g,
		seeds,
		WscParams(),
		region_end=len(g.nodes),
		budget_tokens=0,
		unresolved_set={n.idx for n in g.nodes if n.is_error},
	)
	assert set(seeds.pin_nodes).issubset(set(sel.kept))
	assert any(g.nodes[i].is_error for i in sel.kept)


def test_budget_is_charged_by_emitted_cost_not_raw_size():
	"""已进 PIN 的节点在热层里不占空间，预算不得按原文体积计。"""
	_, g, _, seeds = _setup()
	pin_tokens = sum(g.nodes[i].tokens for i in seeds.pin_nodes)
	assert pin_tokens > 0

	sel_charged = plan_selection(
		g, seeds, WscParams(), region_end=len(g.nodes), budget_tokens=1200, unresolved_set=set()
	)
	from synaptic.graph import Graph  # noqa: F401  (仅作类型说明)

	# 若按原文计费，PIN 节点自己就会吃掉全部预算；按发射成本计费则还剩空间给主链
	non_pin_kept = [i for i in sel_charged.kept if i not in set(seeds.pin_nodes)]
	assert non_pin_kept, "预算被 PIN 的原文体积吃光，主链为空（记账口径回归）"


def test_selection_is_deterministic():
	_, g, _, seeds = _setup()
	args = dict(region_end=len(g.nodes), budget_tokens=800, unresolved_set=set())
	a = plan_selection(g, seeds, WscParams(), **args)
	b = plan_selection(g, seeds, WscParams(), **args)
	assert selection_digest(a) == selection_digest(b)
	assert a.kept == b.kept and a.pruned == b.pruned


def test_knapsack_respects_budget_when_settable():
	_, g, _, seeds = _setup()
	sel = knapsack_select(
		g,
		{},
		candidates={n.idx for n in g.nodes},
		must_keep=set(),
		budget_tokens=100,
		charge={n.idx: n.tokens for n in g.nodes},
	)
	assert sel.used_tokens <= 100


def test_closure_hops_change_reachable_set():
	g = build_graph(synth_session(turns=4))
	seed = (g.nodes[-1].idx,)
	one = backward_closure(g, seed, 1)
	two = backward_closure(g, seed, 2)
	assert one.issubset(two)


def test_reason_recorded_for_both_kept_and_pruned():
	"""可审计性：入围与落选都必须有理由。"""
	_, g, _, seeds = _setup()
	sel = plan_selection(
		g, seeds, WscParams(), region_end=len(g.nodes), budget_tokens=500, unresolved_set=set()
	)
	cands = set(sel.candidates)
	assert cands <= set(sel.reason), "有候选节点没有留下决策理由"
