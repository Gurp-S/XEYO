"""种子收集（规则 2 的入口）：当前目标 / 未完成 TODO / 未解决错误 / 用户硬约束。

种子是 PIN 集的来源，也是反向依赖闭包的起点。与生产链的差别在于：这里读的是
**目标态**（主动种子），而不是「被压掉的左段」（被动种子）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from synaptic.graph import Graph
from synaptic.textutil import tool_use_blocks
from synaptic.types import KIND_TOOL_RESULT, KIND_TOOL_USE, KIND_USER, FileState

# 用户硬约束句式（中英双轨）
_CONSTRAINT_PATTERNS = (
	"不能", "不要", "不许", "不得", "禁止", "必须", "务必", "要求", "只允许", "只能",
	"不允许", "不可以", "注意", "记得", "一定要", "别改", "别动",
	"must not", "must ", "don't ", "do not ", "never ", "always ", "required",
	"only ", "shall not", "make sure", "be sure",
)
_CONSTRAINT_RE = re.compile("|".join(re.escape(p) for p in _CONSTRAINT_PATTERNS), re.IGNORECASE)

# 收尾/寒暄式的无实质用户消息（不作种子）
_NOISE_USER = (
	"继续", "好的", "ok", "okay", "谢谢", "嗯", "可以了", "go on", "continue", "thanks",
)

# 引擎注入的伪用户消息（续跑指令 / 系统提醒）：它们不是用户意图，不能当目标或约束。
# 判据取自引擎实际注入文本的开头标记，避免把机器文本读成人类指令。
_ENGINE_INJECTED = (
	"[resume]",
	"[continue]",
	"[wrap-up]",
	"[系统提醒]",
	"the user asked to continue an interrupted turn",
	"the user asks you to continue",
)

_SENT_SPLIT = re.compile(r"(?<=[。！？；!?;])|\n+")

TODO_TOOLS = frozenset({"TodoWrite", "TodoRead", "TaskCreate", "TaskUpdate"})
TODO_PENDING = ("pending", "in_progress", "in-progress", "todo", "open", "not_started")


@dataclass(frozen=True)
class Seeds:
	"""种子集合（PIN 集的直接来源）。"""

	goal: str
	original_task: str
	constraints: tuple[str, ...] = ()
	unresolved_errors: tuple[str, ...] = ()
	todos: tuple[str, ...] = ()
	pin_nodes: tuple[int, ...] = ()
	pin_paths: tuple[str, ...] = ()
	#: **实质**人类用户节点下标（``_substantive`` 过滤后的），权威口径。
	#:
	#: 存在的理由：``graph`` 里 ``kind == KIND_USER`` 的节点远不止人类原话——
	#: 工具结果与引擎注入的伪用户消息都落在同一 kind 上（本仓库 199 回合会话里
	#: 区域内 188 个 kind=user，实质人类消息只有 17 条）。
	#: ``[REQUESTS]`` 需要的是「用户原话」，所以必须用这里的过滤结果，
	#: **不要**在别处重新按 kind 扫图——那会把工具结果当用户原话导出（踩过）。
	user_nodes: tuple[int, ...] = ()
	# 审计留痕：每个种子的来源与理由
	trace: list[dict[str, str]] = field(default_factory=list)


def _substantive(text: str) -> bool:
	s = (text or "").strip()
	if len(s) < 4:
		return False
	low = s.lower()
	if any(low.startswith(m) or m in low[:200] for m in _ENGINE_INJECTED):
		return False
	return not any(low == n or (len(s) <= 12 and low.startswith(n)) for n in _NOISE_USER)


def extract_constraints(text: str, *, limit: int = 12) -> tuple[str, ...]:
	"""从一条用户消息里抽约束句（原句保留，不改写）。"""
	if not text:
		return ()
	out: list[str] = []
	for raw in _SENT_SPLIT.split(text):
		s = " ".join((raw or "").split())
		if len(s) < 4:
			continue
		if _CONSTRAINT_RE.search(s):
			out.append(s[:240])
		if len(out) >= limit:
			break
	return tuple(out)


# 「已修好」的正向标记：错误被判定为已解决，必须真的看到成功证据。
# 仅凭「之后有同类成功结果」是不够的——一条 grep 输出提到同一个文件，也会
# 满足「同工具 + 同路径」，但它跟「那个测试已经过了」毫无关系。误判「已解决」
# 会让失败现场从 PIN 里消失，代价远大于误判「未解决」（后者只是 PIN 大一点）。
_SUCCESS_MARKERS = (
	"passed",
	"pass",
	"all tests",
	"ok",
	"success",
	"build succeeded",
	"exit code 0",
	"0 failed",
	"0 errors",
	"✓",
	"通过",
	"全部成功",
	"测试通过",
)


def _has_success_marker(text: str) -> bool:
	low = (text or "")[:4000].lower()
	return any(m in low for m in _SUCCESS_MARKERS)


def _is_resolved(graph: Graph, n) -> bool:
	"""错误是否已被后续成功的**同类动作**解决。

三条同时满足才算解决：①同一工具的后续结果；②其文件引用覆盖失败现场；
③结果文本里出现成功标记。第 ③ 条是刻意加的——机器无法判断「一次 Read 成功」
等不等于「那个失败的测试已经过了」，所以只承认明确的成功证据。
	"""
	targets = set(n.refs)
	for j in range(n.idx + 1, len(graph.nodes)):
		m = graph.nodes[j]
		if m.is_error or m.kind != KIND_TOOL_RESULT:
			continue
		if m.tool_name != n.tool_name:
			continue
		if targets:
			if not m.refs or not (targets & set(m.refs)):
				continue
		if not _has_success_marker(m.text):
			continue
		return True
	return False


def _unresolved_error_nodes(graph: Graph) -> list[int]:
	"""未解决错误节点：之后没有针对同一现场的成功同类动作。"""
	return [
		n.idx
		for n in graph.nodes
		if n.is_error and n.error_sig and not _is_resolved(graph, n)
	]


def _todo_items(messages: list[dict], graph: Graph) -> list[str]:
	"""取**最后一次** TodoWrite 的未完成条目。

任务树记录的是「现在要做什么」，不是「历史上一共写过哪些待办」——历次
TodoWrite 是同一份清单的覆盖式快照，累积起来会把已废弃条目当成现存任务。
	"""
	last_idx = -1
	for n in graph.nodes:
		if n.kind != KIND_TOOL_USE:
			continue
		names = [x.strip() for x in str(n.tool_name or "").split(",") if x.strip()]
		if any(x in TODO_TOOLS for x in names):
			last_idx = max(last_idx, n.idx)
	if last_idx < 0 or last_idx >= len(messages):
		return []

	out: list[str] = []
	for u in tool_use_blocks(messages[last_idx]):
		inp = u.get("input")
		if not isinstance(inp, dict):
			continue
		items = inp.get("todos") or inp.get("items")
		if isinstance(items, list):
			for it in items:
				if not isinstance(it, dict):
					continue
				st = str(it.get("status") or "").lower()
				body = str(
					it.get("content") or it.get("text") or it.get("subject") or ""
				).strip()
				if body and st in TODO_PENDING:
					out.append(f"[{st or 'pending'}] {body[:180]}")
		elif isinstance(items, str) and items.strip():
			out.append(items.strip()[:180])
	return list(dict.fromkeys(out))


def collect_seeds(
	graph: Graph,
	messages: list[dict],
	file_states: dict[str, FileState],
	*,
	goal_override: str = "",
) -> Seeds:
	"""收集种子并给出 PIN 节点/路径。"""
	trace: list[dict[str, str]] = []

	user_nodes = [n for n in graph.nodes if n.kind == KIND_USER and _substantive(n.text)]
	original_task = user_nodes[0].text.strip() if user_nodes else ""
	if original_task:
		trace.append({"kind": "goal", "src": f"user#{user_nodes[0].idx}", "why": "首个实质用户目标"})

	# 后继用户消息**不再**进 PIN（规则 1）。
	# 理由有两条，缺一不可：
	#   1) 冗余：未被保护的尾部本来就逐字带着最近的用户消息，再钉进热层是重复计费；
	#   2) KV 敌对：它们逐轮必变，而此前它们排在热层 offset 0 之后不远处，一变就让
	#      其后 [MAIN]/[DECISIONS]/[PRUNED] 数千 token 的稳定内容全部前缀失效。
	# 目标/约束由下面两条抽取式种子承担（稳定），近期原话由尾部承担（逐字）。
	# 详见 docs/synaptic-compression.md §11.8。
	constraints: list[str] = []
	for n in user_nodes:
		for c in extract_constraints(n.text):
			constraints.append(c)
			trace.append({"kind": "constraint", "src": f"user#{n.idx}", "why": f"约束句: {c[:48]}"})
	constraints = list(dict.fromkeys(constraints))

	err_nodes = _unresolved_error_nodes(graph)
	# 次序用「首现次序」而非排序——实测排序更差（[UNRESOLVED] 前缀失稳率 6% → 15%）：
	# graph.nodes 按 idx 升序，故首现次序等价于「按最早存活实例下标排序」，它把段首
	# 锚定在**最老的未解决错误**上（极稳）；改成字典序后段首变成「字典序最小的签名」，
	# 该签名一消失段首就换人。两者都不完美，但前者实测更稳。
	unresolved = tuple(dict.fromkeys(graph.nodes[i].error_sig for i in err_nodes))
	for i in err_nodes:
		trace.append(
			{"kind": "unresolved_error", "src": f"msg#{i}", "why": graph.nodes[i].error_sig[:64]}
		)

	todos = tuple(_todo_items(messages, graph))
	for t in todos:
		trace.append({"kind": "todo", "src": "todo_tool", "why": t[:64]})

	# PIN 节点：用户消息 + 未解决错误 + TODO 所在节点
	pin_nodes: list[int] = [n.idx for n in user_nodes]
	pin_nodes.extend(err_nodes)
	for n in graph.nodes:
		if n.kind != KIND_TOOL_USE:
			continue
		names = [x.strip() for x in str(n.tool_name or "").split(",")]
		if any(x in TODO_TOOLS for x in names):
			pin_nodes.append(n.idx)

	# PIN 路径：目标/约束/未解决错误涉及，或状态已过期/带未解错误
	pin_paths: list[str] = []
	for i in [*[n.idx for n in user_nodes], *err_nodes]:
		node = graph.node(i)
		if node:
			pin_paths.extend(node.refs)
	for p, s in file_states.items():
		if s.stale or s.related_errors:
			pin_paths.append(p)
			trace.append(
				{
					"kind": "pin_path",
					"src": p,
					"why": "文件状态过期" if s.stale else f"带未解错误 {s.related_errors[0][:32]}",
				}
			)

	goal = goal_override.strip() or original_task
	return Seeds(
		goal=goal,
		original_task=original_task,
		constraints=tuple(constraints),
		unresolved_errors=unresolved,
		todos=todos,
		pin_nodes=tuple(dict.fromkeys(pin_nodes)),
		pin_paths=tuple(dict.fromkeys(pin_paths)),
		user_nodes=tuple(n.idx for n in user_nodes),
		trace=trace,
	)


# ---------------------------------------------------------------------------
# 关键信息针（用于「即时关键信息保留」的非同义反复度量）
# ---------------------------------------------------------------------------

def harvest_needles(
	graph: Graph,
	file_states: dict[str, FileState],
	*,
	region_end: int | None = None,
) -> dict[str, tuple[str, ...]]:
	"""从**原始历史**收割关键信息针，按类别分组。

这些针不是 PIN 集的产物，因此「针在热层的存活率」不是同义反复——它检验
WSC 是否真的把关键信息带过去了，而不是把 PIN 塞满就算完。

``region_end`` 给出时只收割被压缩区域内的节点（热层之外的尾部本就逐字保留，
把它算进来会虚高存活率）。
	"""
	limit = region_end if region_end is not None else 1 << 30
	nodes = [n for n in graph.nodes if n.idx < limit]

	users: list[str] = []
	for n in nodes:
		if n.kind == KIND_USER and _substantive(n.text):
			users.append(" ".join(n.text.split())[:80])

	errs: list[str] = []
	for n in nodes:
		if n.is_error and n.error_sig:
			errs.append(n.error_sig)

	paths: list[str] = []
	for n in nodes:
		paths.extend(n.refs)
	if region_end is None:
		paths.extend(file_states.keys())

	# 近期路径：区域后 25% 内被触碰的路径。长尾路径（早期读一次、之后再没碰过）
	# **本来就应该被丢掉**（冷层可 expand），所以「全部路径存活率」天然偏低；
	# 真正该问的是「还在用的那些路径有没有留下来」。
	cut = int(len(nodes) * 0.75)
	recent: list[str] = []
	for n in nodes[cut:]:
		recent.extend(n.refs)

	# 失败现场：出现错误的节点所触碰的路径（与 path 类不同——这里是「踩过坑」的地方）
	fails: list[str] = []
	for n in nodes:
		if not n.is_error:
			continue
		fails.extend(n.refs)

	unwrap = lambda xs: tuple(dict.fromkeys(x for x in xs if x))  # noqa: E731
	return {
		"user": unwrap(users),
		"error_sig": unwrap(errs),
		"path": unwrap(paths),
		"path_recent": unwrap(recent),
		"failure_site": unwrap(fails),
	}
