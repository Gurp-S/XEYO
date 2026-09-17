"""证据 DAG 构建（规则 1：边工作边记录，不判断重要性）。

节点 = 消息；边 = 四类关系（seq / use / file / err）。构建阶段不做任何
保留/剪枝判断——所有价值判断推迟到评分与闭包阶段。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from synaptic.textutil import (
	classify_tool,
	command_paths,
	content_hash,
	extract_error_sig,
	extract_paths,
	extract_symbols,
	message_text,
	node_token_len,
	tool_input_paths,
	tool_result_blocks,
	tool_result_text,
	tool_use_blocks,
)
from synaptic.types import (
	EDGE_ERR,
	EDGE_FILE,
	EDGE_SEQ,
	EDGE_USE,
	KIND_ASST_TEXT,
	KIND_OTHER,
	KIND_TOOL_RESULT,
	KIND_TOOL_USE,
	KIND_USER,
	Edge,
	Node,
)

# 强错误标记（仅当消息未显式携带 is_error 时才用文本启发式）
_STRONG_ERR_MARKERS = (
	"traceback (most recent call last)",
	"permission denied",
	"command not found",
	"no such file or directory",
	"assertionerror",
	"exception:",
	"error:",
	"\nfailed",
	"exit code 1",
)


@dataclass(frozen=True)
class Graph:
	nodes: tuple[Node, ...]
	edges: tuple[Edge, ...]
	out_adj: dict[int, tuple[int, ...]]
	in_adj: dict[int, tuple[int, ...]]
	file_index: dict[str, tuple[int, ...]]  # path -> 按时间的节点序列
	by_use_id: dict[str, int]  # tool_use_id -> 承载该调用的节点 idx
	#: 按边类型预索引的邻接表 ``(idx, kind) -> (dst,)`` / ``(idx, kind) -> (src,)``。
	#:
	#: 存在的理由：``outgoing(idx, kind)`` 原先每次都要**线性扫全部边**，而它在
	#: 卡片生成阶段被调用上万次 ⇒ O(边数 × 调用数)。200 回合标准会话的 profile 里
	#: 这一条占总耗时约 20%。预索引后是 O(1) 查表，结果与线性扫描逐元素相同。
	out_kind: dict[tuple[int, str], tuple[int, ...]] = field(default_factory=dict)
	in_kind: dict[tuple[int, str], tuple[int, ...]] = field(default_factory=dict)

	def node(self, idx: int) -> Node | None:
		if 0 <= idx < len(self.nodes):
			return self.nodes[idx]
		return None

	def outgoing(self, idx: int, kind: str | None = None) -> tuple[int, ...]:
		out = self.out_adj.get(idx, ())
		if kind is None:
			return out
		hit = self.out_kind.get((idx, kind))
		if hit is not None:
			return hit
		return tuple(e.dst for e in self.edges if e.src == idx and e.kind == kind)

	def incoming(self, idx: int, kind: str | None = None) -> tuple[int, ...]:
		if kind is None:
			return self.in_adj.get(idx, ())
		hit = self.in_kind.get((idx, kind))
		if hit is not None:
			return hit
		return tuple(e.src for e in self.edges if e.dst == idx and e.kind == kind)


def _classify_message(
	msg: dict, name_by_id: dict[str, str]
) -> tuple[str, str, str, str, bool, bool, bool, str]:
	"""返回 (kind, role, tool_name, tool_use_id, is_error, is_write, read_only, error_sig)。"""
	uses = tool_use_blocks(msg)
	results = tool_result_blocks(msg)
	role_raw = str(msg.get("role") or "")
	if results:
		uid = str(results[0].get("tool_use_id") or "")
		name = name_by_id.get(uid, str(msg.get("name") or ""))
		text = "\n".join(tool_result_text(b) for b in results)
		flag = results[0].get("is_error")
		is_err = bool(flag) if flag is not None else _looks_like_error(text)
		# tool_result 节点本身不改盘也不可重放（重放的是那次调用）
		return (
			KIND_TOOL_RESULT,
			"tool",
			name,
			uid,
			is_err,
			False,
			False,
			extract_error_sig(text) if is_err else "",
		)
	if uses:
		names: list[str] = []
		ids: list[str] = []
		is_write = read_only = False
		replay = ""
		for u in uses:
			n = str(u.get("name") or "")
			i = str(u.get("id") or "")
			if n:
				names.append(n)
			if i:
				ids.append(i)
			w, ro, rc = classify_tool(n, u.get("input"))
			is_write = is_write or w
			read_only = read_only or ro
			if rc and not replay:
				replay = rc
		return (
			KIND_TOOL_USE,
			"assistant",
			",".join(dict.fromkeys(names)),
			ids[0] if ids else "",
			False,
			is_write,
			read_only and not is_write,
			replay,
		)
	if role_raw == "assistant":
		return (KIND_ASST_TEXT, "assistant", "", "", False, False, False, "")
	if role_raw in ("user", "human"):
		return (KIND_USER, "user", "", "", False, False, False, "")
	if role_raw in ("system", "tool"):
		return (KIND_OTHER, role_raw, "", "", False, False, False, "")
	return (KIND_OTHER, role_raw or "other", "", "", False, False, False, "")


def _looks_like_error(text: str) -> bool:
	if not text:
		return False
	low = text[:2000].lower()
	return any(m in low for m in _STRONG_ERR_MARKERS)


def build_graph(messages: list[dict], *, include_soft_edges: bool = True) -> Graph:
	"""从 API 形式的消息列构建证据图。

	``include_soft_edges`` 只控制启发式 ``seq/file/err`` 边是否进入图的邻接表。
	默认保持完整图，便于离线 oracle 与历史契约；WSC 的 ``project()`` 默认关闭，
	主线只消费语法确定的 ``tool_use -> tool_result`` provenance。
	"""
	# 第一遍：tool_use_id -> 工具名（tool_result 需要反查名字）
	name_by_id: dict[str, str] = {}
	for msg in messages:
		for u in tool_use_blocks(msg):
			uid = str(u.get("id") or "")
			if uid:
				name_by_id[uid] = str(u.get("name") or "tool")

	# 第二遍：建节点
	nodes: list[Node] = []
	for i, msg in enumerate(messages):
		kind, role, tool_name, uid, is_err, is_write, read_only, err_sig = _classify_message(
			msg, name_by_id
		)
		text = message_text(msg)
		# 抽取用的扫描窗口上限：超长工具输出（几十万字符）全量跑正则会主导回放耗时，
		# 而路径/符号在前 8k 字符内已基本出现完毕。
		scan = text[:8000]
		refs: list[str] = []
		replay_cmd = ""
		for u in tool_use_blocks(msg):
			inp = u.get("input")
			refs.extend(tool_input_paths(inp))
			refs.extend(command_paths(inp))
			_, _, rc = classify_tool(str(u.get("name") or ""), inp)
			if rc and not replay_cmd:
				replay_cmd = rc
		for r in tool_result_blocks(msg):
			refs.extend(extract_paths(tool_result_text(r)[:8000], limit=12))
		if not refs:
			refs.extend(extract_paths(scan, limit=12))
		refs = list(dict.fromkeys(p for p in refs if p))
		symbols = extract_symbols(scan, limit=12) if kind in (KIND_USER, KIND_ASST_TEXT) else ()
		ts = msg.get("ts")
		nodes.append(
			Node(
				idx=i,
				kind=kind,
				role=role,
				text=text,
				tokens=node_token_len(text),
				tool_name=tool_name,
				tool_use_id=uid,
				is_error=is_err,
				is_write=is_write,
				read_only=read_only,
				ts=float(ts) if isinstance(ts, (int, float)) else 0.0,
				refs=tuple(refs),
				symbols=tuple(symbols),
				error_sig=err_sig,
				replay_cmd=replay_cmd,
			)
		)

	# 第三遍：建边
	edges: list[Edge] = []
	by_use_id: dict[str, int] = {}
	for n in nodes:
		if n.kind == KIND_TOOL_USE and n.tool_use_id:
			by_use_id.setdefault(n.tool_use_id, n.idx)

	# 补 refs：tool_result 的「现场」由**发起它的调用**决定，不是由输出文本决定。
	# 只在输出文本自身没扫出路径时继承，避免把调用参数里的无关路径灌进结果节点。
	for n in nodes:
		if n.kind != KIND_TOOL_RESULT or not n.tool_use_id or n.refs:
			continue
		src = by_use_id.get(n.tool_use_id)
		if src is None:
			continue
		inherited = nodes[src].refs
		if inherited:
			nodes[n.idx] = replace(n, refs=inherited)

	# file_index 必须在 refs 补齐之后建，否则 err 边会漏掉一半现场
	file_index: dict[str, list[int]] = {}
	for n in nodes:
		for p in n.refs:
			file_index.setdefault(p, []).append(n.idx)

	if include_soft_edges:
		# seq：时序相邻
		for i in range(len(nodes) - 1):
			edges.append(Edge(i, i + 1, EDGE_SEQ, 0.4))

	# use：tool_use -> tool_result（语法因果边；对应生产链 memindex.edges 的那条）
	pending: list[int] = []
	for n in nodes:
		if n.kind == KIND_TOOL_USE:
			pending.append(n.idx)
		elif n.kind == KIND_TOOL_RESULT:
			if n.tool_use_id and n.tool_use_id in by_use_id:
				edges.append(Edge(by_use_id[n.tool_use_id], n.idx, EDGE_USE, 1.0))
			elif pending:
				edges.append(Edge(pending[-1], n.idx, EDGE_USE, 0.6))
			if pending:
				pending.pop()

	if include_soft_edges:
		# file：同一路径的相邻两次访问（共访链）
		for p, idxs in file_index.items():
			for a, b in zip(idxs, idxs[1:]):
				if a != b:
					edges.append(Edge(a, b, EDGE_FILE, 0.5))

	if include_soft_edges:
		# err：失败结果 -> 之后首次触碰同一路径的调用（错误归因启发式）
		for n in nodes:
			if not n.is_error or not n.refs:
				continue
			cands = [
				j
				for p in n.refs
				for j in file_index.get(p, ())
				if j > n.idx and nodes[j].kind == KIND_TOOL_USE
			]
			if cands:
				edges.append(Edge(n.idx, min(cands), EDGE_ERR, 0.8))

	# 邻接表（确定性顺序：按边序）+ 按边类型预索引（``outgoing/incoming(kind=…)`` 的 O(1) 通道）
	out_map: dict[int, list[int]] = {}
	in_map: dict[int, list[int]] = {}
	out_kind: dict[tuple[int, str], list[int]] = {}
	in_kind: dict[tuple[int, str], list[int]] = {}
	for e in edges:
		out_map.setdefault(e.src, []).append(e.dst)
		in_map.setdefault(e.dst, []).append(e.src)
		out_kind.setdefault((e.src, e.kind), []).append(e.dst)
		in_kind.setdefault((e.dst, e.kind), []).append(e.src)

	return Graph(
		nodes=tuple(nodes),
		edges=tuple(edges),
		out_adj={k: tuple(dict.fromkeys(v)) for k, v in out_map.items()},
		in_adj={k: tuple(dict.fromkeys(v)) for k, v in in_map.items()},
		file_index={k: tuple(v) for k, v in file_index.items()},
		by_use_id=by_use_id,
		out_kind={k: tuple(dict.fromkeys(v)) for k, v in out_kind.items()},
		in_kind={k: tuple(dict.fromkeys(v)) for k, v in in_kind.items()},
	)


def graph_digest(graph: Graph) -> str:
	"""图结构摘要（确定性；用于快照断言）。"""
	import hashlib

	parts = [f"n={len(graph.nodes)}", f"e={len(graph.edges)}"]
	for n in graph.nodes:
		parts.append(f"{n.idx}:{n.kind}:{n.tokens}:{content_hash(n.text)}")
	for e in graph.edges:
		parts.append(f"{e.src}>{e.dst}:{e.kind}")
	blob = "\n".join(parts)
	return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]
