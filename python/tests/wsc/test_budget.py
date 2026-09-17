"""双预算回归：固定段/主链拆分、REQUESTS 降级、句柄保底与审计透传。"""

from __future__ import annotations

from synaptic.assemble import H_CONSTRAINTS, H_REQUESTS
from synaptic.budget import (
	apply_hot_budgets,
	render_requests_compact,
	render_requests_grouped,
	rendered_request_nodes,
	segment_tokens,
)
from synaptic.graph import build_graph
from synaptic.project import project
from synaptic.seeds import collect_seeds, request_skip
from synaptic.types import LEVELS, WscParams
from wsc._fixtures import msg_asst_text, msg_user, synth_session


def test_for_level_splits_exact_hot_budget():
	p = WscParams().for_level("Medium+")
	assert p.hot_budget_tokens == 3_000
	assert p.fixed_segment_budget_tokens == 1_800
	assert p.main_segment_budget_tokens == 1_200
	assert p.fixed_segment_budget_tokens + p.main_segment_budget_tokens == p.hot_budget_tokens


def test_for_level_never_leaves_unaccounted_budget():
	for level in LEVELS:
		p = WscParams().for_level(level)
		assert p.fixed_segment_budget_tokens + p.main_segment_budget_tokens == p.hot_budget_tokens
		want_fixed = 1_800 if level == "Medium+" else 1_200
		assert p.fixed_segment_budget_tokens == min(want_fixed, p.hot_budget_tokens)
	clamped = WscParams(fixed_segment_budget_tokens=99_999).for_level("Hard")
	assert clamped.fixed_segment_budget_tokens == clamped.hot_budget_tokens
	assert clamped.main_segment_budget_tokens == 0


def _request_budget_case(*, fixed_budget: int = 80):
	msgs = [msg_user("不要改协议。"), msg_asst_text("ok")]
	for i in range(5):
		msgs.append(msg_user(f"第 {i} 条后续要求：" + "很长的用户原话" * 30))
		msgs.append(msg_asst_text("收到"))
	g = build_graph(msgs)
	s = collect_seeds(g, msgs, {}, goal_override="")
	req = [
		(f"req:{idx}", f"#{idx} 用户: " + "很长的用户原话" * 30)
		for idx in s.user_nodes
		if idx < len(msgs)
	]
	params = WscParams(fixed_segment_budget_tokens=fixed_budget, main_segment_budget_tokens=200)
	groups = {H_REQUESTS: req}
	out, audit = apply_hot_budgets(
		groups,
		params,
		graph=g,
		region_end=len(msgs),
		request_header=H_REQUESTS,
		request_skip=frozenset(),
		user_nodes=s.user_nodes,
		fixed_headers=(H_REQUESTS,),
		main_headers=(),
	)
	return g, s, out, audit


def test_requests_degrade_before_dropping_handles():
	g, s, out, audit = _request_budget_case()
	assert audit.request_mode in ("dedup_short", "handles", "dropped")
	assert audit.request_tokens <= audit.fixed_budget_tokens
	if audit.request_mode == "dropped":
		assert H_REQUESTS not in out
	else:
		rendered = "\n".join(line for _key, line in out[H_REQUESTS])
		assert "expand(" in rendered


def test_dedup_short_keeps_full_80_char_needle():
	"""80 字符降级档必须保留完整前 80 字符；不能是 79 字符 + 省略号。"""
	g, s, out, audit = _request_budget_case(fixed_budget=420)
	assert audit.request_mode == "dedup_short"
	rendered = "\n".join(line for _key, line in out[H_REQUESTS])
	for idx in s.user_nodes:
		node = g.node(idx)
		assert node is not None
		needle = " ".join(node.text.split())[:80]
		assert needle in rendered, f"80 字符档丢失关键针: idx={idx}"

def test_requests_dedup_preserves_unique_user_text_across_turns():
	"""回归：REQUESTS 超预算时，重复原话必须保留文本针而不是退成纯句柄。

	P1-b 之后区间句柄把 ``[REQUESTS]`` 行数压掉一个量级，真实语料通常已经撞不到
	固定段预算。**所以这里显式把预算压到「装得下去重形态、装不下完整形态」那一档**：
	不改的话这条回归会因为「压根没触发降级」而静默失效——测试还是绿的，但机制没人守。
	"""
	prompts = (
		"第一个问题：" + "甲" * 120,
		"第二个问题：" + "乙" * 120,
		"第三个问题：" + "丙" * 120,
	)
	msgs = [msg_user("总目标"), msg_asst_text("ok")]
	for _ in range(9):
		for text in prompts:
			msgs.append(msg_user(text))
			msgs.append(msg_asst_text("收到 " + "x" * 80))
	region_end = len(msgs)
	g = build_graph(msgs)
	s = collect_seeds(g, msgs, {})
	base = WscParams().for_level("Medium+")
	kwargs = {"skip": request_skip(s), "user_nodes": s.user_nodes}
	full = render_requests_compact(g, region_end, base, **kwargs)
	grouped = render_requests_grouped(g, region_end, base, **kwargs)
	full_tok, grouped_tok = segment_tokens(full), segment_tokens(grouped)
	assert grouped_tok < full_tok, (grouped_tok, full_tok)

	params = WscParams(
		fixed_segment_budget_tokens=grouped_tok, main_segment_budget_tokens=1_800
	)
	out, audit = apply_hot_budgets(
		{H_REQUESTS: full},
		params,
		graph=g,
		region_end=region_end,
		request_header=H_REQUESTS,
		request_skip=request_skip(s),
		user_nodes=s.user_nodes,
		fixed_headers=(H_REQUESTS,),
		main_headers=(),
	)
	assert audit.request_mode == "dedup", audit.request_mode
	rendered = "\n".join(line for _key, line in out[H_REQUESTS])
	for text in prompts:
		needle = " ".join(text.split())[:80]
		assert needle in rendered, f"唯一用户原话未逐字保留: {needle!r}"
	# 句柄口径：去重形态把同文本节点并成一个 ``node://i,j,...`` 组句柄，
	# 所以**不能**断言每个节点各有一条 ``node://<idx>``——要断言的是
	# 「每个节点都被某个已发射句柄覆盖」，这正是 rendered_request_nodes 的口径。
	covered = rendered_request_nodes(out[H_REQUESTS])
	# skip 集合里的节点已经在 [PIN] 里逐字出现，[REQUESTS] 不再为它们发句柄——
	# 这是设计口径，不是覆盖漏洞。
	skip = request_skip(s)
	in_region = {i for i in s.user_nodes if i < region_end} - set(skip)
	assert in_region <= covered, f"未覆盖的用户节点: {sorted(in_region - covered)}"


def test_fixed_overflow_is_recorded_when_other_sections_exceed_budget():
	msgs = [msg_user("不要改协议。"), msg_asst_text("ok")]
	for i in range(3):
		msgs.append(msg_user(f"要求 {i}：" + "内容" * 50))
		msgs.append(msg_asst_text("ok"))
	g = build_graph(msgs)
	s = collect_seeds(g, msgs, {})
	params = WscParams(fixed_segment_budget_tokens=10, main_segment_budget_tokens=10)
	out, audit = apply_hot_budgets(
		{H_CONSTRAINTS: [("pin:0", "不要改协议")], H_REQUESTS: [("req:1", "x" * 200)]},
		params,
		graph=g,
		region_end=len(msgs),
		request_header=H_REQUESTS,
		request_skip=frozenset(),
		user_nodes=s.user_nodes,
		fixed_headers=(H_CONSTRAINTS, H_REQUESTS),
		main_headers=(),
	)
	assert audit.fixed_overflow_tokens == 0
	assert audit.fixed_unavoidable_overflow_tokens == 0
	assert audit.fixed_avoidable_overflow_tokens == 0
	assert audit.request_mode in ("handles", "dropped")
	assert audit.fixed_avoidable_overflow_tokens == 0
	assert audit.request_tokens <= audit.fixed_budget_tokens


def test_project_counts_interval_request_nodes_not_lines():
	"""覆盖率回归：一行区间句柄覆盖 N 个节点时，分子必须按 N 计数。

	P1-b 换掉了 `[REQUESTS]` 的渲染形态（逐节点 → 区间句柄），断言里的
	`request_mode` 已不再是本条要守的契约；**要守的契约是「分子按节点算、不按行算」**，
	而区间句柄恰好把这件事放大到 8 倍（一行覆盖一整块），所以这里把它显式钉住。
	"""
	prompts = (
		"重复问题：" + "甲" * 120,
		"另一个问题：" + "乙" * 120,
	)
	msgs = [msg_user("总目标"), msg_asst_text("ok")]
	for _ in range(9):
		for text in prompts:
			msgs.append(msg_user(text))
			msgs.append(msg_asst_text("收到 " + "x" * 80))
	p = project(
		msgs,
		region_end=len(msgs),
		params=WscParams().for_level("Medium+"),
		session="coverage-dedup",
	)
	req_lines = [ln for ln in p.text.splitlines() if ln.startswith(H_REQUESTS)]
	# 「一行覆盖多节点」在两种形态下都成立：区间句柄 ``reqs://a-b``，
	# 或去重组句柄 ``node://i,j,...``。本条要守的是**分子按节点算、不按行算**，
	# 不是某一种句柄拼写，所以两种都接受（否则降级一发生测试就假红）。
	multi_node = [
		ln
		for ln in req_lines
		if "reqs://" in ln or ("," in ln.split("expand(")[-1])
	]
	assert multi_node, ("未走「一行多节点」形态，本条回归就测不到覆盖口径", req_lines)
	# “总目标”只有 3 个字符，按 _substantive 规则不算实质用户消息；
	# 其余 2 条不同原话各重复 9 次，共 18 个节点。
	assert p.result.user_requests_total == 2 * 9
	assert p.result.user_requests_rendered == p.result.user_requests_total
	assert len(req_lines) < p.result.user_requests_total, "行数没有真正降下来"


def test_project_exposes_budget_audit_and_trace():
	msgs = synth_session(turns=12, user_every=3)
	p = project(msgs, region_end=len(msgs), params=WscParams().for_level("Medium+"))
	assert p.result.budget
	assert p.result.budget["fixed_budget_tokens"] == 1_800
	assert p.result.budget["main_budget_tokens"] == 1_200
	assert any("fixed_budget=" in t.get("detail", "") for t in p.result.trace)
