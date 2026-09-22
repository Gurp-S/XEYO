"""证据 DAG 构建（规则 1：边工作边记录，不判断重要性）。

节点 = 消息；边 = 四类关系（seq / use / file / err）。构建阶段不做任何
保留/剪枝判断——所有价值判断推迟到评分与闭包阶段。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from synaptic.textutil import (
	classify_tool,
	command_paths,
	content_hash,
	extract_error_sig,
	extract_paths,
	extract_symbols,
	is_noise_path,
	suffix_chain_canonical,
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
	"verification failed",
)

# 退出码错误（**必须带非零码**）：`Process exited with code 1` / `exit code 137` /
# `exited with code 2`。原先只有字面量 `"exit code 1"`，于是 `process exited with
# code 1` 这类最常见的失败文本全部漏判（本语料 24 次真实失败 → is_error 判定 0 个）。
_ERR_EXIT_RE = re.compile(r"exit(?:ed)?\s*(?:with\s*)?code\s*([1-9]\d*)")

#: 输出**头部**的机器状态行（工具回执格式）：存在即权威。
_STATUS_EXIT_RE = re.compile(r"process exited with code (\d+)")


def _status_verdict(text: str) -> bool | None:
	"""头部状态行给出的判定：非零码 ⇒ 失败，0 ⇒ 成功；没有状态行返回 ``None``。

	为什么需要它：工具输出经常**引用含 ``Permission denied:`` / ``Traceback`` 的源码
	或日志**——纯文本启发式会把「成功读出的一段权限代码」判成失败（本语料 2 例）。
	头部退出码是唯一无歧义的机器判据，出现即覆盖其它信号。
	"""
	m = _STATUS_EXIT_RE.search(str(text or "")[:300].lower())
	if m is None:
		return None
	return m.group(1) != "0"

# 硬证据标记（无歧义）：显式 ``is_error: false`` 但文本铁证是失败时，**升格**为错误。
#
# 存在理由（真实根因）：Codex 形态的 transcript 把**每一次**工具输出都标成
# ``is_error: false``（本语料 39/39），于是 ``flag is not None`` 分支永远短路掉文本
# 启发式 —— 24 次真实失败全部漏判、[UNRESOLVED] 恒空。显式标记只允许**升格**，
# 不允许把有硬证据的失败降格成成功。
_HARD_ERR_MARKERS = (
	"traceback (most recent call last)",
	"permission denied",
	"command not found",
	"no such file or directory",
	"assertionerror",
	"verification failed",
)

#: 宿主**回执信封**自己写的结构化退出码（Codex 形态）：
#: ``Script completed\nWall time …\nOutput:\n\n{"chunk_id":…,"exit_code":1,…,"output":"…"}``。
#:
#: 为什么 ``_STATUS_EXIT_RE`` 盖不住它：信封头部的 ``Script completed`` 描述的是
#: 「信封成功送达」，不是被跑那条命令的退出状态——真状态在正文 JSON 的前几个键里。
#: 实测语料 8 条 ``exit_code:1`` 全是这个形状，头部却一律写 completed。
#:
#: 为什么要卡「必须出现在 ``"output"`` 之前」：被运行的程序自己也会打印含
#: ``exit_code`` 的 JSON（实测 msg#220 的 ``output`` 里就嵌着一层），那属于正文内容、
#: 不是机器回执，按 ``_status_verdict`` 同源的理由不许当判据。
_RECEIPT_ENV_RE = re.compile(r'"chunk_id"\s*:', re.I)
_RECEIPT_EXIT_RE = re.compile(r'"exit_code"\s*:\s*(\d+)')


def _receipt_verdict(text: str) -> bool | None:
	"""回执信封给出的判定：非零码 ⇒ 失败，0 ⇒ 成功；没有信封返回 ``None``。"""
	head = str(text or "")[:300]
	env = _RECEIPT_ENV_RE.search(head)
	if env is None:
		return None
	cut = head.find('"output"', env.end())
	scope = head[env.end():cut if cut > 0 else len(head)]
	m = _RECEIPT_EXIT_RE.search(scope)
	if m is None:
		return None
	return m.group(1) != "0"


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
	#: 建图前被「来源过滤」剔除的噪音路径（去噪审计用；不影响图结构）。
	noise_refs: tuple[str, ...] = ()
	#: 路径变体归并的 ``(原写法, 最短写法)`` 对（去噪审计用）。
	refs_merged: tuple[tuple[str, str], ...] = ()

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


#: 每个动词「哪些非零退出码属于**正常语义**」（不在表内的码一律按失败处理）。
#: 这是「动词 + 参数/退出码」判语义的第一层，替代原先「非零 ⇒ 可疑失败」的粗判。
_VERB_NORMAL_CODES: dict[str, frozenset[int]] = {
	"rg": frozenset({1}),            # 1 = 没有匹配（2 = 真出错）
	"grep": frozenset({1}),
	"findstr": frozenset({1}),
	"select-string": frozenset({1}),
	"git diff": frozenset({1}),      # 1 = 有差异
	"git grep": frozenset({1}),      # 1 = 没有匹配
	"compare-object": frozenset({1}),
	"diff": frozenset({1}),
	"fc": frozenset({1}),
	"test-path": frozenset({1}),     # 1 = 路径不存在
	"get-childitem": frozenset({1}), # 管道下游无匹配 / 个别路径被静默忽略
	"get-nettcpconnection": frozenset({1}),
}

#: 需要**正文形状确认**才能降格的动词：`git diff` 返回 1 是因为「有差异」，
#: 那就必须真的看到 diff 正文；看不到（例如 "Not a git repository"）就不是这个语义。
_VERB_NEEDS_BODY_CONFIRM: dict[str, "re.Pattern[str]"] = {
	"git diff": re.compile(r"(?m)^(?:diff --git |index |--- |\+\+\+ |@@ )"),
	"diff": re.compile(r"(?m)^(?:\d+(?:,\d+)?[acd]|\+\+\+ |--- |@@ )"),
}

#: 第二层的**结构化错误记录**：只认这些形状，不再用「某行含 error」的关键词扫描
#: （`error_handler.py`、日志文本、diff 里被删掉的 `error:` 行都会让关键词扫描误命中）。
_ERROR_RECORD_RE = re.compile(
	r"(?im)"
	r"(?:\+\s*(?:CategoryInfo|FullyQualifiedErrorId)\b)"
	r"|(?:^\s*At line:\s)"
	r"|(?:^\s*Line \|\s*$)"
	r"|(?:^\s*[A-Za-z][A-Za-z0-9_.\-]*(?:Error|Exception|Unavailable)\s*:)"
	r"|(?:^\s*(?:Access to the path\b.{0,160}?\bis denied\b))"
	r"|(?:^\s*(?:access|permission) denied\b)"
	r"|(?:\[Errno 13\])"
	r"|(?:\bnot recognized\b)"
	r"|(?:\bunable to (?:create|find|open|process|locate|resolve)\b)"
	r"|(?:\btraceback \(most recent call last\)\b)"
	r"|(?:\b(?:ModuleNotFound|Import|Syntax|Type|Value|Name|FileNotFound|UnicodeDecode"
	r"|Attribute|Key|Index)Error\b)"
	r"|(?:\bcommand not found\b)"
	r"|(?:^\s*(?:fatal|error)\s*:)"
)

#: 调用方显式要求忽略错误的参数（-ErrorAction SilentlyContinue / Ignore）。
_SILENCE_RE = re.compile(r"-ErrorAction\s+(?:SilentlyContinue|Ignore)\b", re.I)

#: 工具回执头部（Chunk ID / Wall time / 退出码 / Original token count）——判正文时先剥掉。
_HEADER_END = "Output:"


def _output_body(text: str) -> str:
	"""剥掉工具回执头部，只留输出正文。"""
	s = str(text or "")
	i = s.find(_HEADER_END)
	return s[i + len(_HEADER_END):] if i >= 0 else s


def _status_code(text: str) -> int | None:
	"""头部状态行的退出码；没有状态行返回 ``None``。"""
	m = _STATUS_EXIT_RE.search(str(text or "")[:300].lower())
	return int(m.group(1)) if m else None


def _normal_nonzero_verb(command: str) -> str:
	"""命令的动词（`git diff` 视作一个动词）；不在语义表里返回空串。"""
	toks = str(command or "").strip().strip("\"'(").split()
	if not toks:
		return ""
	verb = toks[0].lower().strip("\"'")
	if verb == "git" and len(toks) > 1:
		verb = f"git {toks[1].lower()}"
	return verb if verb in _VERB_NORMAL_CODES else ""


def _demote_normal_nonzero(text: str, command: str) -> bool:
	"""非零退出码是否应当**降格**为非错误（动词 + 退出码 + 正文形状三件事一起判）。

	同时满足才降格：
	1. 动词在 ``_VERB_NORMAL_CODES`` 里，且**这个码**属于该动词的正常语义；
	2. 正文里没有结构化错误记录、没有硬错误标记；
	3. 需要正文确认的动词（`git diff` 类）必须真的看到 diff 正文。

	实测收益（人工逐条核 26 条）：原先「非零 ⇒ 可疑失败」粗判把**一条真失败**
	（`Select-String` 正则非法）判成正常，又靠关键词扫描才勉强留住另一条
	（`Get-ChildItem` 递归踩到目录拒绝访问）。本判据两者都对。
	"""
	verb = _normal_nonzero_verb(command)
	if not verb:
		return False
	code = _status_code(text)
	if code is None or code not in _VERB_NORMAL_CODES[verb]:
		return False
	body = _output_body(text)
	head = body[:3000]
	if _ERROR_RECORD_RE.search(head):
		return False
	if any(m in head[:2000].lower() for m in _HARD_ERR_MARKERS):
		return False
	if _SILENCE_RE.search(str(command or "")):
		return True
	confirm = _VERB_NEEDS_BODY_CONFIRM.get(verb)
	if confirm is not None:
		return bool(confirm.search(head))
	return True


def _classify_message(
	msg: dict, name_by_id: dict[str, str], cmd_by_id: dict[str, str] | None = None
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
		if not is_err:
			is_err = _looks_like_hard_error(text)
		if is_err and _demote_normal_nonzero(text, (cmd_by_id or {}).get(uid, "")):
			is_err = False
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


def _looks_like_hard_error(text: str) -> bool:
	"""无歧义的失败证据（用于把显式 ``is_error: false`` 升格）。"""
	if not text:
		return False
	verdict = _status_verdict(text)
	if verdict is not None:
		return verdict
	verdict = _receipt_verdict(text)
	if verdict is not None:
		return verdict
	if _ERR_EXIT_RE.search(text[:300].lower()):
		return True
	low = text[:2000].lower()
	return any(m in low for m in _HARD_ERR_MARKERS)


def _looks_like_error(text: str) -> bool:
	if not text:
		return False
	# 头部有机器状态行时，它就是权威判据（成功输出里引用错误文本不算失败）。
	verdict = _status_verdict(text)
	if verdict is not None:
		return verdict
	# 信封自己写的结构化退出码同样权威（头部 ``Script completed`` 不是命令的退出状态）。
	verdict = _receipt_verdict(text)
	if verdict is not None:
		return verdict
	low = text[:2000].lower()
	if any(m in low for m in _STRONG_ERR_MARKERS):
		return True
	return bool(_ERR_EXIT_RE.search(low))


def build_graph(messages: list[dict], *, include_soft_edges: bool = True) -> Graph:
	"""从 API 形式的消息列构建证据图。

	``include_soft_edges`` 只控制启发式 ``seq/file/err`` 边是否进入图的邻接表。
	默认保持完整图，便于离线 oracle 与历史契约；WSC 的 ``project()`` 默认关闭，
	主线只消费语法确定的 ``tool_use -> tool_result`` provenance。
	"""
	# 第一遍：tool_use_id -> 工具名（tool_result 需要反查名字）
	name_by_id: dict[str, str] = {}
	cmd_by_id: dict[str, str] = {}
	for msg in messages:
		for u in tool_use_blocks(msg):
			uid = str(u.get("id") or "")
			if uid:
				name_by_id[uid] = str(u.get("name") or "tool")
				inp = u.get("input")
				if isinstance(inp, dict):
					cmd = inp.get("command") or inp.get("cmd")
					if isinstance(cmd, str):
						cmd_by_id[uid] = cmd

	# 第二遍：建节点
	nodes: list[Node] = []
	noise_refs: list[str] = []
	for i, msg in enumerate(messages):
		kind, role, tool_name, uid, is_err, is_write, read_only, err_sig = _classify_message(
			msg, name_by_id, cmd_by_id
		)
		# 本次调用携带的 shell 命令（工具调用取自身输入；结果节点按键反查）。
		command = ""
		for _u in tool_use_blocks(msg):
			_inp = _u.get("input")
			if isinstance(_inp, dict):
				_c = _inp.get("command") or _inp.get("cmd")
				if isinstance(_c, str) and _c:
					command = _c
					break
		if not command and uid:
			command = cmd_by_id.get(uid, "")
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
		# 来源过滤（去噪机制之一，对所有信息类同口径、在建图之前生效）：机器噪音路径
		# 不进 file_index / 文件状态 / [PATHS] / 针。原始消息一字节不动，冷层仍可展开。
		_noise = [p for p in refs if is_noise_path(p)]
		if _noise:
			noise_refs.extend(_noise)
			_noise_set = set(_noise)
			refs = [p for p in refs if p not in _noise_set]
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
				command=command,
			)
		)


	# 路径变体归并（去噪机制之一，对所有信息类同口径）：同一文件的不同写法
	# （``components/X.tsx`` 与 ``code/cli/src/components/X.tsx``）折叠成最短写法。
	# 必须在这里做——下游 file_states / [PATHS] / [WORKING SET] / 针**全部**从
	# ``node.refs`` 派生，只有这一个入口改写才能保证各处口径一致。
	_ref_pool = [p for n in nodes for p in n.refs]
	_canon = suffix_chain_canonical(_ref_pool)
	_refs_merged = tuple(sorted((k, v) for k, v in _canon.items() if k != v))
	for _i, _n in enumerate(nodes):
		if not _n.refs:
			continue
		_new_refs = tuple(dict.fromkeys(_canon.get(p, p) for p in _n.refs))
		if _new_refs != _n.refs:
			nodes[_i] = replace(_n, refs=_new_refs)

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
		noise_refs=tuple(dict.fromkeys(noise_refs)),
		refs_merged=_refs_merged,
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
