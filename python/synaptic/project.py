"""突触压缩（WSC）顶层入口。

一次压缩 = 建图 → 文件状态 → 种子 → 反向闭包 → 加权背包 → 剪枝卡 → 组装。
全流程零 LLM 调用、零随机性、零生产链依赖。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from synaptic.assemble import (
	AssemblyState,
	assemble,
	build_pins,
	render_pins,
)
from synaptic.budget import request_chunk_ids
from synaptic.closure import Selection, audit_rows, plan_selection
from synaptic.coldstore import (
	ColdStore,
	head_handle,
	node_group_handle,
	node_handle,
	reqs_handle,
)
from synaptic.cold_evidence import complete_cold_evidence
from synaptic.filestate import build_file_states, file_state_tokens, working_set
from synaptic.freeze import freeze_working_set, phase_signature
from synaptic.freshness import analyze as analyze_freshness
from synaptic.graph import Graph, build_graph, graph_digest
from synaptic.handles import HandleRenderer
from synaptic.read_plan import prepare_view
from synaptic.prune import build_cards, cards_handle, cards_tokens, group_cards
from synaptic.pin_sources import bind_short_pin_sources, complete_pin_sources
from synaptic.journal_rollover import journal_preserves_head
from synaptic.group_recovery import prepare_groups, recovery_renderer
from synaptic.journal_snapshot import finish_rebase
from synaptic.rehydrate import (
	decay_leases,
	leased_paths,
	plan_working_set_rehydration,
	renew_leases,
)
from synaptic.retrieval import (
	CurrentState,
	HistoryCandidate,
	HistoryQuery,
)
from synaptic.seeds import Seeds, collect_seeds, recent_paths, request_skip
from synaptic.textutil import node_token_len
from synaptic.timing import StageTimer
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
	#: 冷层取回视图路径（`handle_style=read` 时非空）。
	view_path: str = ""
	#: 时效轴（去噪）审计：错误识别数 / 按类降级数 / 误降级复检 / 死路径。
	denoise: dict = field(default_factory=dict)
	#: 当前状态与历史候选（仅审计/旁路；不改变当前热层文本）。
	current_state: CurrentState | None = None
	history_query: HistoryQuery | None = None
	history_candidates: tuple[HistoryCandidate, ...] = ()

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
	#: 冷层取回视图落盘路径。给了且 `params.handle_style == "read"` 时，热层句柄
	#: 渲染成 `Read(file_path=…, offset=…, limit=…)`；不给则保持 `expand(<handle>)`。
	view_path: Path | str | None = None,
	#: 句柄里**渲染**出来的取回路径（默认 = `str(view_path)`）。
	#: 与 `view_path` 分开的理由：写入位置必须是绝对路径（进程 cwd ≠ 工作区时相对路径会写错地方），
	#: 而**渲染**给模型的引用应当尽量短——`Read` 的 cwd 是读取方工作区，工作区相对路径同样能解析。
	#: 调用方用 `memory.offload.ref_path_for()` 生成它（判不出相对会自动回落绝对）。
	view_ref: str = "",
	#: 当前轮显式触碰的工作集路径；供旁路自动取回使用，不做语义推断。
	rehydrate_paths: tuple[str, ...] = (),
	persist_view: bool = True,
	exclude_state_notes: bool = False,
) -> Projection:
	"""压缩 ``messages[:region_end]`` 为热层；``[region_end, end)`` 不触碰。

``region_baseline_tokens`` 给出「把该区域原样发出去」的成本（调用方用生产链
同口径的 C0 投影算）。给定且热层不比重放更省时，置 ``compressed=False``——
短会话上 PIN + 卡片开销会超过节省，没有这道门就会出现「压缩后更大」。
	"""
	p = params or WscParams()
	timer = StageTimer()
	if region_end <= 0:
		region_end = 0

	graph = build_graph(messages, include_soft_edges=p.soft_dag)
	state_notes = frozenset()
	if exclude_state_notes:
		from synaptic.state_source import exclude_state_notes as exclude_notes
		graph, state_notes = exclude_notes(graph, messages)
	timer.mark("graph")
	# 时效轴：判定「同实体的旧断言是否已被后续断言覆盖」。这一步必须先于种子收集——
	# 降级集要参与「谁当种子 / 谁进热层」的决策，但它**只降级不删除**（冷层句柄可 expand）。
	fresh = analyze_freshness(graph, region_end=region_end)
	if state_notes:
		fresh = replace(fresh, superseded=fresh.superseded | state_notes)
	timer.mark("freshness")
	file_states = build_file_states(graph, messages)
	timer.mark("file_state")
	seeds = collect_seeds(
		graph,
		messages,
		file_states,
		goal_override=goal_override,
		superseded=fresh.superseded,
		resolved_errors=fresh.resolved_idx,
		drop_constraints=fresh.superseded_constraints,
		region_end=region_end,
	)
	seeds = replace(seeds, dead_paths=fresh.dead_paths)
	timer.mark("seeds")

	pins = bind_short_pin_sources(build_pins(seeds), seeds, graph,
	                              region_end=region_end, inline_max_tokens=p.inline_max_tokens)
	pin_tokens = sum(node_token_len(line) + 1 for _, line in render_pins(pins))
	ws = working_set(
		file_states,
		limit=12,
		pin_paths=seeds.pin_paths,
		recent_paths=recent_paths(graph, region_end=region_end),
	)
	if p.freeze_working_set and prev is not None and prev.frozen_file_states:
		ws = freeze_working_set(prev.frozen_file_states, ws, limit=12)
	ws_tokens = file_state_tokens(ws)

	# 已被后续成功覆盖的失败不再是「未解决」——它降级进冷层，不再占热层席位。
	# 口径直接取时效轴的结果，避免与 ``seeds`` 各算一份。
	unresolved_set = set(fresh.unresolved_idx) - set(fresh.superseded)

	overhead = pin_tokens + ws_tokens
	# 主链预算独立于固定段：REQUESTS 不再与 kept 抢同一个未分账水位。
	budget = max(0, p.main_segment_budget_tokens - _CARD_RESERVE_SEED)

	phase_key = phase_signature(graph, seeds, region_end) if p.freeze_main_chain else ""
	frozen_reuse = bool(
		p.freeze_main_chain
		and prev is not None
		and prev.frozen_phase_signature
		and prev.frozen_phase_signature == phase_key
		and prev.frozen_region_end > 0
	)
	selection = None
	cards = ()
	used = 0
	if frozen_reuse:
		frozen_kept = tuple(i for i in prev.frozen_kept if i < region_end)
		frozen_pruned = tuple(i for i in prev.frozen_pruned if i < region_end)
		kept_set = set(frozen_kept)
		new_pruned = tuple(
			i for i in range(max(0, prev.frozen_region_end), region_end)
			if i not in kept_set
		)
		selection = Selection(
			kept=frozen_kept,
			pruned=tuple(sorted(set(frozen_pruned) | set(new_pruned))),
			candidates=tuple(range(region_end)),
			scores={},
			budget_tokens=prev.frozen_selection_budget,
			used_tokens=prev.frozen_selection_used,
			reason={},
		)
		cards = tuple(prev.frozen_cards)
		used = selection.used_tokens + cards_tokens(cards)
	else:
		for _ in range(4):
			with timer.measure("select_plan"):
				selection = plan_selection(
					graph,
					seeds,
					p,
					region_end=region_end,
					budget_tokens=budget,
					unresolved_set=unresolved_set,
					superseded=fresh.superseded,
				)
			with timer.measure("select_cards"):
				cards = build_cards(
					graph, selection.pruned, p, region_end=region_end,
					superseded=fresh.superseded,
				)
			used = selection.used_tokens + cards_tokens(cards)
			overflow = used - p.main_segment_budget_tokens
			if overflow <= 0:
				break
			budget = max(0, budget - overflow - 20)

	assert selection is not None
	timer.mark("select")
	rehydration = None
	next_rehydration_leases: tuple[tuple[str, int], ...] = ()
	if p.auto_rehydrate_working_set:
		rehydrate_budget = max(0, int(p.main_segment_budget_tokens) - int(used))
		rehydrate_budget = min(rehydrate_budget, max(0, int(p.rehydrate_budget_tokens)))
		# ``kept`` only means the node won selection; large nodes are emitted as a
		# skeleton + handle and are therefore not fully visible.  Auto rehydration
		# must exclude only nodes whose complete text is already inline.
		inline_visible = {
			n.idx
			for n in graph.nodes
			if n.idx in selection.kept and n.idx not in seeds.pin_nodes
			and n.tokens <= p.inline_max_tokens and n.text.strip()
		}
		# Append-only journals already contain the previous recall lines.  They are
		# visible facts, so do not emit the same node again on every lease turn.
		if p.journal_layout and prev is not None and prev.mode == p.mode:
			inline_visible.update(prev.rehydration_nodes)
		previous_leases = prev.rehydration_leases if prev is not None else ()
		active_leases = decay_leases(
			previous_leases,
			working_paths=tuple(state.path for state in ws),
			min_working_set_lease=p.rehydrate_min_working_set_lease,
		)
		active_paths = leased_paths(active_leases)
		explicit_paths = tuple(str(path) for path in rehydrate_paths if str(path).strip())
		eligible_paths = tuple(dict.fromkeys((*active_paths, *explicit_paths)))
		rehydration = plan_working_set_rehydration(
			graph,
			ws,
			region_end=region_end,
			budget_tokens=rehydrate_budget,
			exclude=inline_visible,
			eligible_paths=eligible_paths,
		)
		next_rehydration_leases = renew_leases(
			active_leases,
			selected_paths=rehydration.selected_paths,
			initial_lease=p.rehydrate_initial_lease,
			refresh_lease=p.rehydrate_refresh_lease,
		)
	# 冷层：被剪枝的 + 被骨架化的（未内联的）保留节点，全部可无损拉回
	cs = cold or ColdStore(session=session)
	cold_nodes: list[tuple[int, str, dict]] = []
	for c in cards:
		cs.bind(c.handle, c.nodes)
		for i in c.nodes:
			n = graph.node(i)
			if n is not None:
				cold_nodes.append((i, n.text, {"kind": n.kind, "tool": n.tool_name}))
	# 合并卡行的组句柄：渲染（prune.render_card_group）与本处共用 group_cards/cards_handle。
	# 引用包含完整成员身份，不能让同名根节点在后续合并时改写旧引用。
	for group in group_cards(cards):
		if len(group) > 1:
			cs.bind(cards_handle(group), tuple(i for c in group for i in c.nodes))
	for idx in selection.kept:
		n = graph.node(idx)
		if n is None or (n.tokens <= p.inline_max_tokens and idx not in seeds.pin_nodes):
			continue
		cs.bind(node_handle(idx), (idx,))
		cold_nodes.append((idx, n.text, {"kind": n.kind, "tool": n.tool_name}))
	if frozen_reuse:
		# New nodes entering the compressed region stay out of the frozen main
		# decision, but remain recoverable without forcing a phase recompute.
		old_end = max(0, prev.frozen_region_end)
		old_pruned = set(prev.frozen_pruned)
		for idx in selection.pruned:
			if idx < old_end or idx in old_pruned:
				continue
			n = graph.node(idx)
			if n is None:
				continue
			cs.bind(node_handle(idx), (idx,))
			cold_nodes.append((idx, n.text, {"kind": n.kind, "tool": n.tool_name}))
	# [REQUESTS] 是**截断摘要 + 句柄**：句柄必须是真句柄，否则「无损可恢复」被截断悄悄破坏。
	# 集合取 seeds.user_nodes（实质人类用户消息），不按 kind 扫图——kind 上还挂着工具结果。
	user_groups: dict[str, list[int]] = {}
	req_skip = request_skip(seeds)
	for idx in seeds.user_nodes:
		if idx >= region_end:
			continue
		n = graph.node(idx)
		if n is None or not n.text.strip():
			continue
		cs.bind(node_handle(idx), (idx,))
		cold_nodes.append((idx, n.text, {"kind": n.kind, "tool": n.tool_name}))
		if idx in req_skip:
			continue
		key = " ".join(n.text.split())
		if key:
			user_groups.setdefault(key, []).append(idx)
	# 去重 [REQUESTS] 用的组句柄：同文本节点一次展开即可拿回全部原文。
	for idxs in user_groups.values():
		cs.bind(node_group_handle(tuple(idxs)), tuple(idxs))
	# P1-b 区间句柄：旧用户节点在紧凑渲染里被合并成 reqs://<首>-<末>。
	# **分块与渲染必须共用 ``request_chunk_ids``**（唯一实现在 budget.py）：
	# 各写一份就会出现「行里写的区间」与「句柄展开的节点集」不一致——
	# 那正是可恢复性被悄悄破坏的形态，而且往返比对会照样通过（句柄自洽地错）。
	# 单节点块渲染成 ``node://<idx>``（上面已绑），故这里只绑多节点块。
	for first, last, idxs in request_chunk_ids(
		graph, region_end, p, skip=req_skip, user_nodes=seeds.user_nodes
	):
		if len(idxs) > 1:
			cs.bind(reqs_handle(first, last), idxs)
	cs.put_nodes(cold_nodes)
	complete_cold_evidence(cs, graph, selection.kept, region_end=region_end)
	# 被替换的旧头需要归档；经核对仍完整保留的追加前缀不复制第二份。
	# 已发布的快照与 Read 区间仍按原块序保留。
	old_head = head_handle(prev.full_text) if prev is not None and prev.full_text else ""
	pending_archive = None
	if old_head and not journal_preserves_head(prev, p):
		if p.journal_layout and p.journal_rebase and p.handle_style == "read" and view_path:
			pending_archive = (old_head, prev.full_text)
		else:
			cs.put_snapshot(old_head, prev.full_text)
	recovery_aliases = {}
	if p.journal_rebase and p.handle_style == "read" and view_path:
		recovery_aliases = prepare_groups(cs, cards, view_ref or str(view_path))
	# ── 取回视图 + 句柄渲染器（2026-09-16 用户裁定：取回统一到 `Read`）──────────
	# 顺序要求：**先定稿节点集 → 写视图拿行号 → 再渲染**。旧顺序是「先渲染句柄文本、
	# 再绑冷层」，那样渲染时拿不到行号，也就渲染不出 `Read(file_path=…, offset=…, limit=…)`。
	# 视图路径不给 / style 非 read 时，渲染仍走历史形态 `expand(<handle>)`（零行为变更）。
	handles = HandleRenderer()
	view_out = ""
	if p.handle_style == "read":
		if view_path:
			ranges, line_lengths = prepare_view(cs, view_path, persist_view)
			handles = HandleRenderer(
				style="read",
				path=view_ref or str(view_path),
				node_ranges=ranges,
				handle_nodes=dict(cs.handles),
				line_lengths=line_lengths,
			)
			if recovery_aliases or any(h.startswith("head://packet-") for h in cs.snapshots):
				handles = recovery_renderer(cs, handles.path, ranges, line_lengths, recovery_aliases)
			view_out = str(view_path)
		else:
			# 没给视图路径 ⇒ 回落 expand 形态。**不静默**：调用方给了 read 却没给路径是配置错，
			# 落进 trace 让它可查（渲染坏引用的后果比降级严重得多）。
			pass
	timer.mark("coldstore")

	pins = complete_pin_sources(pins, prev, handles, cs)
	text, rebuilt, state, atrace = assemble(
		graph,
		seeds,
		pins,
		ws,
		cards,
		selection.kept,
		p,
		prev=prev,
		region_end=region_end,
		handles=handles,
		old_head_handle=old_head,
		rehydration=rehydration,
	)
	if pending_archive is not None:
		text, rebuilt, state, atrace = finish_rebase(
			(text, rebuilt, state, atrace), cold=cs, pending=pending_archive,
			view_path=view_path, view_ref=view_ref or str(view_path), persist=persist_view,
			aliases=recovery_aliases, assembler=assemble,
			args=(graph, seeds, pins, ws, cards, selection.kept, p),
			kwargs=dict(prev=prev, region_end=region_end, handles=handles,
			            old_head_handle=old_head, rehydration=rehydration))
	timer.mark("assemble")
	if p.freeze_main_chain:
		state.frozen_phase_signature = phase_key
		state.frozen_region_end = region_end
		state.frozen_kept = tuple(selection.kept)
		state.frozen_pruned = tuple(selection.pruned)
		state.frozen_cards = tuple(cards)
		state.frozen_selection_budget = int(selection.budget_tokens)
		state.frozen_selection_used = int(selection.used_tokens)
	if p.freeze_working_set:
		state.frozen_file_states = tuple(ws)
	if p.auto_rehydrate_working_set:
		state.rehydration_leases = next_rehydration_leases
		prior_rehydrated = (
			prev.rehydration_nodes
			if p.journal_layout and prev is not None and prev.mode == p.mode
			else ()
		)
		state.rehydration_nodes = tuple(
			dict.fromkeys((*prior_rehydrated, *(rehydration.nodes if rehydration else ())))
		)
	tokens = node_token_len(text)


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
		rehydrated_nodes=tuple(rehydration.nodes) if rehydration else (),
	)

	trace = [
		{
			"step": "freeze",
			"detail": (
				f"main={'reuse' if frozen_reuse else 'recompute' if p.freeze_main_chain else 'off'} "
				f"working_set={'reuse' if p.freeze_working_set and prev is not None and prev.frozen_file_states else 'recompute' if p.freeze_working_set else 'off'}"
			),
		},
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
			"detail": (
				f"mode={p.mode} rebuilt={rebuilt} tokens={tokens} overhead={overhead} "
				f"fixed_budget={p.fixed_segment_budget_tokens} "
				f"main_budget={p.main_segment_budget_tokens}"
			),
		},
		{
			"step": "sections",
			"detail": " → ".join(state.seg_order)
			+ "".join(f" | {h}:{st.change_rate:.0%}" for h, st in state.seg_stats.items() if st.obs),
		},
		{
			"step": "handles",
			# 引用路径必须留痕：绝对/相对两种形态的热层 token 不同（成本不可跨形态相减）。
			"detail": (
				f"style={p.handle_style} view={view_out or '-'} "
				f"ref={view_ref or view_out or '-'}"
			),
		},
		*({"step": "assembly", "detail": t["action"] + ": " + t["why"]} for t in atrace),
	]
	if overhead > p.fixed_segment_budget_tokens:
		trace.append(
			{
				"step": "warn",
				"detail": (
					f"PIN+工作集已超固定段预算（{overhead}>{p.fixed_segment_budget_tokens}），"
					"[REQUESTS] 仅保留句柄且固定段仍可能超预算"
				),
			}
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
			journal_refroze=state.journal_refroze if p.journal_layout else False,
			journal_tokens=node_token_len(state.full_text) if p.journal_layout else 0,
			user_requests_rendered=state.req_rendered,
			user_requests_total=state.req_total,
			budget=state.budget,
			stage_ms=timer.finish(),
			trace=trace,
		),
		cold=cs,
		view_path=view_out,
		state=state,
		graph=graph,
		seeds=seeds,
		audit=_audit_with_freshness(graph, selection, fresh),
		denoise=_denoise_report(graph, fresh),
	)


def _audit_with_freshness(graph: Graph, selection: Selection, fresh) -> list[dict]:
	"""选择审计 + 时效轴降级行（同一张表，便于逐条核对「谁因为什么离开热层」）。"""
	rows = audit_rows(graph, selection)
	for d in fresh.downgrades:
		rows.append(
			{
				"idx": d.idx,
				"action": "降级",
				"cls": d.cls,
				"by": d.by,
				"why": f"被 #{d.by} 覆盖：{d.why}",
			}
		)
	return rows


def _denoise_report(graph: Graph, fresh) -> dict:
	"""去噪审计（进 Projection，供回放/报告聚合）。"""
	out = fresh.audit()
	out["path_variants"] = {
		"merged_pairs": len(graph.refs_merged),
		"examples": [list(x) for x in graph.refs_merged[:12]],
	}
	out["noise_refs_dropped"] = len(graph.noise_refs)
	out["noise_refs_examples"] = list(graph.noise_refs[:12])
	return out


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
