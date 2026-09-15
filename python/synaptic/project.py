"""突触压缩（WSC）顶层入口。

一次压缩 = 建图 → 文件状态 → 种子 → 反向闭包 → 加权背包 → 剪枝卡 → 组装。
全流程零 LLM 调用、零随机性、零生产链依赖。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from synaptic.assemble import (
	AssemblyState,
	assemble,
	build_pins,
	render_pins,
)
from synaptic.closure import audit_rows, plan_selection
from synaptic.coldstore import ColdStore, branch_handle, node_handle
from synaptic.filestate import build_file_states, file_state_tokens, working_set
from synaptic.graph import Graph, build_graph, graph_digest
from synaptic.prune import build_cards, cards_tokens
from synaptic.seeds import Seeds, collect_seeds
from synaptic.textutil import node_token_len
from synaptic.types import (
	KIND_USER,
	MODE_APPEND_ONLY,
	HotLayer,
	WscParams,
	WscResult,
)

# 剪枝卡预算的首次预留（token）。真实值由 build_cards 回算后迭代收敛。
_CARD_RESERVE_SEED = 400


@dataclass
class Projection:
	"""一次投影的产物（热层文本 + 冷层 + 组装状态）。"""

	result: WscResult
	cold: ColdStore
	state: AssemblyState
	graph: Graph
	seeds: Seeds
	audit: list[dict] = field(default_factory=list)

	@property
	def text(self) -> str:
		return self.result.hot.text

	@property
	def tokens(self) -> int:
		return self.result.hot.tokens


def project(
	messages: list[dict],
	*,
	region_end: int,
	params: WscParams | None = None,
	prev: AssemblyState | None = None,
	cold: ColdStore | None = None,
	goal_override: str = "",
	session: str = "",
	region_baseline_tokens: int | None = None,
) -> Projection:
	"""压缩 ``messages[:region_end]`` 为热层；``[region_end, end)`` 不触碰。

``region_baseline_tokens`` 给出「把该区域原样发出去」的成本（调用方用生产链
同口径的 C0 投影算）。给定且热层不比重放更省时，置 ``compressed=False``——
短会话上 PIN + 卡片开销会超过节省，没有这道门就会出现「压缩后更大」。
	"""
	p = params or WscParams()
	if region_end <= 0:
		region_end = 0

	graph = build_graph(messages)
	file_states = build_file_states(graph, messages)
	seeds = collect_seeds(graph, messages, file_states, goal_override=goal_override)

	pins = build_pins(seeds)
	pin_tokens = sum(node_token_len(line) + 1 for _, line in render_pins(pins))
	ws = working_set(file_states, limit=12, pin_paths=seeds.pin_paths)
	ws_tokens = file_state_tokens(ws)

	unresolved_set = _unresolved_idx(graph)

	overhead = pin_tokens + ws_tokens
	budget = max(0, p.hot_budget_tokens - overhead - _CARD_RESERVE_SEED)

	selection = None
	cards = ()
	used = 0
	for _ in range(4):
		selection = plan_selection(
			graph,
			seeds,
			p,
			region_end=region_end,
			budget_tokens=budget,
			unresolved_set=unresolved_set,
		)
		cards = build_cards(graph, selection.pruned, p, region_end=region_end)
		used = selection.used_tokens + cards_tokens(cards)
		overflow = overhead + used - p.hot_budget_tokens
		if overflow <= 0:
			break
		budget = max(0, budget - overflow - 20)

	assert selection is not None
	text, rebuilt, state, atrace = assemble(
		graph, seeds, pins, ws, cards, selection.kept, p, prev=prev, region_end=region_end
	)
	tokens = node_token_len(text)

	# 冷层：被剪枝的 + 被骨架化的（未内联的）保留节点，全部可无损拉回
	cs = cold or ColdStore(session=session)
	cold_nodes: list[tuple[int, str, dict]] = []
	for c in cards:
		cs.bind(branch_handle(c.card_id), c.nodes)
		for i in c.nodes:
			n = graph.node(i)
			if n is not None:
				cold_nodes.append((i, n.text, {"kind": n.kind, "tool": n.tool_name}))
	for idx in selection.kept:
		n = graph.node(idx)
		if n is None or n.tokens <= p.inline_max_tokens:
			continue
		cs.bind(node_handle(idx), (idx,))
		cold_nodes.append((idx, n.text, {"kind": n.kind, "tool": n.tool_name}))
	# [REQUESTS] 是**截断摘要 + 句柄**：句柄必须是真句柄，否则「无损可恢复」被截断悄悄破坏。
	# 集合取 seeds.user_nodes（实质人类用户消息），不按 kind 扫图——kind 上还挂着工具结果。
	for idx in seeds.user_nodes:
		if idx >= region_end:
			continue
		n = graph.node(idx)
		if n is None or not n.text.strip():
			continue
		cs.bind(node_handle(idx), (idx,))
		cold_nodes.append((idx, n.text, {"kind": n.kind, "tool": n.tool_name}))
	cs.put_nodes(cold_nodes)

	hot = HotLayer(
		text=text,
		tokens=tokens,
		kept_nodes=selection.kept,
		pruned_nodes=selection.pruned,
		cards=cards,
		file_states=ws,
		pins=pins,
		level=p.level,
		mode=p.mode,
	)

	trace = [
		{
			"step": "graph",
			"detail": f"nodes={len(graph.nodes)} edges={len(graph.edges)} digest={graph_digest(graph)}",
		},
		{
			"step": "seeds",
			"detail": f"pin_nodes={len(seeds.pin_nodes)} constraints={len(seeds.constraints)} "
			f"unresolved={len(seeds.unresolved_errors)} todos={len(seeds.todos)}",
		},
		{
			"step": "select",
			"detail": f"kept={len(selection.kept)} pruned={len(selection.pruned)} "
			f"budget={selection.budget_tokens} used={selection.used_tokens}",
		},
		{
			"step": "assemble",
			"detail": f"mode={p.mode} rebuilt={rebuilt} tokens={tokens} overhead={overhead}",
		},
		{
			"step": "sections",
			"detail": " → ".join(state.seg_order)
			+ "".join(f" | {h}:{st.change_rate:.0%}" for h, st in state.seg_stats.items() if st.obs),
		},
		*({"step": "assembly", "detail": t["action"] + ": " + t["why"]} for t in atrace),
	]
	if overhead >= p.hot_budget_tokens:
		trace.append(
			{"step": "warn", "detail": f"PIN+工作集已超预算（{overhead}>{p.hot_budget_tokens}），主链为空"}
		)

	# 收益门（规则 7）：热层不比重放原文更省 → 不压缩。
	compressed = True
	if region_baseline_tokens is not None:
		if tokens >= max(0, region_baseline_tokens - p.min_gain_tokens):
			compressed = False
			trace.append(
				{
					"step": "gain_gate",
					"detail": (
						f"放弃压缩：热层 {tokens} tok vs 原样重放 {region_baseline_tokens} tok，"
						f"差值不足 min_gain_tokens={p.min_gain_tokens}"
					),
				}
			)

	return Projection(
		result=WscResult(
			hot=hot,
			level=p.level,
			mode=p.mode,
			base_tokens=_region_tokens(graph, region_end),
			rebuilt=rebuilt,
			compressed=compressed,
			churn={h: st.change_rate for h, st in state.seg_stats.items()},
			front_break={h: st.front_rate for h, st in state.seg_stats.items()},
			churn_warnings=state.churn_warn,
			journal_appends=state.journal_appends,
			journal_refroze=rebuilt if p.journal_layout else False,
			journal_tokens=node_token_len(state.full_text) if p.journal_layout else 0,
			user_requests_rendered=state.req_rendered,
			user_requests_total=state.req_total,
			trace=trace,
		),
		cold=cs,
		state=state,
		graph=graph,
		seeds=seeds,
		audit=audit_rows(graph, selection),
	)


def _unresolved_idx(graph: Graph) -> set[int]:
	from synaptic.seeds import _unresolved_error_nodes

	return set(_unresolved_error_nodes(graph))


def _region_tokens(graph: Graph, region_end: int) -> int:
	return sum(n.tokens for n in graph.nodes if n.idx < region_end)


def default_params(level: str = "Medium+", mode: str = "closure") -> WscParams:
	return WscParams(level=level, mode=mode).for_level(level)


__all__ = [
	"MODE_APPEND_ONLY",
	"Projection",
	"default_params",
	"project",
]
