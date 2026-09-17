"""确定性历史发现：把当前状态转换为可审计的历史候选。

这个模块只负责回答「哪些历史可能与当前状态直接相关、为什么相关、在哪里」；
不负责预算选择、热层排序或替模型决定是否读取。这样可以把三件事分开：

* ``Seeds`` / ``FileState``：当前状态的来源；
* ``HistoryQuery``：本轮检索的明确输入；
* ``HistoryCandidate``：候选历史及其来源理由。

检索只使用显式信号：用户节点、约束原文、未解决错误签名、明确路径，以及
``tool_use -> tool_result`` 硬 provenance。不会因为时间相邻、关键词相似或同一
文件就推断因果；路径命中只说明「涉及同一显式路径」。

本模块不接入生产链，也不改变现有 projection。它是 algorithm-side 的旁路，供
后续的历史入口渲染和行为实验使用。
"""

from __future__ import annotations

from dataclasses import dataclass

from synaptic.coldstore import node_handle
from synaptic.graph import Graph
from synaptic.seeds import Seeds
from synaptic.types import EDGE_USE, FileState


@dataclass(frozen=True)
class CurrentState:
	"""从现有种子和文件状态整理出的当前状态视图。

	它不是历史 Journal，也不是 selector 的结果。`working_paths` 由调用方提供时，
	表示本轮明确的工作集；未提供时退回文件状态表中的路径。状态只携带可由现有
	结构确定的事实，不生成自然语言结论。
	"""

	goal: str = ""
	constraints: tuple[str, ...] = ()
	unresolved_errors: tuple[str, ...] = ()
	todos: tuple[str, ...] = ()
	working_paths: tuple[str, ...] = ()
	stale_paths: tuple[str, ...] = ()
	request_nodes: tuple[int, ...] = ()
	anchor_nodes: tuple[int, ...] = ()


def build_current_state(
	seeds: Seeds,
	file_states: dict[str, FileState],
	*,
	working_paths: tuple[str, ...] = (),
) -> CurrentState:
	"""从现有 ``Seeds`` / ``FileState`` 构造当前状态，不读取 selection 结果。"""
	path_source = working_paths or tuple(file_states)
	paths = tuple(dict.fromkeys(str(path) for path in path_source if str(path).strip()))
	stale = tuple(
		path
		for path, state in file_states.items()
		if state.stale or bool(state.related_errors)
	)
	return CurrentState(
		goal=str(seeds.goal or ""),
		constraints=tuple(seeds.constraints),
		unresolved_errors=tuple(seeds.unresolved_errors),
		todos=tuple(seeds.todos),
		working_paths=paths,
		stale_paths=tuple(dict.fromkeys(stale)),
		request_nodes=tuple(dict.fromkeys(seeds.user_nodes)),
		anchor_nodes=tuple(dict.fromkeys(seeds.pin_nodes)),
	)


@dataclass(frozen=True)
class HistoryQuery:
	"""一次历史发现的完整、可序列化输入。"""

	region_end: int
	anchor_nodes: tuple[int, ...] = ()
	request_nodes: tuple[int, ...] = ()
	constraints: tuple[str, ...] = ()
	unresolved_errors: tuple[str, ...] = ()
	paths: tuple[str, ...] = ()
	max_candidates: int = 64


def build_history_query(
	state: CurrentState,
	*,
	region_end: int,
	max_candidates: int = 64,
) -> HistoryQuery:
	"""把当前状态转换为检索输入。

	``request_nodes`` 单独保留，避免调用方把「当前用户原话」和一般锚点混为一谈。
	"""
	return HistoryQuery(
		region_end=max(0, int(region_end)),
		anchor_nodes=tuple(dict.fromkeys(state.anchor_nodes)),
		request_nodes=tuple(dict.fromkeys(state.request_nodes)),
		constraints=tuple(dict.fromkeys(x for x in state.constraints if x.strip())),
		unresolved_errors=tuple(
			dict.fromkeys(x for x in state.unresolved_errors if x.strip())
		),
		paths=tuple(
			dict.fromkeys(
				x for x in (*state.working_paths, *state.stale_paths) if str(x).strip()
			)
		),
		max_candidates=max(0, int(max_candidates)),
	)


@dataclass(frozen=True)
class HistoryCandidate:
	"""一个历史候选及其可审计来源。"""

	idx: int
	reasons: tuple[str, ...]
	matched_keys: tuple[str, ...] = ()
	source_nodes: tuple[int, ...] = ()
	handle: str = ""


_REASON_RANK = {
	"state_anchor": 0,
	"constraint_exact": 1,
	"unresolved_error_exact": 2,
	"hard_provenance": 3,
	"working_path_exact": 4,
}


def discover_history(graph: Graph, query: HistoryQuery) -> tuple[HistoryCandidate, ...]:
	"""按显式状态线索发现候选历史，结果完全确定且不做语义推断。

	候选发现和候选选择刻意分开：这里最多返回 ``max_candidates`` 条入口，预算、
	热层位置和是否自动读取仍由调用方决定。候选按「状态直接来源 → 硬来源关系 →
	路径证据」排序，同层按风险和最新节点优先，最后用节点下标稳定裁决。
	"""
	limit = min(max(0, int(query.region_end)), len(graph.nodes))
	if query.max_candidates <= 0 or limit <= 0:
		return ()

	anchor = {idx for idx in query.anchor_nodes if 0 <= idx < limit}
	paths = {str(path) for path in query.paths if str(path).strip()}
	errors = {str(sig) for sig in query.unresolved_errors if str(sig).strip()}
	constraints = tuple(x.strip() for x in query.constraints if x.strip())
	data: dict[int, dict[str, set]] = {}

	def add(
		idx: int,
		reason: str,
		*,
		keys: tuple[str, ...] = (),
		sources: tuple[int, ...] = (),
	) -> None:
		if not 0 <= idx < limit:
			return
		entry = data.setdefault(
			idx,
			{"reasons": set(), "keys": set(), "sources": set()},
		)
		entry["reasons"].add(reason)
		entry["keys"].update(keys)
		entry["sources"].update(sources)

	for idx in sorted(anchor):
		add(idx, "state_anchor", sources=(idx,))

	# 约束只做原文包含匹配；不把关键词重叠当作语义相关。
	for node in graph.nodes[:limit]:
		if not node.text.strip():
			continue
		for constraint in constraints:
			if constraint in node.text:
				add(node.idx, "constraint_exact", keys=(f"constraint:{constraint[:80]}",))

		if node.is_error and node.error_sig and node.error_sig in errors:
			add(
				node.idx,
				"unresolved_error_exact",
				keys=(f"error:{node.error_sig}",),
			)

		matched_paths = tuple(sorted(paths.intersection(node.refs)))
		if matched_paths:
			add(
				node.idx,
				"working_path_exact",
				keys=tuple(f"path:{path}" for path in matched_paths),
			)

	# 只沿硬 provenance 关系扩展，不沿 seq/file/err 软边扩展。
	for source in sorted(anchor):
		for idx in graph.incoming(source, EDGE_USE):
			add(idx, "hard_provenance", sources=(source,))
		for idx in graph.outgoing(source, EDGE_USE):
			add(idx, "hard_provenance", sources=(source,))

	def priority(idx: int) -> tuple[int, int, int]:
		node = graph.node(idx)
		entry = data[idx]
		rank = min(_REASON_RANK[r] for r in entry["reasons"])
		# 错误和写入是显式高风险证据；同风险取最新节点。
		risk = 0 if node is not None and node.is_error else 1 if node is not None and node.is_write else 2
		return rank, risk, -idx

	out: list[HistoryCandidate] = []
	for idx in sorted(data, key=priority)[: query.max_candidates]:
		entry = data[idx]
		out.append(
			HistoryCandidate(
				idx=idx,
				reasons=tuple(sorted(entry["reasons"], key=lambda x: _REASON_RANK[x])),
				matched_keys=tuple(sorted(entry["keys"])),
				source_nodes=tuple(sorted(entry["sources"])),
				handle=node_handle(idx),
			)
		)
	return tuple(out)


__all__ = [
	"CurrentState",
	"HistoryCandidate",
	"HistoryQuery",
	"build_current_state",
	"build_history_query",
	"discover_history",
]
