"""反向依赖闭包 + 五维加权评分 + 确定性背包近似选择（规则 2）。

与「选最长链」的分野：候选集来自种子在 DAG 上的**反向 k 跳可达**，而不是
消息位置；位置的权重（recency）只是五维之一，且被刻意压到最低。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from synaptic.graph import Graph
from synaptic.memo import Memo
from synaptic.seeds import Seeds
from synaptic.textutil import node_token_len
from synaptic.types import (
	W_CONSTRAINT,
	W_GOAL,
	W_RECENCY,
	W_REPLAY,
	W_UNRESOLVED,
	WscParams,
)

_LATIN_RE = re.compile(r"[A-Za-z0-9_]{3,}")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_STOP = frozenset(
	{"the", "and", "for", "with", "this", "that", "from", "have", "not", "are", "was", "you"}
)

#: ``keywords`` 的记忆表（进程内、有界、不落盘）。见 ``synaptic/memo.py`` 的说明。
_KEYWORD_MEMO = Memo()


def keywords(text: str, *, limit: int = 400) -> set[str]:
	"""确定性关键词集：拉丁词（≥3）+ 中文 bigram + 路径。

记忆化：本函数每轮要对**整段历史**的每个节点各跑一次正则，而相邻两轮的输入
只差最后几条消息。输入是纯文本、输出只取决于输入 ⇒ 记忆化只改变耗时。
返回的是**同一个 set 对象**，调用方只做读操作（交集/长度），不得原地修改。
	"""
	if not text:
		return set()
	return _KEYWORD_MEMO.get_or((text, limit), lambda: _keywords_uncached(text, limit=limit))


def _keywords_uncached(text: str, *, limit: int = 400) -> set[str]:
	out: set[str] = set()
	if not text:
		return out
	low = text.lower()
	for m in _LATIN_RE.finditer(low):
		w = m.group(0)
		if w not in _STOP and not w.isdigit():
			out.add(w)
		if len(out) >= limit:
			return out
	for m in _CJK_RUN_RE.finditer(text):
		run = m.group(0)
		for i in range(len(run) - 1):
			out.add(run[i : i + 2])
		if len(out) >= limit:
			return out
	return out


@dataclass(frozen=True)
class Scored:
	"""一个节点的五维评分明细（审计留痕）。"""

	idx: int
	dims: dict[str, float]
	total: float
	tokens: int

	@property
	def density(self) -> float:
		return self.total / max(1, self.tokens)


@dataclass
class Selection:
	kept: tuple[int, ...]
	pruned: tuple[int, ...]
	candidates: tuple[int, ...]
	scores: dict[int, Scored]
	budget_tokens: int
	used_tokens: int
	reason: dict[int, str] = field(default_factory=dict)


def backward_closure(
	graph: Graph,
	seeds: tuple[int, ...],
	hops: int,
	*,
	edge_kinds: Iterable[str] | None = None,
) -> set[int]:
	"""种子在指定边集上的反向 k 跳可达集。

	不传 ``edge_kinds`` 时保留完整图的历史 API；WSC 默认由 ``plan_selection``
	传入 hard-use provenance，避免 soft DAG 的启发式关联改变主线选择。
	"""
	if not seeds or hops <= 0:
		return set(seeds)
	kinds = frozenset(edge_kinds) if edge_kinds is not None else None
	seen: set[int] = set(seeds)
	frontier: set[int] = set(seeds)
	for _ in range(max(1, hops)):
		nxt: set[int] = set()
		for idx in sorted(frontier):
			if kinds is None:
				sources = graph.in_adj.get(idx, ())
			else:
				sources = tuple(
					src for kind in sorted(kinds) for src in graph.incoming(idx, kind)
				)
			for src in sources:
				if src not in seen:
					seen.add(src)
					nxt.add(src)
		if not nxt:
			break
		frontier = nxt
	return seen


def score_nodes(
	graph: Graph,
	seeds: Seeds,
	params: WscParams,
	*,
	region_end: int,
	reachable: set[int],
	unresolved_set: set[int],
) -> dict[int, Scored]:
	"""五维加权评分。全部维度归一化到 [0,1]，权重显式来自 params。"""
	seed_text = "\n".join(
		[seeds.goal, *seeds.constraints, *seeds.unresolved_errors, *seeds.todos]
	)
	seed_kw = keywords(seed_text)
	seed_paths = set(seeds.pin_paths)
	pin_set = set(seeds.pin_nodes)
	denom = max(1, len(seed_kw))
	span = max(1, region_end - 1)

	out: dict[int, Scored] = {}
	for n in graph.nodes:
		if n.idx >= region_end:
			continue
		# goal_rel：关键词交集 + 路径命中（扫描窗口限 4k，避免超长工具输出主导耗时）
		kw = keywords(n.text[:4000], limit=200)
		ref_hit = any(ref in seed_paths for ref in n.refs)
		inter = len(kw & seed_kw)
		goal_rel = min(1.0, (inter / denom) * 3.0 + (0.4 if ref_hit else 0.0))

		# unresolved：自身是未解决错误，或 1 跳内可达未解决错误
		unresolved = 1.0 if n.idx in unresolved_set else 0.0
		if unresolved == 0.0 and n.idx in reachable:
			if any(d in unresolved_set for d in graph.out_adj.get(n.idx, ())):
				unresolved = 0.5

		# constraint：用户消息本身，或与带约束的用户消息相邻
		constraint = 0.0
		if n.role == "user":
			constraint = 0.4
		if n.idx in pin_set and n.role == "user":
			constraint = 1.0
		if seeds.constraints and any(c[:24] in n.text for c in seeds.constraints):
			constraint = 1.0

		# recency：刻意压低权重的位置项
		recency = n.idx / span

		# replay_cost：不可重放/有副作用的一律高分（重做代价高）
		replay_cost = 0.0
		if n.is_write:
			replay_cost = 1.0
		elif n.read_only:
			replay_cost = 0.1
		elif n.kind == "tool_result":
			replay_cost = 0.5

		dims = {
			W_GOAL: goal_rel,
			W_UNRESOLVED: unresolved,
			W_CONSTRAINT: constraint,
			W_RECENCY: recency,
			W_REPLAY: replay_cost,
		}
		total = (
			params.w_goal * goal_rel
			+ params.w_unresolved * unresolved
			+ params.w_constraint * constraint
			+ params.w_recency * recency
			+ params.w_replay * replay_cost
		)
		out[n.idx] = Scored(idx=n.idx, dims=dims, total=total, tokens=n.tokens)
	return out


def knapsack_select(
	graph: Graph,
	scores: dict[int, Scored],
	*,
	candidates: set[int],
	must_keep: set[int],
	budget_tokens: int,
	charge: dict[int, int] | None = None,
	reason: dict[int, str] | None = None,
) -> Selection:
	"""确定性背包近似：按「分数/体积」密度贪心，同密度按 idx 升序。

不做随机化、不做浮点抖动——同输入必同输出。

``charge`` 是「发射成本」覆盖表（见 assemble.emitted_tokens）。不传时回落
原文 token，但那是错的记账——已进 PIN 的节点在热层里几乎不占空间。
	"""
	rsn = reason if reason is not None else {}
	chg = charge or {}

	def cost(idx: int) -> int:
		node = graph.node(idx)
		if node is None:
			return 0
		return int(chg.get(idx, node.tokens))

	kept: list[int] = []
	used = 0
	for idx in sorted(must_keep):
		if graph.node(idx) is None:
			continue
		kept.append(idx)
		used += cost(idx)
		rsn.setdefault(idx, "PIN/闭包必需")

	rest = [i for i in candidates if i not in must_keep]
	rest.sort(key=lambda i: (-scores[i].density if i in scores else 0.0, i))
	for idx in rest:
		c = cost(idx)
		if used + c > budget_tokens:
			rsn[idx] = "预算不足落选"
			continue
		kept.append(idx)
		used += c
		sc = scores.get(idx)
		rsn.setdefault(idx, f"密度入围 (score={sc.total:.3f})" if sc else "密度入围")

	kept_set = set(kept)
	pruned = sorted(i for i in candidates if i not in kept_set)
	for i in pruned:
		rsn.setdefault(i, "闭包外剪枝")
	return Selection(
		kept=tuple(sorted(kept_set)),
		pruned=tuple(pruned),
		candidates=tuple(sorted(candidates)),
		scores=scores,
		budget_tokens=budget_tokens,
		used_tokens=used,
		reason=rsn,
	)


def plan_selection(
	graph: Graph,
	seeds: Seeds,
	params: WscParams,
	*,
	region_end: int,
	budget_tokens: int,
	unresolved_set: set[int],
) -> Selection:
	"""从种子出发的完整选择流程（闭包 → 评分 → 背包）。"""
	from synaptic.assemble import emitted_tokens

	seed_nodes = tuple(sorted(set(seeds.pin_nodes)))
	edge_kinds = None
	if not params.soft_dag:
		from synaptic.types import EDGE_USE

		edge_kinds = (EDGE_USE,)
	reachable = backward_closure(
		graph,
		seed_nodes,
		params.closure_hops,
		edge_kinds=edge_kinds,
	)
	# 候选 = 可达集 ∪ 闭包外全体（闭包外节点仍参与竞争，只是没有可达加成）
	candidates = {n.idx for n in graph.nodes if n.idx < region_end}
	must_keep = set(seed_nodes) | {i for i in reachable if graph.nodes[i].is_error}
	scores = score_nodes(
		graph,
		seeds,
		params,
		region_end=region_end,
		reachable=reachable,
		unresolved_set=unresolved_set,
	)
	pin_set = set(seeds.pin_nodes)
	charge = {
		n.idx: emitted_tokens(n, params, is_pin=n.idx in pin_set)
		for n in graph.nodes
		if n.idx < region_end
	}
	sel = knapsack_select(
		graph,
		scores,
		candidates=candidates,
		must_keep=must_keep,
		budget_tokens=budget_tokens,
		charge=charge,
	)
	# 闭包可达但落选的节点，理由标注为可达但预算不足（便于审计阅读）
	for idx in sel.pruned:
		if idx in reachable:
			sel.reason[idx] = "闭包可达但预算不足"
	return sel


def selection_digest(sel: Selection) -> str:
	"""选择结果的确定性摘要（快照断言用）。"""
	import hashlib

	parts = [f"budget={sel.budget_tokens}", f"used={sel.used_tokens}"]
	parts += [f"k:{i}" for i in sel.kept]
	parts += [f"p:{i}" for i in sel.pruned]
	return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def audit_rows(graph: Graph, sel: Selection) -> list[dict[str, Any]]:
	"""把「入围/落选」的理由摊平成可写进报告的表格（可审计性要求）。"""
	rows: list[dict[str, Any]] = []
	for idx, sc in sorted(sel.scores.items()):
		node = graph.node(idx)
		if node is None:
			continue
		rows.append(
			{
				"idx": idx,
				"kind": node.kind,
				"tool": node.tool_name,
				"tokens": node.tokens,
				"kept": idx in set(sel.kept),
				"score": round(sc.total, 4),
				"density": round(sc.density, 6),
				"dims": {k: round(v, 3) for k, v in sc.dims.items()},
				"reason": sel.reason.get(idx, ""),
			}
		)
	return rows


def estimate_card_tokens(text: str) -> int:
	return node_token_len(text)
