"""时效轴（去噪核心）：判定「同一实体的旧断言是否已被后续断言覆盖」。

本模块**不认「错误」这一种类**，而认一个统一模型——

	信息节点 = (实体键 entity_key, 断言值 value, 出现序 turn)

只要「同类信息在更晚的节点以**结构上可判**的方式覆盖了更早的节点」，旧节点就
标记为 ``superseded``：**降级**（移出热层 + 句柄留底，可 expand 逐字节拉回），
不是删除。判不出覆盖关系时**一律不降级**——误降级会把活信息移出热层，代价远大于
多留一条旧信息。

类目不是特例分支，而是同一模型下的「实体键函数 + 覆盖判据」：

| 类目 | 实体键 | 覆盖信号 | 判不出时 |
| error_sig | (工具, 完整调用参数) | 后续相同调用的成功结果 | 不降级 |
| filestate | 文件路径 | 后续对同一路径的成功结果 | 不降级 |
| todo | 清单整体 | 后续 TodoWrite 快照 | 不降级 |
| decision | (工具, 完整调用参数) | 后续相同调用的成功结果 | 不降级 |
| constraint | 约束主题（关键词集） | 后续用户消息显式改口 + 主题重合 ≥2 | 不降级 |
| injected | 声道标识（机器注入块） | 机器注入 ⇒ 非种子 | 恒定 |
| path_dead | 文件路径 | 后续**成功**的删除/改名命令，且此后无人再碰 | 不降级 |

``decision`` 与 ``error_sig`` 共用实体键（本仓 [DECISIONS] 段渲染的就是带错误签名的
卡片），故它只作为**标签化的子计数**上报，不是第二套判据。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from synaptic.graph import Graph
from synaptic.seeds import extract_constraints, strip_machine_blocks
from synaptic.textutil import is_useful_error_sig, suffix_chain_canonical
from synaptic.types import EDGE_USE, KIND_TOOL_RESULT, KIND_TOOL_USE, KIND_USER

CLASSES = ("error_sig", "decision", "filestate", "todo", "constraint", "injected", "path_dead")

#: 与 ``seeds._SUCCESS_MARKERS`` 同口径（此处复制常量以避免反向依赖 seed 私有名）。
_SUCCESS_MARKERS = (
	"passed", "all tests", "build succeeded", "exit code 0", "0 failed", "0 errors",
	"✓", "通过", "全部成功", "测试通过",
)

#: 需要词边界才算数的宽松标记——避免 "broken"/"passed" 这类子串误命中。
_WORD_MARKERS = ("ok", "success", "succeeded", "verified")
#: 旧实现（正则）。**保留只作等价性自检的参照**，运行期不再使用。
_SUCCESS_WORD_RE = re.compile(r"(?<![A-Za-z])(?:ok|success|succeeded|verified)(?![A-Za-z])")
_ASCII_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _has_word_marker(low: str) -> bool:
	"""词边界版标记匹配：与 ``_SUCCESS_WORD_RE.search(low)`` **逐例等价**。

	为什么不用正则：该判定在 1255 条消息的会话上被调用约 1500 次，正则引擎扫 4000
	字符窗口占掉 freshness 阶段约 1/3 的时间。``str.find`` 走 C 层，快一个数量级；
	边界语义（ASCII 字母）与旧正则逐字符一致，等价值由 ``marker_parity_check()``
	在真实语料上自检。
	"""
	n = len(low)
	for w in _WORD_MARKERS:
		i = low.find(w)
		while i >= 0:
			before_ok = i == 0 or low[i - 1] not in _ASCII_LETTERS
			end = i + len(w)
			after_ok = end >= n or low[end] not in _ASCII_LETTERS
			if before_ok and after_ok:
				return True
			i = low.find(w, i + 1)
	return False


def _marker_window(text: str) -> str:
	"""成功标记的扫描窗口（与旧实现同源：前 4000 字符 + 小写化）。"""
	return (text or "")[:4000].lower()


def marker_parity_check(texts) -> list[str]:
	"""自检：``_has_word_marker`` 与旧正则在给定语料上是否逐例一致。"""
	bad: list[str] = []
	for t in texts:
		low = _marker_window(t)
		if _has_word_marker(low) != bool(_SUCCESS_WORD_RE.search(low)):
			bad.append(str(t)[:120])
	return bad

#: 显式改口标记：出现它才可能「新说法取代旧说法」。
_OVERRIDE_MARKERS = (
	"改成", "改为", "换成", "换为", "改用", "取代", "不再是", "不要了", "不用了",
	"取消刚才", "撤销", "instead of", "no longer", "rather than", "replace ",
	"switch to", "change to", "stop using", "forget about", "drop the",
)

#: 成功的删除 / 改名命令标记（判定路径已死）。
_DELETE_MARKERS = (
	"rm ", "rm -", "rmdir", "del ", "erase ", "remove-item", "git rm", "git mv",
	"move-item", "mv ", "rename ",
)

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,}")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")

#: 命令位置边界：删除/改名标记必须跟在行首或这些字符之后，才算一条命令。
_CMD_BOUNDARY = frozenset(" \t\n\r\"';|&(-=:,.")


@dataclass(frozen=True)
class Downgrade:
	"""一条降级记录：谁被降级、被谁覆盖、依据什么类目与实体键。"""

	idx: int
	by: int
	cls: str
	key: str
	why: str


@dataclass
class Freshness:
	"""时效轴分析结果（审计可直接落盘）。"""

	downgrades: tuple[Downgrade, ...] = ()
	superseded: frozenset[int] = frozenset()
	superseded_constraints: frozenset[str] = frozenset()
	dead_paths: tuple[str, ...] = ()
	identified_errors: int = 0
	errors_resolved: int = 0
	injected_nodes: tuple[int, ...] = ()
	mis_downgrade: tuple[str, ...] = ()
	by_class: dict[str, int] = field(default_factory=dict)
	#: 逐条「被判为失败」的清单（idx / 工具 / 签名 / 是否被后续证据填掉）。
	error_detail: tuple[dict, ...] = ()
	#: 识别到的失败下标 / 已被后续证据覆盖的下标 / 仍在的下标（三者是**唯一口径**，
	#: 种子与评分都从这里取，不再各自重算）。
	identified_idx: frozenset[int] = frozenset()
	resolved_idx: frozenset[int] = frozenset()
	unresolved_idx: frozenset[int] = frozenset()

	def _useful_sig_rate(self) -> float:
		if not self.error_detail:
			return 1.0
		n = sum(1 for d in self.error_detail if is_useful_error_sig(d["sig"]))
		return round(n / len(self.error_detail), 4)

	def audit(self) -> dict:
		"""审计行（确定性；进报告）。"""
		return {
			"identified_errors": self.identified_errors,
			# 可用签名率：签名不是「退出码 N」这类零信息量回落的比例。
			# 为什么要它：error_sig 针存活率 100% 只能证明**那条字符串还在**，
			# 而「退出码 1」也是 100%——两个指标一起看才有意义。
			"useful_signature_rate": self._useful_sig_rate(),
			"useless_signatures": sorted(
				{d["sig"] for d in self.error_detail if not is_useful_error_sig(d["sig"])}
			)[:12],
			"errors_resolved": self.errors_resolved,
			"downgraded_total": len(self.downgrades),
			"downgraded_by_class": dict(sorted(self.by_class.items())),
			"downgrade_examples": [
				{"idx": d.idx, "by": d.by, "cls": d.cls, "key": d.key[:64], "why": d.why[:96]}
				for d in self.downgrades[:12]
			],
			"dead_paths": list(self.dead_paths[:24]),
			"dead_path_count": len(self.dead_paths),
			"injected_nodes": list(self.injected_nodes[:24]),
			"injected_count": len(self.injected_nodes),
			"errors": [dict(x) for x in self.error_detail],
			"mis_downgrade": list(self.mis_downgrade),
			"mis_downgrade_count": len(self.mis_downgrade),
		}


def _has_success_marker(text: str) -> bool:
	"""输出里是否出现**明确的成功证据**。

	注意：不做窗口截断。实测把扫描窗口从 4000 字符压到「头 400 + 尾 800」虽然省
	约 14% 的 freshness 耗时，却把本语料的「已解决」判定从 5 条砍到 3 条——判定
	准确性优先于这点延迟。
	"""
	low = _marker_window(text)
	if any(m in low for m in _SUCCESS_MARKERS):
		return True
	return _has_word_marker(low)



def _invocation_text(graph: Graph, node) -> str:
	"""结果节点对应的**那次调用**的原文（用于「同一条命令原样重跑」判据）。"""
	uid = str(getattr(node, "tool_use_id", "") or "")
	if not uid:
		return ""
	if uid in graph.use_signatures:
		return graph.use_signatures[uid]
	use = graph.node(graph.by_use_id.get(uid, -1))
	return str(use.text or "").strip() if use is not None else ""


def _marker_at(graph: Graph, idx: int, cache: dict[int, bool] | None) -> bool:
	"""按节点缓存成功标记判定（同一条结果会被多条错误反复判到）。"""
	if cache is None:
		n = graph.node(idx)
		return _has_success_marker(n.text if n is not None else "")
	hit = cache.get(idx)
	if hit is None:
		n = graph.node(idx)
		hit = _has_success_marker(n.text if n is not None else "")
		cache[idx] = hit
	return hit


def _result_index(graph: Graph, region_end: int) -> dict[str, tuple[int, ...]]:
	"""工具名 -> 区域内的**非错误结果**节点下标（升序）。

	存在理由：原先每条错误都线性扫全部后续节点（1255 节点 × 19 条错误 × 每轮 ⇒ 明显
	的延迟增量）。索引一次、按工具名取窗口，判定结果逐元素不变。
	"""
	out: dict[str, list[int]] = {}
	for m in graph.nodes:
		if m.idx >= region_end or m.is_error or m.kind != KIND_TOOL_RESULT:
			continue
		out.setdefault(m.tool_name, []).append(m.idx)
	return {k: tuple(v) for k, v in out.items()}




def _covered_later(
	graph: Graph,
	n,
	region_end: int,
	results_by_tool: dict[str, tuple[int, ...]] | None = None,
	marker_cache: dict[int, bool] | None = None,
) -> int | None:
	"""``n``（一个失败结果）是否被后续**同类成功**覆盖。

	后续结果必须来自相同工具和完整调用参数，且带成功标记。
	旧结果有文件引用时，还要求现场路径重合；仅同路径或成功改写不能证明错误已解决。

	信号不够就返回 ``None``（保守：不降级）。宁可多留一条未解错误，也不把还在
	的坑标成已填。
	"""
	targets = set(n.refs)
	invocation = _invocation_text(graph, n)
	if not invocation:
		return None
	cands = (
		results_by_tool.get(n.tool_name, ())
		if results_by_tool is not None
		else tuple(
			m.idx
			for m in graph.nodes
			if m.idx < region_end
			and not m.is_error
			and m.kind == KIND_TOOL_RESULT
			and m.tool_name == n.tool_name
		)
	)
	for j in cands:
		if j <= n.idx:
			continue
		m = graph.nodes[j]
		if not _marker_at(graph, j, marker_cache):
			continue
		if targets:
			if not (targets & set(m.refs)):
				continue
		if _invocation_text(graph, m) != invocation:
			continue
		return j
	return None


def _write_success(graph: Graph, u, region_end: int) -> bool:
	"""``u``（一次写工具调用）是否成功落地：有结果、无错误、结果非空，
	**且结果里真的出现正向成功标记**。

	为什么必须有正向标记（漏这一条会让 5 条契约测试同时红）：只判「非空 + 未被判错误」
	时，一次同命令重试哪怕只回 ``no output``、一条 ``Edit`` 只回 ``edited``，都会被当成
	「成功改写同一文件」而把**先前的失败现场抹掉** —— ``[UNRESOLVED]`` 就此漏报。
	本模块的取舍写在 ``seeds`` 的同一条注释里：误判「已解决」的代价远大于误判
	「未解决」（后者只是 PIN 大一点）。
	"""
	children = [d for d in graph.outgoing(u.idx, EDGE_USE) if d < region_end]
	if not children:
		return False
	for c in children:
		m = graph.node(c)
		text = str(m.text or "").strip() if m is not None else ""
		if m is None or m.is_error or not text:
			return False
		low = text.lower()
		if not (any(s in low for s in _SUCCESS_MARKERS) or _has_word_marker(low)):
			return False
	return True




def error_covered_by(
	graph: Graph,
	n,
	region_end: int,
	results_by_tool: dict[str, tuple[int, ...]] | None = None,
	marker_cache: dict[int, bool] | None = None,
) -> tuple[int, str] | None:
	"""一条失败结果是否已被后续证据覆盖：返回 ``(覆盖者下标, 依据)``，否则 ``None``。

	**判据的唯一实现**：``freshness`` 与 ``seeds._is_resolved`` 都从这里取结论，
	不允许第二份副本（两份口径各自漂移会让 [UNRESOLVED] 与实际覆盖关系不一致）。
	"""
	by = _covered_later(graph, n, region_end, results_by_tool, marker_cache)
	if by is not None:
		return by, "后续同类成功结果覆盖同一现场"
	return None


def _error_superseders(graph: Graph, region_end: int) -> tuple[list[Downgrade], int]:
	out: list[Downgrade] = []
	resolved = 0
	results_by_tool = _result_index(graph, region_end)
	marker_cache: dict[int, bool] = {}
	for n in graph.nodes:
		if n.idx >= region_end or not n.is_error or not n.error_sig:
			continue
		hit = error_covered_by(
			graph, n, region_end, results_by_tool, marker_cache
		)
		if hit is None:
			continue
		by, why = hit
		resolved += 1
		out.append(
			Downgrade(
				idx=n.idx,
				by=by,
				cls="error_sig",
				key=f"{n.tool_name}|{','.join(sorted(set(n.refs))) or '-'}",
				why=why,
			)
		)
	return out, resolved


def _filestate_superseders(graph: Graph, region_end: int) -> list[Downgrade]:
	"""同一路径的旧观测被更晚的成功结果覆盖（读后又有新读 ⇒ 旧读过期）。"""
	last: dict[str, int] = {}
	for n in graph.nodes:
		if n.idx >= region_end or n.kind != KIND_TOOL_RESULT or n.is_error:
			continue
		for p in n.refs:
			last[p] = max(last.get(p, -1), n.idx)
	out: list[Downgrade] = []
	seen: set[int] = set()
	for n in graph.nodes:
		if n.idx >= region_end or n.kind != KIND_TOOL_RESULT or n.is_error:
			continue
		for p in n.refs:
			j = last.get(p, -1)
			if j > n.idx and n.idx not in seen:
				seen.add(n.idx)
				out.append(
					Downgrade(
						idx=n.idx, by=j, cls="filestate", key=p,
						why="同一路径有更晚的成功结果",
					)
				)
	return out


def _todo_superseders(graph: Graph, region_end: int) -> list[Downgrade]:
	"""任务清单是覆盖式快照：历次 TodoWrite 被最后一次取代。"""
	from synaptic.seeds import TODO_TOOLS

	nodes = [
		n.idx
		for n in graph.nodes
		if n.idx < region_end
		and n.kind == KIND_TOOL_USE
		and any(x.strip() in TODO_TOOLS for x in str(n.tool_name or "").split(","))
	]
	if len(nodes) < 2:
		return []
	last = nodes[-1]
	return [
		Downgrade(idx=i, by=last, cls="todo", key="todo_list", why="被最后一次清单快照覆盖")
		for i in nodes[:-1]
	]


def _tokens(text: str) -> set[str]:
	"""主题词集：拉丁词（≥4 字符）+ 中文双字组。

	中文为什么必须进来：本仓的用户约束几乎全是中文，而原先只取拉丁词 ⇒ 绝大多数约束
	的词集是**空集**，改口判据永远不会触发（实测本语料 6 条约束里 4 条词集为 0）。
	中文用 bigram——与 ``closure.keywords`` 同口径，无需分词器、确定性强。
	"""
	s = text or ""
	out = {m.group(0).lower() for m in _TOKEN_RE.finditer(s)}
	for m in _CJK_RUN_RE.finditer(s):
		run = m.group(0)
		for i in range(len(run) - 1):
			out.add(run[i:i + 2])
	return out


def _is_cjk_bigram(tok: str) -> bool:
	return len(tok) == 2 and all("\u4e00" <= ch <= "\u9fff" for ch in tok)


def _constraint_superseders(
	graph: Graph, region_end: int, user_nodes: tuple[int, ...]
) -> tuple[list[Downgrade], frozenset[str]]:
	"""后续用户消息**显式改口**且主题重合足够 ⇒ 旧约束降级；否则原样保留。

	阈值分语言：有拉丁词重合时 2 个词即可；**只有中文 bigram 重合**时要求 3 个——
	bigram 是弱信号（短句之间天然共享若干双字组），抬高门槛换取「不误降级」。
	"""
	seen: list[tuple[int, str]] = []
	for i in user_nodes:
		if i >= region_end:
			continue
		n = graph.node(i)
		if n is None or n.kind != KIND_USER:
			continue
		for c in extract_constraints(strip_machine_blocks(n.text)):
			seen.append((i, c))
	out: list[Downgrade] = []
	dropped: set[str] = set()
	for pos, (i, c) in enumerate(seen):
		ct = _tokens(c)
		if not ct:
			continue
		for j, (k, other) in enumerate(seen):
			if k <= i or j <= pos:
				continue
			low = strip_machine_blocks(graph.nodes[k].text).lower()
			if not any(m in low for m in _OVERRIDE_MARKERS):
				continue
			shared = ct & _tokens(other)
			need = 2 if any(not _is_cjk_bigram(t) for t in shared) else 3
			if len(shared) < need:
				continue
			out.append(
				Downgrade(
					idx=i, by=k, cls="constraint", key=c[:48],
					why="后续用户消息显式改口且主题重合",
				)
			)
			dropped.add(c)
			break
	return out, frozenset(dropped)


_SEG_SPLIT = re.compile(r"[;\n|]|&&|\|\|")
#: 段首即删除/改名动词（``git rm`` / ``git mv`` 走 head == "git" 的分支）。
_DELETE_VERBS = frozenset({
	"rm", "rmdir", "del", "erase", "remove-item", "mv", "move-item", "rename",
})


def _delete_segments(cmd: str) -> list[str]:
	"""把 shell 命令切成简单命令段，只留下**段首就是删除/改名动词**的那些段。

	为什么不用裸子串匹配：``"form field"`` 含 ``"rm "``、``"confirm "`` 含 ``"rm "``，
	HTML/CSS 里的 ``transform`` / ``.ctrl`` 也一样。实测本语料 2 条 path_dead 命中的是
	``n/n.ctrl`` / ``n/n.list``（内联 HTML 里被正则扫出来的垃圾路径），另一条把
	**新增**文件的 apply_patch 判成了删除——裸匹配在这个问题上根本不可用。
	"""
	out: list[str] = []
	for seg in _SEG_SPLIT.split(str(cmd or "")):
		toks = seg.strip().split()
		if not toks:
			continue
		head = toks[0].strip("\"'`(){}[]").lower()
		if head == "git" and len(toks) > 1 and toks[1].lower() in ("rm", "mv", "checkout"):
			out.append(seg)
		elif head in _DELETE_VERBS:
			out.append(seg)
	return out


def _deleted_operands(cmd: str, refs) -> tuple[str, ...]:
	"""命令里**作为删除/改名操作数**出现的 refs（先按段首动词筛，再要求路径落在该段内）。"""
	segs = _delete_segments(cmd)
	if not segs:
		return ()
	out: list[str] = []
	for p in refs:
		base = p.rsplit("/", 1)[-1]
		for seg in segs:
			flat = seg.replace("\\", "/")
			if p in flat or base in flat:
				out.append(p)
				break
	return tuple(dict.fromkeys(out))


def _dead_paths(graph: Graph, region_end: int) -> list[Downgrade]:
	"""**成功的**删除 / 改名命令命中的路径，且此后无人再触碰 ⇒ 该路径已死。

	拿不到命令原文（``messages`` 未给）时**不判**——保守方向是「少降级」。
	"""
	out: list[Downgrade] = []
	seen_paths: set[str] = set()
	for n in graph.nodes:
		if n.idx >= region_end or n.kind != KIND_TOOL_USE or not n.refs:
			continue
		operands = _deleted_operands(n.command, n.refs)
		if not operands:
			continue
		if not _write_success(graph, n, region_end):
			continue
		# 「之后无人再碰」必须排除这次删除调用**自己的输出**：结果节点会继承调用方
		# 的 refs，若把它算成「又碰了一次」，任何成功的 rm 都永远判不出死路径。
		own = set(graph.outgoing(n.idx, EDGE_USE))
		for p in operands:
			if p in seen_paths:
				continue
			seen_paths.add(p)
			touched_later = any(
				m.idx > n.idx and p in m.refs
				for m in graph.nodes
				if m.idx < region_end and m.idx not in own
			)
			if touched_later:
				continue
			out.append(
				Downgrade(
					idx=n.idx, by=n.idx, cls="path_dead", key=p,
					why="成功的删除/改名之后无人再触碰该路径",
				)
			)
	return out


def _mis_downgrade(graph: Graph, downs: tuple[Downgrade, ...]) -> tuple[str, ...]:
	"""不变式复检（独立于判据本身的那种）：覆盖者必须晚于被降级者，且在图中存在、
	自身未被降级（除非它就是删除动作本身）。"""
	bad: list[str] = []
	# 按类目预聚合（原先在循环里现算 ⇒ O(降级数²)；1255 条消息的会话上实测占掉
	# freshness 阶段的大头）。结果与逐次现算完全一致。
	by_cls: dict[str, set[int]] = {}
	for d in downs:
		by_cls.setdefault(d.cls, set()).add(d.idx)
	for d in downs:
		if d.cls == "path_dead":
			continue
		if d.by <= d.idx:
			bad.append(f"{d.cls} #{d.idx}: 覆盖者 #{d.by} 不晚于被降级者")
			continue
		if graph.node(d.by) is None:
			bad.append(f"{d.cls} #{d.idx}: 覆盖者 #{d.by} 不在图中")
			continue
		# filestate 是**链式**覆盖（读 A → 读 A → 读 A），中间的读自身也会被更晚的读
		# 覆盖，这是正常的；只在**同一类目**内检查「覆盖者自身也被降级」。
		if d.cls != "filestate" and d.by in by_cls.get(d.cls, ()):
			bad.append(f"{d.cls} #{d.idx}: 覆盖者 #{d.by} 自身也被同类降级")
	return tuple(bad)


def analyze(
	graph: Graph,
	*,
	region_end: int | None = None,
	user_nodes: tuple[int, ...] = (),
) -> Freshness:
	"""跑一遍时效轴：返回降级集与审计。"""
	limit = region_end if region_end is not None else len(graph.nodes)

	errors = [n for n in graph.nodes if n.idx < limit and n.is_error and n.error_sig]
	users = user_nodes or tuple(
		n.idx for n in graph.nodes if n.idx < limit and n.kind == KIND_USER
	)
	err_downs, resolved = _error_superseders(graph, limit)
	file_downs = _filestate_superseders(graph, limit)
	todo_downs = _todo_superseders(graph, limit)
	constraint_downs, dropped_constraints = _constraint_superseders(graph, limit, users)
	dead = _dead_paths(graph, limit)

	injected = tuple(
		n.idx
		for n in graph.nodes
		if n.idx < limit
		and n.kind == KIND_USER
		and not strip_machine_blocks(n.text).strip()
	)

	# path_dead 也进 ``downgrades``：它同样是「时效轴判定该条目过期」，只是降级对象是
	# **路径索引条目**而非节点（故不进 ``superseded``，不参与节点级不变式复检）。
	downs = tuple(err_downs + file_downs + todo_downs + constraint_downs + dead)
	by_class: dict[str, int] = {}
	for d in downs:
		by_class[d.cls] = by_class.get(d.cls, 0) + 1
	# [DECISIONS] 渲染的就是带错误签名的卡片 ⇒ decision 是 error_sig 的标签化子计数
	if err_downs:
		by_class["decision"] = len(err_downs)
	by_class["injected"] = len(injected)

	superseded: set[int] = set()
	for d in downs:
		if d.cls != "path_dead":
			superseded.add(d.idx)

	# 逐条错误清单（**最有说服力的原始证据**）：谁被判成失败、有没有被后续证据填掉。
	err_detail = [
		{
			"idx": n.idx,
			"tool": n.tool_name,
			"sig": n.error_sig[:96],
			"refs": list(n.refs[:4]),
			"resolved_by": next((d.by for d in err_downs if d.idx == n.idx), -1),
		}
		for n in errors
	]

	return Freshness(
		downgrades=downs,
		identified_idx=frozenset(n.idx for n in errors),
		resolved_idx=frozenset(d.idx for d in err_downs),
		unresolved_idx=frozenset(
			n.idx for n in errors if n.idx not in {d.idx for d in err_downs}
		),
		superseded=frozenset(superseded),
		superseded_constraints=dropped_constraints,
		dead_paths=tuple(d.key for d in dead),
		identified_errors=len(errors),
		errors_resolved=resolved,
		injected_nodes=injected,
		mis_downgrade=_mis_downgrade(graph, downs),
		by_class=by_class,
		error_detail=tuple(err_detail),
	)


def path_variant_report(paths: list[str]) -> dict[str, object]:
	"""路径变体归并的可解释报告（谁并到了谁）。"""
	m = suffix_chain_canonical(paths)
	merged = sorted((k, v) for k, v in m.items() if k != v)
	return {"merged_pairs": len(merged), "examples": merged[:12]}


__all__ = [
	"CLASSES",
	"marker_parity_check",
	"Downgrade",
	"Freshness",
	"analyze",
	"path_variant_report",
]
