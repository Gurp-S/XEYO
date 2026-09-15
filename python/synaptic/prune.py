"""剪枝卡生成（规则 4）：被剪掉的分支不消失，降级成「结论 + 缺口句柄」。

卡片只承载结论型信息：这条分支试了什么、涉及哪些文件、错误签名是什么、
能不能重放。原始内容不在卡里（在冷层，靠 ``branch://<id>`` 展开）。
"""

from __future__ import annotations

from dataclasses import dataclass

from synaptic.graph import Graph
from synaptic.textutil import node_token_len
from synaptic.types import EDGE_USE, KIND_TOOL_RESULT, KIND_TOOL_USE, PruneCard, WscParams

CARD_ID_PREFIX = "B"


@dataclass(frozen=True)
class _Unit:
	"""一个「尝试单元」：一次工具调用 + 它的结果。"""

	root: int
	nodes: tuple[int, ...]
	tool: str
	ok: bool
	error_sig: str
	files: tuple[str, ...]
	replay: str


def _units(graph: Graph, region_end: int) -> list[_Unit]:
	"""把区域切成尝试单元（tool_use + use 边指向的结果）。"""
	units: list[_Unit] = []
	claimed: set[int] = set()
	for n in graph.nodes:
		if n.idx >= region_end or n.kind != KIND_TOOL_USE:
			continue
		children = [d for d in graph.outgoing(n.idx, EDGE_USE) if d < region_end]
		idxs = [n.idx, *children]
		claimed.update(idxs)
		err = ""
		ok = True
		for c in children:
			m = graph.node(c)
			if m is None:
				continue
			if m.is_error:
				ok = False
				if not err:
					err = m.error_sig
		files: list[str] = []
		for i in idxs:
			m = graph.node(i)
			if m:
				files.extend(m.refs)
		replay = n.replay_cmd
		for c in children:
			m = graph.node(c)
			if m and m.replay_cmd and not replay:
				replay = m.replay_cmd
		units.append(
			_Unit(
				root=n.idx,
				nodes=tuple(idxs),
				tool=n.tool_name or "tool",
				ok=ok,
				error_sig=err,
				files=tuple(dict.fromkeys(files)),
				replay=replay,
			)
		)
	# 未被单元认领的节点（用户文本 / 纯助手文本 / 孤儿结果）→ 各自成「散点单元」
	for n in graph.nodes:
		if n.idx >= region_end or n.idx in claimed:
			continue
		units.append(
			_Unit(
				root=n.idx,
				nodes=(n.idx,),
				tool=n.kind,
				ok=not n.is_error,
				error_sig=n.error_sig if n.is_error else "",
				files=tuple(n.refs),
				replay=n.replay_cmd,
			)
		)
	units.sort(key=lambda u: u.root)
	return units


def _first_meaningful_line(text: str, limit: int = 90) -> str:
	for raw in str(text or "").splitlines():
		s = " ".join(raw.split())
		if len(s) >= 6:
			return s[:limit]
	return ""


def _conclusion(graph: Graph, unit: _Unit, limit: int) -> str:
	"""把单元压缩成一句结论（删过程留结论）。"""
	target = unit.files[0] if unit.files else ""
	if unit.error_sig:
		head = f"{unit.tool} 对 {target} 失败：{unit.error_sig}" if target else f"{unit.tool} 失败：{unit.error_sig}"
		return head[:limit]
	if unit.tool == KIND_TOOL_RESULT:
		# 孤儿结果：只留首行实质内容
		m = graph.node(unit.root)
		line = _first_meaningful_line(m.text if m else "")
		return (f"结果: {line}" if line else "结果（内容已冷存）")[:limit]
	if unit.tool == "user_text":
		m = graph.node(unit.root)
		s = " ".join((m.text if m else "").split())
		return f"用户输入: {s[: limit - 6]}" if s else "用户输入"
	if unit.tool == "assistant_text":
		m = graph.node(unit.root)
		line = _first_meaningful_line(m.text if m else "")
		return (f"助手结论: {line}" if line else "助手结论（已冷存）")[:limit]
	m = graph.node(unit.root)
	line = _first_meaningful_line(m.text if m else "")
	suffix = f" → {line}" if line else ""
	head = f"{unit.tool}"
	if target:
		head += f" {target}"
	if unit.ok:
		head += " 完成"
	return (head + suffix)[:limit]


def build_cards(
	graph: Graph,
	pruned: tuple[int, ...],
	params: WscParams,
	*,
	region_end: int,
) -> tuple[PruneCard, ...]:
	"""把剪掉的节点归并成剪枝卡。"""
	pruned_set = set(pruned)
	kept_units: list[_Unit] = []
	for u in _units(graph, region_end):
		if all(i in pruned_set for i in u.nodes):
			kept_units.append(u)
		elif any(i in pruned_set for i in u.nodes):
			# 部分剪掉：只把被剪的成员缩成一个卡（避免丢信息）
			sub = tuple(i for i in u.nodes if i in pruned_set)
			kept_units.append(
				_Unit(
					root=sub[0],
					nodes=sub,
					tool=u.tool,
					ok=u.ok,
					error_sig=u.error_sig,
					files=u.files,
					replay=u.replay,
				)
			)
	if not kept_units:
		return ()

	# 生成卡。card_id 用**根节点下标**而不是序号——序号会随区域增长整体位移，
	# 导致 append_only 模式下每轮都判定「内容变了」而被迫整层重建。
	raw: list[PruneCard] = []
	for u in kept_units:
		concl = _conclusion(graph, u, params.card_conclusion_chars)
		tokens = node_token_len(concl) + 6  # 卡片自身的固定开销（id/files/句柄）
		raw.append(
			PruneCard(
				card_id=f"{CARD_ID_PREFIX}{u.root}",
				conclusion=concl,
				files=u.files[:4],
				error_sig=u.error_sig,
				replay=u.replay,
				nodes=u.nodes,
				tokens=tokens,
			)
		)

	# 删重复：同结论合并（保留第一个，节点并集）
	merged: list[PruneCard] = []
	by_concl: dict[tuple[str, str], int] = {}
	for c in raw:
		key = (c.conclusion, c.error_sig)
		if key in by_concl:
			i = by_concl[key]
			prev = merged[i]
			merged[i] = PruneCard(
				card_id=prev.card_id,
				conclusion=prev.conclusion,
				files=tuple(dict.fromkeys(prev.files + c.files))[:4],
				error_sig=prev.error_sig,
				replay=prev.replay or c.replay,
				nodes=tuple(dict.fromkeys(prev.nodes + c.nodes)),
				tokens=prev.tokens,
			)
		else:
			by_concl[key] = len(merged)
			merged.append(c)

	# 卡上限：只合并「无错误签名」的纯信息卡，带错误的卡永不丢弃（防重复犯错）
	while len(merged) > params.max_cards:
		idx = _weakest_mergeable(merged)
		if idx is None:
			break
		j = _nearest_mergeable(merged, idx)
		if j is None:
			break
		a, b = merged[idx], merged[j]
		new_nodes = tuple(dict.fromkeys(a.nodes + b.nodes))
		concl = f"{a.conclusion}；另 {len(b.nodes)} 条同类记录"[: params.card_conclusion_chars]
		merged[idx] = PruneCard(
			card_id=a.card_id,
			conclusion=concl,
			files=tuple(dict.fromkeys(a.files + b.files))[:4],
			error_sig=a.error_sig,
			replay=a.replay,
			nodes=new_nodes,
			tokens=node_token_len(concl) + 6,
		)
		merged.pop(j)

	return tuple(merged)


def _weakest_mergeable(cards: list[PruneCard]) -> int | None:
	"""最弱的可合并卡：无错误签名、节点数最少、编号最大。"""
	cands = [i for i, c in enumerate(cards) if not c.error_sig and len(c.nodes) <= 2]
	if not cands:
		cands = [i for i, c in enumerate(cards) if not c.error_sig]
	if not cands:
		return None
	return min(cands, key=lambda i: (len(cards[i].nodes), -i))


def _nearest_mergeable(cards: list[PruneCard], avoid: int) -> int | None:
	cands = [i for i, c in enumerate(cards) if i != avoid and not c.error_sig]
	if not cands:
		return None
	return min(cands, key=lambda i: (abs(i - avoid), -i))


def render_card(c: PruneCard) -> str:
	"""一张卡的热层文本（单行，便于前缀稳定）。"""
	bits = [f"{c.card_id}:"]
	bits.append(c.conclusion)
	if c.files:
		bits.append(f"files={','.join(c.files)}")
	if c.error_sig:
		bits.append(f"err={c.error_sig[:80]}")
	if c.replay:
		bits.append(f"replay={c.replay[:100]}")
	bits.append(f"expand({c.handle})")
	return " ".join(bits)


def cards_tokens(cards: tuple[PruneCard, ...]) -> int:
	return sum(node_token_len(render_card(c)) for c in cards)
