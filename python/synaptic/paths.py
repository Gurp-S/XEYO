"""路径索引段 ``[PATHS]``（P0-1）：给「还在用的路径」一条必然可见的渲染通道。

背景（第五轮串行基线实测）：``path`` 针存活率 **0.6106**、``path_recent`` **0.6946**，
是最大的信息留存缺口（DOD 目标 0.75 / 0.85）。

根因不是「预算不够」，而是**通道不够**。区域内路径原先只有三条渲染通道：

1. ``[WORKING SET]``：只渲染 ``working_set`` 选出的 ≤12 条文件状态；
2. ``[MAIN]`` 骨架行：``_skeleton_of`` 只取 ``node.refs[0]``，且只对进了 ``kept`` 的节点；
3. 剪枝卡：只对**被剪**节点生成的卡里带 ``files``。

于是「最近碰过、但既没进 working set 也没进 kept 的路径」在热层里彻底消失——
它是活的依赖信息（下一步大概率还要碰它），却因为不在闭包里而被丢掉。

本模块提供第四条通道，并把它做成**强制配额**：候选池按「最近触碰 → 失败现场 →
保留节点 → 钉住路径」的优先级取前 ``path_index_limit`` 条，配额内的路径**必然发射**，
不受闭包/背包选择影响。

两个刻意的确定性/前缀友好设计：

* **渲染形态 = 最短唯一后缀**（``src/auth.ts`` 只写 ``auth.ts``；有同名时自动加长到唯一）。
  后缀的唯一性以**同一个候选池**为全集判定，因此不会产生歧义，也不会把两条路径压成一行。
* **发射顺序 = 首次出现下标升序**（不是「最近优先」）。这样新路径永远追加在段尾，
  段内不会因为「某条路径又被碰了一次」而整体重排——KV 前缀只在追加时被延长。
  选谁进配额仍按「最近触碰」优先，两个口径分工明确。
"""

from __future__ import annotations

from synaptic.graph import Graph
from synaptic.seeds import Seeds, recent_paths
from synaptic.textutil import node_token_len
from synaptic.types import WscParams

H_PATHS = "[PATHS]"

Line = tuple[str, str]


def shortest_unique_suffix(path: str, others: frozenset[str]) -> str:
	"""把路径压成在同池内唯一的最短后缀；无法唯一时回落全路径。"""
	parts = [p for p in str(path or "").split("/") if p]
	if not parts:
		return str(path or "")
	for n in range(1, len(parts) + 1):
		cand = "/".join(parts[-n:])
		clash = False
		for other in others:
			if other == path:
				continue
			if other == cand or other.endswith("/" + cand):
				clash = True
				break
		if not clash:
			return cand
	return "/".join(parts)


def _touch_span(graph: Graph, region_end: int) -> dict[str, tuple[int, int]]:
	"""路径 -> (首次出现下标, 最后触碰下标)，只统计区域内节点。"""
	first: dict[str, int] = {}
	last: dict[str, int] = {}
	for n in graph.nodes:
		if n.idx >= region_end:
			continue
		for p in n.refs:
			if p not in first:
				first[p] = n.idx
			last[p] = n.idx
	return {p: (first[p], last[p]) for p in first}


def render_paths(
	graph: Graph,
	seeds: Seeds,
	*,
	region_end: int,
	kept: tuple[int, ...],
	params: WscParams,
) -> list[Line]:
	"""返回 ``[PATHS]`` 的行列表（可能为空）。

	候选池优先级（同一层内按「最后触碰下标降序」取，确定性平局用路径字典序）：

	1. ``recent_paths``：区域内后 25% 触碰过的路径（= ``path_recent`` 针的集合本身）；
	2. 失败现场：出现错误的节点触碰过的路径（同时支撑 ``failure_site`` 针）；
	3. ``kept`` 节点触碰过的路径（闭包真正认为有用的）；
	4. ``seeds.pin_paths``（目标/约束涉及、或状态过期、或带未解错误）。

	配额：``params.path_index_limit`` 条 + ``params.path_index_budget_tokens`` token 上限，
	两者都从尾部裁（尾部 = 优先级最低）。裁剪只影响可见性配额，不改任何删除/剪枝决策，
	因此不可能破坏可恢复性（被裁掉的路径仍在冷层可达）。
	"""
	span = _touch_span(graph, region_end)
	if not span:
		return []

	recent = {p for p in recent_paths(graph, region_end=region_end) if p in span}
	fail: set[str] = set()
	for n in graph.nodes:
		if n.idx >= region_end or not n.is_error:
			continue
		fail.update(p for p in n.refs if p in span)
	kept_paths: set[str] = set()
	for idx in kept:
		node = graph.node(idx)
		if node is None:
			continue
		kept_paths.update(p for p in node.refs if p in span)
	pinned = {p for p in seeds.pin_paths if p in span}

	rank: dict[str, tuple[int, int, str]] = {}
	for tier, group in enumerate((recent, fail, kept_paths, pinned)):
		for p in group:
			first, last = span[p]
			cur = rank.get(p)
			cand = (tier, -last, p)
			if cur is None or cand < cur:
				rank[p] = cand

	ordered = sorted(rank, key=lambda p: rank[p])
	# 两个维度的上限都是「正数 = 上限；0 或负数 = 该段不发」。可疑配置一律按保守方向处理：
	# 宁可不发这一段，也不让它悄悄超预算占掉 [MAIN] 的额度。
	limit = max(0, int(params.path_index_limit))
	budget = max(0, int(params.path_index_budget_tokens))
	if limit <= 0 or budget <= 0:
		return []
	ordered = ordered[:limit]
	pool = frozenset(span)
	lines: list[Line] = []
	tokens = 0
	# 渲染顺序：首次出现升序（追加友好）；选谁已在上面按优先级定好
	for p in sorted(ordered, key=lambda x: (span[x][0], x)):
		suffix = shortest_unique_suffix(p, pool)
		line = suffix
		cost = node_token_len(line) + 1
		if tokens + cost > budget:
			break
		tokens += cost
		lines.append((f"path:{p}", line))
	return lines
