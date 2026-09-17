"""剪枝卡生成（规则 4）：被剪掉的分支不消失，降级成「结论 + 缺口句柄」。

卡片只承载结论型信息：这条分支试了什么、涉及哪些文件、错误签名是什么、
能不能重放。原始内容不在卡里（在冷层，靠 ``branch://<id>`` 展开）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from synaptic.coldstore import BRANCH_PREFIX
from synaptic.graph import Graph
from synaptic.handles import renderer_or_default
from synaptic.textutil import node_token_len
from synaptic.types import EDGE_USE, KIND_TOOL_RESULT, KIND_TOOL_USE, PruneCard, WscParams

CARD_ID_PREFIX = "B"

#: 一张卡最多内联多少条文件路径。
#:
#: 原为 4（**丢弃**其余），归因实测（185 条 failure_site 漏失里 52 条）证明这是
#: 主要漏失源：Bash 单元的 refs 会把「命令串里提到的路径 + 输出里提到的路径」全部
#: 并进来，一个 `npm test && cat a b c` 型单元轻松超过 4 条，而被丢掉的那些路径
#: 在热层里**没有别的出口**（[MAIN] 只渲染 refs[0]、[PATHS] 有条数配额、
#: [WORKING SET] ≤12 条）⇒ 失败现场整条消失。8 条覆盖实测分布，代价约 +30–40 tok/张。
CARD_FILES_MAX = 8


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
				files=u.files[:CARD_FILES_MAX],
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
				files=tuple(dict.fromkeys(prev.files + c.files))[:CARD_FILES_MAX],
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
			files=tuple(dict.fromkeys(a.files + b.files))[:CARD_FILES_MAX],
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


def render_card(c: PruneCard, *, handles: Any = None) -> str:
	"""一张卡的热层文本（单行，便于前缀稳定）。

	句柄表达式由 `handles.HandleRenderer` 产出（**不在这里拼 `expand(...)`**：
	渲染形态与解析必须同源，见 `synaptic/handles.py` 的模块文档）。
	"""
	hr = renderer_or_default(handles)
	bits = [f"{c.card_id}:"]
	bits.append(c.conclusion)
	if c.files:
		bits.append(f"files={','.join(c.files)}")
	if c.error_sig:
		bits.append(f"err={c.error_sig[:80]}")
	if c.replay:
		bits.append(f"replay={c.replay[:100]}")
	bits.append(hr.expression(c.handle))
	return " ".join(bits)


def cards_tokens(cards: tuple[PruneCard, ...], *, handles: Any = None) -> int:
	return sum(node_token_len(render_card(c, handles=handles)) for c in cards)


#: 卡组内多条结论的分隔符（与 ``budget._EXCERPT_SEP`` 同款理由：可见、不歧义、
#: 不破坏「关键信息针按连续子串判定」）。
_CARD_SEP = " ⏐ "


def card_group_key(c: PruneCard) -> tuple[str, tuple[str, ...]]:
	"""卡组归并键：同错误签名 + 同文件集合。

	**只按事实字段归并，不按结论文本**——结论逐卡唯一（实测同回合重复率 0.0%），
	按文本归并等于不去重。
	"""
	return (c.error_sig, tuple(c.files))


def group_cards(cards: tuple[PruneCard, ...]) -> list[list[PruneCard]]:
	"""按 ``card_group_key`` 归并，保持**首次出现顺序**（前缀追加友好、确定性）。"""
	order: list[tuple[str, tuple[str, ...]]] = []
	groups: dict[tuple[str, tuple[str, ...]], list[PruneCard]] = {}
	for c in cards:
		k = card_group_key(c)
		if k not in groups:
			groups[k] = []
			order.append(k)
		groups[k].append(c)
	return [groups[k] for k in order]


def cards_handle(cards: list[PruneCard]) -> str:
	"""组句柄：**渲染与冷层绑定共用这一处**。

	两边各拼一次 ``branch://id1,id2`` 就会漂移——「行里写的句柄」与「绑定的节点集」
	不一致时可恢复性会被悄悄破坏，而往返比对照样通过（句柄自洽地错）。
	与 ``budget.request_chunk_ids`` 是同一条纪律。
	"""
	if len(cards) == 1:
		return cards[0].handle
	return BRANCH_PREFIX + ",".join(c.card_id for c in cards)


def render_card_group(cards: list[PruneCard], *, handles: Any = None) -> str:
	"""一组卡的热层文本（单行）。

	为什么合并：实测 `[PRUNED]` 1221 tok ÷ 24 卡 ≈ 51 tok/卡行，而单卡结论本身只有
	med 34 tok ⇒ **约 17 tok/卡是纯行开销**（``<id>:`` 前缀 + 句柄尾巴，且 id 在一行里出现两次）。
	行开销与结论长度无关，只能靠**合并行**压。

	合并后**每条结论仍逐字内联**——不做「只留首条」那种压缩，那会把结论文本针打掉，
	与 docs §13.4 的 `user` 针事故同型。只有前缀与句柄从 N 份降到 1 份；
	行尾句柄覆盖组内**全部**卡 ⇒ 展开仍逐字节无损。
	"""
	hr = renderer_or_default(handles)
	head = cards[0]
	bits = [_CARD_SEP.join(c.conclusion for c in cards)]
	if head.files:
		bits.append(f"files={','.join(head.files)}")
	if head.error_sig:
		bits.append(f"err={head.error_sig[:80]}")
	if head.replay:
		bits.append(f"replay={head.replay[:100]}")
	bits.append(hr.expression(cards_handle(cards)))
	return " ".join(bits)


def render_cards_merged(
	cards: tuple[PruneCard, ...], *, handles: Any = None
) -> list[tuple[str, str]]:
	"""``[PRUNED]`` 行列表：同组卡并成一行（组内 1 张时退化为原单卡形态）。"""
	out: list[tuple[str, str]] = []
	for group in group_cards(cards):
		key = group[0].card_id if len(group) == 1 else ",".join(c.card_id for c in group)
		out.append((f"cards:{key}", render_card_group(group, handles=handles)))
	return out
