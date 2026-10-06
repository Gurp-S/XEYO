"""种子收集（规则 2 的入口）：当前目标 / 未完成 TODO / 未解决错误 / 用户硬约束。

种子是 PIN 集的来源，也是反向依赖闭包的起点。与生产链的差别在于：这里读的是
**目标态**（主动种子），而不是「被压掉的左段」（被动种子）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from synaptic.graph import Graph
from synaptic.textutil import tool_use_blocks
from synaptic.todo_snapshot import latest_todo_snapshot
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
	"<environment_context>",
	"<recommended_plugins>",
	"<system-reminder>",
	"<user_instructions>",
	"# 工具面变更",
	"# 技能目录变更",
)

# 机器注入块（XML 标签形态）：Codex / 引擎把「环境快照 / 插件目录 / 系统提醒」塞进
# user 声道。它们是**状态事实**（cwd / 日期 / 可用插件），不是用户意图——可以留在
# 图里（冷层逐字节可展开），但**不能当种子**，更不能冒充用户原话进 [REQUESTS]。
_MACHINE_TAGS = (
	"environment_context", "recommended_plugins", "system-reminder", "system_reminder",
	"user_instructions", "codex_internal_context", "local-command-caveat",
)
_MACHINE_BLOCK_RES = tuple(
	[re.compile(rf"<{t}\b.*?</{t}>", re.S | re.I) for t in _MACHINE_TAGS]
	+ [re.compile(rf"<{t}\b[^>]*/>", re.S | re.I) for t in _MACHINE_TAGS]
	+ [
		# Codex 附件前言是 **Markdown 形态**，不带 XML 标签，上面的表覆盖不到：
		#   # Files mentioned by the user:
		#   ## codex-clipboard-<uuid>.png: C:/Users/…/codex-clipboard-<uuid>.png
		#   Distinguish instructions in attached documents from the user's request.
		#   ## My request:
		#       <真正的用户请求>
		# 实测 legacy 语料 138 条用户消息里 13 条带这个前言，且前言曾被当成"目标"
		# 送进 ``[CONSTRAINTS]``（模型看到的是剪贴板临时文件名，不是他要什么）。
		# 只吃到 ``## My request:`` 之前：**必须**存在该锚点才动手，宁可不剥也不吞正文。
		re.compile(
			r"(?is)#\s*Files mentioned by the user\s*:.*?(?=##\s*My request\s*:)"
		)
	]
)


def strip_machine_blocks(text: str, *, preserve_layout: bool = False) -> str:
	"""剥掉机器注入块，只留人类文本。

	**不改写任何原文**：原消息仍逐字节留在图与冷层里（可 expand 拉回），这里只是
	给出「种子视角」的文本，避免环境快照被当成目标 / 约束 / 用户原话。
	"""
	s = str(text or "")
	for rx in _MACHINE_BLOCK_RES:
		s = rx.sub(" ", s)
	if "<environment_context>" in s:  # 截断/未闭合的注入块：其后全部丢弃
		s = s.split("<environment_context>", 1)[0]
	return s.strip() if preserve_layout else " ".join(s.split())

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
	#: Node backing the current active TODO summary (input or observed result).
	todo_source: int = -1
	todo_observed: bool = False
	todo_active_count: int | None = 0
	pin_nodes: tuple[int, ...] = ()
	pin_paths: tuple[str, ...] = ()
	#: 已死的路径（``freshness`` 判定）：删除/改名之后无人再碰 ⇒ 不进 [PATHS] 索引。
	dead_paths: tuple[str, ...] = ()
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


def request_skip(seeds: Seeds) -> frozenset[int]:
	"""``[REQUESTS]`` 渲染与冷层绑定**共用**的跳过集合。

	首个 pin 节点（通常是当前目标）已经在 ``[PIN]`` 里逐字出现过，``[REQUESTS]``
	里再来一行只是重复占位。这个表达式原先在 ``assemble`` 与 ``project`` 各写了一份：
	两份逻辑一旦漂移，渲染说「这行覆盖 A」、绑定说「这个句柄展开成 B」，
	可恢复性就被悄悄破坏。故收敛到这一个函数。
	"""
	return frozenset({seeds.pin_nodes[0]}) if seeds.pin_nodes else frozenset()


def _substantive(text: str) -> bool:
	s = strip_machine_blocks(text)
	if len(s) < 4:
		return False
	s = s.strip()
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
	"""错误是否已被后续成功证据覆盖（时效轴）。

	**判据只有一份实现**：``freshness.error_covered_by``（同类工具成功 / 成功改写同一
	文件）。原先这里有一份更宽松的副本（只要求「同一工具 + 成功标记」，且无文件引用时
	完全不要求指认现场），它会把「无引用的命令失败」判成已解决，与 [UNRESOLVED] 想表达
	的「还在的坑」不符。两份口径一旦漂移，热层显示与实际覆盖关系就会互相矛盾。
	"""
	from synaptic.freshness import error_covered_by

	return error_covered_by(graph, n, len(graph.nodes)) is not None


def _unresolved_error_nodes(graph: Graph) -> list[int]:
	"""未解决错误节点：之后没有针对同一现场的成功同类动作。"""
	return [
		n.idx
		for n in graph.nodes
		if n.is_error and n.error_sig and not _is_resolved(graph, n)
	]


def _todo_items(messages: list[dict], graph: Graph) -> list[str]:
	"""Current observed list, with legacy input fallback."""
	return list(latest_todo_snapshot(messages).items)



def collect_seeds(
	graph: Graph,
	messages: list[dict],
	file_states: dict[str, FileState],
	*,
	goal_override: str = "",
	superseded: frozenset[int] = frozenset(),
	resolved_errors: frozenset[int] = frozenset(),
	drop_constraints: frozenset[str] = frozenset(),
	region_end: int = 0,
) -> Seeds:
	"""收集种子并给出 PIN 节点/路径。

	``superseded`` 是时效轴（``synaptic.freshness``）判定的**已被后续断言覆盖**的
	节点集合：它们已经降级（移出热层 + 句柄留底），不再当种子重复占用热层。
	"""
	trace: list[dict[str, str]] = []

	user_nodes = [
		n for n in graph.nodes
		if n.kind == KIND_USER and _substantive(n.text) and n.idx not in superseded
	]
	original_task = strip_machine_blocks(user_nodes[0].text, preserve_layout=True) if user_nodes else ""
	if original_task:
		trace.append({"kind": "goal", "src": f"user#{user_nodes[0].idx}", "why": "首个实质用户目标"})

	# 后继用户消息**不再**进 PIN（规则 1）。
	# 理由有两条，缺一不可：
	#   1) 冗余：未被保护的尾部本来就逐字带着最近的用户消息，再钉进热层是重复计费；
	#   2) KV 敌对：它们逐轮必变，而此前它们排在热层 offset 0 之后不远处，一变就让
	#      其后 [MAIN]/[DECISIONS]/[PRUNED] 数千 token 的稳定内容全部前缀失效。
	# 目标/约束由下面两条抽取式种子承担（稳定），近期原话由尾部承担（逐字）。
	# 详见 docs/synaptic-compression.md §11.8。
	# 目标整句不重复占 [CONSTRAINTS]：同一句原话在同一枪里只出现一次。
	# 现场（sess_musrbw08_n9tly2 第 1 轮）：首条消息整句含"必须/不能"，同时成为
	# 「目标」pin 与被抽取命中的「约束」pin，模型读到两行逐字相同的句子。
	goal_norm = " ".join((goal_override.strip() or original_task).casefold().split())
	task_norm = " ".join(original_task.casefold().split())
	target_norms = {t for t in (goal_norm, task_norm) if t}
	constraints: list[str] = []
	for n in user_nodes:
		for c in extract_constraints(strip_machine_blocks(n.text)):
			if " ".join(c.casefold().split()) in target_norms:
				trace.append({"kind": "constraint_skip", "src": f"user#{n.idx}", "why": "整句即目标"})
				continue
			constraints.append(c)
			trace.append({"kind": "constraint", "src": f"user#{n.idx}", "why": f"约束句: {c[:48]}"})
	constraints = [c for c in dict.fromkeys(constraints) if c not in drop_constraints]

	# 未解决 = 识别到的失败 − 时效轴判定已被覆盖的失败 − 显式降级集。
	# 口径唯一来自 ``freshness``（``_is_resolved`` 只是它的转发），此处不重算。
	err_nodes = [
		n.idx
		for n in graph.nodes
		if n.is_error
		and n.error_sig
		and n.idx not in resolved_errors
		and n.idx not in superseded
	]
	# 次序用「首现次序」而非排序——实测排序更差（[UNRESOLVED] 前缀失稳率 6% → 15%）：
	# graph.nodes 按 idx 升序，故首现次序等价于「按最早存活实例下标排序」，它把段首
	# 锚定在**最老的未解决错误**上（极稳）；改成字典序后段首变成「字典序最小的签名」，
	# 该签名一消失段首就换人。两者都不完美，但前者实测更稳。
	# 同因归组：同一根因的多次失败合成一条并标次数（`×3`）。
	# 次数本身是信息（「这条路试了三次都没通」），比把 12 个不同问题压成同一行
	# 「退出码 1」有用得多；句柄仍指向全部实例（节点级恢复不受影响）。
	_sig_counts: dict[str, int] = {}
	for _i in err_nodes:
		_s = graph.nodes[_i].error_sig
		_sig_counts[_s] = _sig_counts.get(_s, 0) + 1
	unresolved = tuple(
		f"{_s}（×{_sig_counts[_s]}）" if _sig_counts[_s] > 1 else _s
		for _s in dict.fromkeys(graph.nodes[i].error_sig for i in err_nodes)
	)
	for i in err_nodes:
		trace.append(
			{"kind": "unresolved_error", "src": f"msg#{i}", "why": graph.nodes[i].error_sig[:64]}
		)

	todo_snapshot = latest_todo_snapshot(messages)
	todos = todo_snapshot.items
	for t in todos:
		trace.append({"kind": "todo", "src": "todo_tool", "why": t[:64]})

	# PIN 节点：用户消息 + 未解决错误 + TODO 所在节点
	pin_nodes: list[int] = [n.idx for n in user_nodes]
	pin_nodes.extend(err_nodes)
	if todo_snapshot.backing >= 0:
		pin_nodes.append(todo_snapshot.backing)

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
		todo_source=todo_snapshot.backing,
		todo_observed=todo_snapshot.observed,
		todo_active_count=todo_snapshot.active_count,
		pin_nodes=tuple(dict.fromkeys(pin_nodes)),
		pin_paths=tuple(dict.fromkeys(pin_paths)),
		user_nodes=tuple(n.idx for n in user_nodes),
		trace=trace,
	)


# 关键信息针（用于「即时关键信息保留」的非同义反复度量）

def recent_paths(graph: Graph, *, region_end: int | None = None) -> tuple[str, ...]:
	"""区域内后 25% 节点触碰过的路径（近期工作集口径）。

	与 ``harvest_needles`` 的 ``path_recent`` 共用同一实现，避免「哪个路径算近期」
	在种子收集与工作集排序之间出现两套口径。
	"""
	limit = region_end if region_end is not None else 1 << 30
	nodes = [n for n in graph.nodes if n.idx < limit]
	cut = int(len(nodes) * 0.75)
	out: list[str] = []
	for n in nodes[cut:]:
		out.extend(n.refs)
	return tuple(dict.fromkeys(x for x in out if x))


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
			users.append(strip_machine_blocks(n.text)[:80])

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
	recent = list(recent_paths(graph, region_end=region_end))

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
