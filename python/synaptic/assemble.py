"""热层组装（规则 3 / 规则 6）+ 双组装模式。

两种模式在 KV 前缀上是对立的：
- ``closure``：每次全量重排，压缩率最高，但每一轮都付一次前缀 miss；
- ``append_only``：稳定区字节冻结，新信息只以「增量行」追加，旧行永不改写
  （与生产链 ``memory.runtime.try_extend_c2`` 同一条纪律），代价是热层会
  随时间单调变胖，超出追加预算才整层重建。

本模块把两者的取舍做成可测量量（``rebuilt`` / LCP token），而不是靠断言。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from synaptic.filestate import render_file_state
from synaptic.graph import Graph
from synaptic.prune import render_card
from synaptic.seeds import Seeds
from synaptic.textutil import node_token_len
from synaptic.types import (
	KIND_ASST_TEXT,
	KIND_OTHER,
	KIND_USER,
	MODE_APPEND_ONLY,
	MODE_CLOSURE,
	Pin,
	PruneCard,
	WscParams,
	FileState,
)

H_CONSTRAINTS = "[CONSTRAINTS]"
H_UNRESOLVED = "[UNRESOLVED]"
H_TODO = "[TODO]"
H_WORKING = "[WORKING SET]"
H_MAIN = "[MAIN]"
H_DECISIONS = "[DECISIONS]"
H_PRUNED = "[PRUNED]"
H_NEXT = "[NEXT]"
#: 区域内用户原话的渲染通道（规则 1 补丁）。规则 1 删掉 ``指令`` 段后，
#: ``render_main`` 跳过 ``pin_nodes`` ⇒ 区域内用户消息一度**完全没有**渲染通道
#: （既是信息空洞，又因为 pin 不被剪 ⇒ 连 expand 句柄都没有 = 不可恢复）。
#: 该段按 idx 升序发射，天然只追加不移位。
H_REQUESTS = "[REQUESTS]"

#: 固定先验序（stable_prefix_ordering=False 时使用；也是动态排序的初始次序与平局裁决）。
#: 依据：越靠前越应当稳定。CONSTRAINTS 只随新约束追加；UNRESOLVED 会因「错误被解决」
#: 而从中间被摘除；WORKING SET 的文件状态只在原地改写；TODO 的状态原地改写最频繁。
#: REQUESTS 排在最后：它随用户回合线性增长，是所有段里最"会长"的一个——按规则 8
#: 的因果（会长者靠后），它是最后一个。
_SECTION_PRIOR: tuple[str, ...] = (
	H_CONSTRAINTS,
	H_UNRESOLVED,
	H_DECISIONS,
	H_PRUNED,
	H_WORKING,
	H_MAIN,
	H_TODO,
	H_NEXT,
	H_REQUESTS,
)


def _one_line(text: str, limit: int = 0) -> str:
	s = " ".join(str(text or "").split())
	if limit and len(s) > limit:
		return s[: limit - 1] + "…"
	return s


@dataclass
class SegStat:
	"""一个热层段落的逐轮观测统计（自检 + 排序依据）。"""

	obs: int = 0
	#: 文本有任何变化（含只在末尾追加）
	changed: int = 0
	#: 前缀失稳：新文本不再以上一轮文本开头 —— 这才是 KV 前缀失效的判据
	front_break: int = 0

	@property
	def change_rate(self) -> float:
		return self.changed / max(1, self.obs)

	@property
	def front_rate(self) -> float:
		return self.front_break / max(1, self.obs)


# ---------------------------------------------------------------------------
# PIN 集
# ---------------------------------------------------------------------------

def build_pins(seeds: Seeds) -> tuple[Pin, ...]:
	"""强制 PIN 集：目标 / 约束 / 未解决错误 / TODO——永不压缩。

	**后继用户消息（原 ``指令`` 段）不在此列**：规则 1 规定「未被保护的尾部已逐字
	携带的内容，一律不得进 PIN」。它们在尾部已经免费存在，放进 PIN 等于冗余计费，
	且因为逐轮必变、位置靠前，会让其后全部稳定内容每轮失去 KV 前缀。
	见 docs/synaptic-compression.md §11.8。
	"""
	pins: list[Pin] = []
	if seeds.original_task:
		pins.append(Pin("goal", "目标", seeds.original_task))
	if seeds.goal and seeds.goal != seeds.original_task:
		pins.append(Pin("goal_current", "当前目标", seeds.goal))
	for i, c in enumerate(seeds.constraints):
		pins.append(Pin(f"constraint:{i}", "约束", c))
	for i, e in enumerate(seeds.unresolved_errors):
		pins.append(Pin(f"unresolved:{i}", "未解决", e))
	for i, t in enumerate(seeds.todos):
		pins.append(Pin(f"todo:{i}", "TODO", t))
	return tuple(pins)


def pin_line(p: Pin) -> str:
	return f"{p.label}: {_one_line(p.text, 400)}"


def render_pins(pins: tuple[Pin, ...]) -> list[tuple[str, str]]:
	return [(f"pin:{p.key}", pin_line(p)) for p in pins]


def pin_group(p: Pin) -> str:
	"""PIN 条目归属的热层段落（规则 2 把原单一 ``[PIN]`` 拆成三段）。"""
	if p.key.startswith("unresolved:"):
		return H_UNRESOLVED
	if p.key.startswith("todo:"):
		return H_TODO
	return H_CONSTRAINTS



# ---------------------------------------------------------------------------
# 主链骨架
# ---------------------------------------------------------------------------

def _skeleton_of(node, limit: int = 140) -> str:
	"""节点的一行骨架（去噪留结论）。"""
	if node is None:
		return ""
	if node.kind == KIND_OTHER:
		line = _one_line(node.text, 80)
		return f"系统: {line}" if line else "系统消息"
	if node.kind == KIND_ASST_TEXT:
		line = _one_line(node.text, max(20, limit - 6))
		return f"结论: {line}" if line else "助手文本"
	head = f"{node.tool_name or node.kind}"
	if node.refs:
		head += f" {node.refs[0]}"
	if node.error_sig:
		head += f" 失败: {node.error_sig}"
	elif node.is_write:
		head += " 写入"
	elif node.read_only:
		head += " 只读"
	return head[:limit]


def emitted_tokens(node, params: WscParams, *, is_pin: bool) -> int:
	"""节点在热层里**实际占用**的 token（不是原文体积）。

已进 PIN 的节点、空文本节点 → 0；小节点内联原文 → 原文；大节点 → 骨架行。

预算必须按「发射成本」而不是「原文体积」记账。否则 PIN 段里的长用户消息会
按原文 token 吃掉整块主链预算，主链退化成只剩剪枝卡——这正是首轮冒烟的结果。
	"""
	if is_pin or not node.text.strip():
		return 0
	if node.tokens <= params.inline_max_tokens:
		return node.tokens
	return node_token_len(_skeleton_of(node))


def render_main(
	graph: Graph,
	kept: tuple[int, ...],
	params: WscParams,
	*,
	pin_nodes: frozenset[int],
) -> list[tuple[str, str]]:
	"""主链：小节点留原文，大节点只留骨架 + 展开句柄（去噪留结论）。"""
	out: list[tuple[str, str]] = []
	for idx in kept:
		node = graph.node(idx)
		if node is None or idx in pin_nodes:
			continue
		if not node.text.strip():
			continue
		if node.tokens <= params.inline_max_tokens:
			line = f"#{idx} {_one_line(node.text, 400)}"
		else:
			line = f"#{idx} {_skeleton_of(node)} expand(node://{idx})"
		out.append((f"main:{idx}", line))
	return out


def render_decisions(cards: tuple[PruneCard, ...]) -> list[tuple[str, str]]:
	"""[DECISIONS]：已排除分支（带错误签名的卡）。"""
	return [
		(f"card:{c.card_id}", f"已排除: {c.conclusion}  expand({c.handle})")
		for c in cards
		if c.error_sig
	]
def render_pruned(cards: tuple[PruneCard, ...]) -> list[tuple[str, str]]:
	"""[PRUNED]：其余被剪分支（每条卡只出现一次，不在 DECISIONS 里重复）。"""
	return [
		(f"card:{c.card_id}", render_card(c)) for c in cards if not c.error_sig
	]


def render_working_set(states: tuple[FileState, ...]) -> list[tuple[str, str]]:
	return [(f"fs:{s.path}", render_file_state(s)) for s in states]
def render_next(graph: Graph, seeds: Seeds, kept: tuple[int, ...]) -> list[tuple[str, str]]:
	"""[NEXT] 段（默认关）。

	内容本身是「事实」而非「指令」，但它出现在注意力里的位置与语气会被读成
	导演。按 XEYO 引擎铁律（注意力里只出现信息，不出现导演）默认关闭，
	开启时报告必须标注——见 docs/synaptic-compression.md「与引擎铁律的冲突」。
	"""
	if not seeds.unresolved_errors:
		return []
	return [("next:0", f"未解决: {_one_line(seeds.unresolved_errors[0], 160)}")]


def render_requests(
	graph: Graph,
	region_end: int,
	params: WscParams,
	*,
	skip: frozenset[int],
	user_nodes: tuple[int, ...],
) -> list[tuple[str, str]]:
	"""``[REQUESTS]``：区域内（未被尾部逐字携带的）用户原话。

	规则 1 删掉 ``指令`` 段后留下的信息空洞就补在这里。三条边界：
	1. 只取 ``idx < region_end`` 的节点——尾部（``>= region_end``）本来就逐字携带，
	   再进热层是重复计费（规则 1 的原则不变）；
	2. ``skip`` 排除已作为 ``目标`` pin 渲染的首个用户节点，避免同一条话出现两次；
	3. 节点集合由 ``seeds.user_nodes`` 给出，**不在这里按 kind 扫图**：
	   ``kind == KIND_USER`` 上还挂着工具结果与引擎注入的伪用户消息
	   （199 回合会话里区域内 188 个 kind=user，实质人类消息只有 17 条），
	   按 kind 扫会把工具结果当用户原话导出（踩过，见 ``Seeds.user_nodes`` 注释）。

	按 idx 升序发射 ⇒ 新用户消息只会追加在段尾，段内永不重排；
	``region_end`` 单调右移 ⇒ 一个用户节点一旦进入该段就**不会**被移出
	（它始终满足 ``idx < region_end``）⇒ 集合只增不减，段本身 append-only。

	每条附 ``expand(node://<idx>)``：内联的是截断摘要，全文经冷层句柄取回，
	保证「无损可恢复」这条数据不被截断悄悄破坏。
	"""
	out: list[tuple[str, str]] = []
	for idx in user_nodes:
		if idx >= region_end or idx in skip:
			continue
		n = graph.node(idx)
		if n is None or n.kind != KIND_USER:
			continue
		text = _one_line(n.text, params.request_excerpt_chars)
		if not text:
			continue
		out.append((f"req:{idx}", f"#{idx} 用户: {text} expand(node://{idx})"))
	return out


# ---------------------------------------------------------------------------
# 组装器（带 append_only 状态）
# ---------------------------------------------------------------------------

@dataclass
class AssemblyState:
	level: str = ""
	mode: str = ""
	full_text: str = ""
	emitted: dict[str, str] = field(default_factory=dict)
	appended: tuple[str, ...] = ()
	base_tokens: int = 0
	#: 逐段自检统计（观测数 / 变动数 / 前缀失稳数）
	seg_stats: dict[str, SegStat] = field(default_factory=dict)
	#: 上一轮各段的渲染文本（算变动率与前缀失稳的基准）
	seg_text: dict[str, str] = field(default_factory=dict)
	#: 上一轮实际采用的段落次序（滞回基准）
	seg_order: tuple[str, ...] = ()
	#: 当前次序已连续保持的轮数（驻留期，未满不许再换序）
	seg_order_age: int = 0
	#: 自检告警（段落逐轮变动率超阈）
	churn_warn: tuple[str, ...] = ()
	#: 规则 8 日志：(段头, 行) 按**首次发射顺序**排列，只追加、不重排、不改写
	journal: tuple[tuple[str, str], ...] = ()
	#: 距上次重冻结累计追加的 token（决定何时压回紧凑渲染）
	journal_since_freeze: int = 0
	#: 区域内用户原话的渲染审计（渲染数 / 区域内总数）
	req_rendered: int = 0
	req_total: int = 0
	#: 本轮日志新增条目数（0 = 本轮投影是上一轮的严格前缀，KV 零损失）
	journal_appends: int = 0

	def clone(self) -> "AssemblyState":
		return AssemblyState(
			level=self.level,
			mode=self.mode,
			full_text=self.full_text,
			emitted=dict(self.emitted),
			appended=tuple(self.appended),
			base_tokens=self.base_tokens,
			seg_stats={k: SegStat(v.obs, v.changed, v.front_break) for k, v in self.seg_stats.items()},
			seg_text=dict(self.seg_text),
			seg_order=tuple(self.seg_order),
			seg_order_age=self.seg_order_age,
			churn_warn=tuple(self.churn_warn),
			journal=tuple(self.journal),
			journal_since_freeze=self.journal_since_freeze,
			req_rendered=self.req_rendered,
			req_total=self.req_total,
			journal_appends=self.journal_appends,
		)


def _segment_groups(
	graph: Graph,
	seeds: Seeds,
	pins: tuple[Pin, ...],
	fs: tuple[FileState, ...],
	cards: tuple[PruneCard, ...],
	kept: tuple[int, ...],
	params: WscParams,
	*,
	region_end: int = 0,
) -> dict[str, list[tuple[str, str]]]:
	"""渲染成「段落 → 行」的分组（尚未排序）。

	规则 2 把原单一 ``[PIN]`` 拆成 ``[CONSTRAINTS]`` / ``[UNRESOLVED]`` / ``[TODO]``：
	这三者的逐轮变动频率差一个量级，混在一段里排序就没意义了。
	"""
	pin_nodes = frozenset(seeds.pin_nodes)
	out: dict[str, list[tuple[str, str]]] = {}
	for p in pins:
		out.setdefault(pin_group(p), []).append((f"pin:{p.key}", pin_line(p)))
	if fs:
		out[H_WORKING] = render_working_set(fs)
	main = render_main(graph, kept, params, pin_nodes=pin_nodes)
	if main:
		out[H_MAIN] = main
	dec = render_decisions(cards)
	if dec:
		out[H_DECISIONS] = dec
	pruned = render_pruned(cards)
	if pruned:
		out[H_PRUNED] = pruned
	req = render_requests(
		graph,
		region_end,
		params,
		skip=frozenset({seeds.pin_nodes[0]}) if seeds.pin_nodes else frozenset(),
		user_nodes=seeds.user_nodes,
	)
	if req:
		out[H_REQUESTS] = req
	if params.include_next:
		nxt = render_next(graph, seeds, kept)
		if nxt:
			out[H_NEXT] = nxt
	return out


def segment_text(items: list[tuple[str, str]]) -> str:
	return "\n".join(line for _, line in items)


def order_segments(
	present: set[str],
	stats: dict[str, SegStat],
	prev_order: tuple[str, ...],
	params: WscParams,
	*,
	allow_reorder: bool = True,
) -> tuple[str, ...]:
	"""按**前缀失稳率**升序排列段落（规则 2）。

	为什么不用「变动率」排序：只追加的段落（``[MAIN]`` 按节点下标升序发射，天然
	append-only）变动率很高但前缀逐字节稳定，放在前面反而最省 KV。用变动率排序会
	把这类段落排到末尾，方向正好相反。变动率仍然照算（自检要求），只是不作排序键。

	四条保序规则：
	1. 新出现的段落**按先验序插回它该在的位置**，而不是一律追加到末尾——否则
	   「错误出现/消失」这类真实新状态会被永远挤到最后；
	2. 只在相邻两段的前缀失稳率差距超过 ``churn_margin`` 时才交换——**次序本身
	   抖一次，就是一次比内容变化更严重的前缀失效**；
	3. 无观测（``obs == 0``）的段落不参与交换（没有证据就没有意见）；
	4. ``allow_reorder=False``（驻留期未满）时整段跳过交换，只做规则 1 的插入。
	"""
	prior = [h for h in _SECTION_PRIOR if h in present]
	if not params.stable_prefix_ordering or not prev_order:
		return tuple(prior)

	base = [h for h in prev_order if h in present]
	for h in prior:  # 1. 新段落插回先验位置
		if h in base:
			continue
		rank = _SECTION_PRIOR.index(h)
		pos = len(base)
		for i, x in enumerate(base):
			if _SECTION_PRIOR.index(x) > rank:
				pos = i
				break
		base.insert(pos, h)

	if not allow_reorder:
		return tuple(base)

	m = params.churn_margin
	for i in range(len(base) - 1):  # 2/3. 有证据才交换，且要拉开差距
		a, b = base[i], base[i + 1]
		sa, sb = stats.get(a), stats.get(b)
		if sa is None or sb is None or sa.obs == 0 or sb.obs == 0:
			continue
		if sb.front_rate + m < sa.front_rate:
			base[i], base[i + 1] = b, a
	return tuple(base)


def _render_full(sections: list[tuple[str, list[tuple[str, str]]]]) -> str:
	lines: list[str] = []
	for header, items in sections:
		lines.append(header)
		lines.extend(line for _, line in items)
	return "\n".join(lines)


# ---------------------------------------------------------------------------
# 规则 8：日志布局
# ---------------------------------------------------------------------------

def _journal_key(header: str, line: str) -> str:
	"""日志条目身份 = 内容摘要。

	用**内容寻址**而不是「段+条目键」：``fs:<path>`` 这类条目的值会随文件状态变化，
	按键去重会退化成「原地改写」，而改写正是要消灭的东西。内容寻址下，
	「同一个文件的新状态」是一条**新事实**，追加在日志尾部，旧事实留在原地——
	既单调又如实（日志本来就该长这样）。
	"""
	import hashlib

	return hashlib.sha1(f"{header}\x00{line}".encode("utf-8")).hexdigest()[:16]


def _journal_text(journal: tuple[tuple[str, str], ...]) -> str:
	"""日志 → 投影文本。每行自带段头，故不存在「段头行」这种会被重排的元素。"""
	return "\n".join(f"{h} {line}" for h, line in journal)


def _journal_seg_text(journal: tuple[tuple[str, str], ...]) -> dict[str, str]:
	"""按段聚合的**累积**文本（自检口径）。

	日志布局下每段的累积文本只增不改 ⇒ 前缀失稳率恒为 0。这是结构使然而非
	「变好了」，所以报告里同时给出 ``journal_appends``（本轮是否真的零损失）
	与重冻结次数，避免拿一个恒为 0 的数当成绩。
	"""
	out: dict[str, list[str]] = {}
	for h, line in journal:
		out.setdefault(h, []).append(line)
	return {h: "\n".join(v) for h, v in out.items()}



def assemble(
	graph: Graph,
	seeds: Seeds,
	pins: tuple[Pin, ...],
	fs: tuple[FileState, ...],
	cards: tuple[PruneCard, ...],
	kept: tuple[int, ...],
	params: WscParams,
	*,
	prev: AssemblyState | None = None,
	region_end: int = 0,
) -> tuple[str, bool, AssemblyState, list[dict[str, str]]]:
	"""组装热层。返回 (文本, 是否发生前缀失效, 新状态, 审计留痕)。"""
	trace: list[dict[str, str]] = []

	# ---- 段落渲染 + 定序 ----
	# 定序只用**上一轮已观测**的统计：拿本轮的果去定本轮的序是因果倒置
	# （旧实现如此，且会在同一轮里让「刚观察到的失稳」立刻改写次序）。
	groups = _segment_groups(
		graph, seeds, pins, fs, cards, kept, params, region_end=region_end
	)
	stats: dict[str, SegStat] = {
		k: SegStat(v.obs, v.changed, v.front_break) for k, v in (prev.seg_stats if prev else {}).items()
	}
	order = order_segments(
		set(groups),
		stats,
		prev.seg_order if prev else (),
		params,
		allow_reorder=bool(prev) and prev.seg_order_age >= params.churn_dwell,
	)
	age = 0 if (prev is None or order != prev.seg_order) else prev.seg_order_age + 1
	sections = [(h, groups[h]) for h in order]
	full = _render_full(sections)
	prev_seg_text = prev.seg_text if prev else {}
	# [REQUESTS] 覆盖率审计：分子分母必须同源，否则报出的是假缺口。
	# 分母用 seeds.user_nodes（_substantive 过滤后的实质人类消息），与 render_requests
	# 的输入同源。**不要**按 kind == KIND_USER 数——那会把非实质节点算进分母（199 vs 188），
	# 看起来像漏渲染，其实只是口径不同（踩过）。
	req_total = sum(1 for i in seeds.user_nodes if i < region_end)
	req_rendered = len(groups.get(H_REQUESTS, ()))
	if (
		seeds.pin_nodes
		and seeds.pin_nodes[0] < region_end
		and seeds.pin_nodes[0] in seeds.user_nodes
	):
		# 首个用户节点渲染成 [CONSTRAINTS] 的「目标」pin，不占 [REQUESTS] 行，
		# 但它在热层里可见 ⇒ 覆盖率要把它算进去。
		req_rendered += 1

	def _finish(
		text: str,
		seg_text: dict[str, str],
		emitted: dict[str, str],
		appended: tuple[str, ...],
		base: int,
		*,
		journal: tuple[tuple[str, str], ...] = (),
		since_freeze: int = 0,
		rebuilt: bool = False,
		appends: int = 0,
	) -> tuple[str, bool, AssemblyState, list[dict[str, str]]]:
		"""公共收尾：**先定稿文本，再据定稿文本算自检**（规则 3 口径修正）。

		旧实现在模式分支之前就算自检，统计的是「冻结前的重渲染文本」——于是
		append_only 报出来的 churn 表与 closure 逐字相同，而它的最终投影是
		字节冻结的。先定稿再统计，自检表才描述真正发出去的那段文本。
		"""
		for h, txt in seg_text.items():
			st = stats.setdefault(h, SegStat())
			before = prev_seg_text.get(h)
			if before is None:
				continue
			st.obs += 1
			if txt != before:
				st.changed += 1
			if not txt.startswith(before):
				st.front_break += 1
		warn: list[str] = []
		for h in order:
			st = stats[h]
			if st.obs >= params.churn_min_obs and st.change_rate > params.churn_warn_rate:
				warn.append(
					f"{h} 逐轮变动率 {st.change_rate:.0%}（阈值 {params.churn_warn_rate:.0%}，"
					f"前缀失稳率 {st.front_rate:.0%}，观测 {st.obs} 轮）"
				)
		if warn:
			trace.append({"mode": params.mode, "action": "churn_warn", "why": "；".join(warn)})
		if params.journal_layout:
			trace.append(
				{
					"mode": params.mode,
					"action": "journal",
					"why": f"新增 {appends} 条 / 日志 {node_token_len(text)} tok"
					+ ("（本轮重冻结）" if rebuilt else ""),
				}
			)
		return (
			text,
			rebuilt,
			AssemblyState(
				level=params.level,
				mode=params.mode,
				full_text=text,
				emitted=emitted,
				appended=appended,
				base_tokens=base,
				seg_stats=stats,
				seg_text=seg_text,
				seg_order=order,
				seg_order_age=age,
				churn_warn=tuple(warn),
				journal=journal,
				journal_since_freeze=since_freeze,
				req_rendered=req_rendered,
				req_total=req_total,
				journal_appends=appends,
			),
			trace,
		)

	# ---- 规则 8：日志布局 ----
	if params.journal_layout:
		prev_journal = (
			tuple(prev.journal) if (prev is not None and prev.mode == params.mode) else ()
		)
		fresh = tuple((h, line) for h in order for _k, line in groups[h])
		if not prev_journal:
			text = _journal_text(fresh)
			return _finish(
				text, _journal_seg_text(fresh), {}, (), node_token_len(text), journal=fresh
			)
		seen = {_journal_key(h, ln) for h, ln in prev_journal}
		new = tuple((h, ln) for h, ln in fresh if _journal_key(h, ln) not in seen)
		add_tok = sum(node_token_len(f"{h} {ln}") + 1 for h, ln in new)
		since = prev.journal_since_freeze + add_tok
		journal = prev_journal + new
		rebuilt = False
		if since > params.journal_growth_tokens:
			# 重冻结：日志胖到阈值 → 压回本轮的紧凑渲染。这是**唯一**的前缀失效来源，
			# 且它换来的是此后若干轮的零损失（摊薄）。
			trace.append(
				{
					"mode": params.mode,
					"action": "refreeze",
					"why": (
						f"日志累计追加 {since} tok > 预算 {params.journal_growth_tokens} tok "
						f"→ 压回紧凑渲染（一次前缀 miss）"
					),
				}
			)
			journal = fresh
			since = 0
			rebuilt = True
			appends = 0
		else:
			appends = len(new)
		text = _journal_text(journal)
		return _finish(
			text,
			_journal_seg_text(journal),
			{},
			(),
			node_token_len(text),
			journal=journal,
			since_freeze=since,
			rebuilt=rebuilt,
			appends=appends,
		)

	if params.mode == MODE_CLOSURE or prev is None or prev.mode != params.mode:
		rebuilt = prev is not None and prev.full_text != "" and not full.startswith(prev.full_text)
		emitted: dict[str, str] = {}
		for header, items in sections:
			emitted[f"hdr:{header}"] = header
			for key, line in items:
				emitted[key] = line
		trace.append(
			{
				"mode": MODE_CLOSURE,
				"action": "rebuild",
				"why": "closure 模式每轮全量重排",
			}
		)
		return _finish(
			full,
			{h: segment_text(groups[h]) for h in order},
			emitted,
			(),
			node_token_len(full),
			rebuilt=rebuilt,
		)

	# ---- append_only ----
	new_lines: list[str] = []
	new_by_h: dict[str, list[str]] = {}
	emitted = dict(prev.emitted)
	for header, items in sections:
		hkey = f"hdr:{header}"
		if emitted.get(hkey) != header:
			new_lines.append(header)
			emitted[hkey] = header
			new_by_h.setdefault(header, []).append(header)
		for key, line in items:
			if emitted.get(key) == line:
				continue  # 已在冻结前缀里且字节一致 → 零成本
			new_lines.append(line)
			emitted[key] = line
			new_by_h.setdefault(header, []).append(line)

	new_tokens = sum(node_token_len(ln) + 1 for ln in new_lines)
	if new_tokens > params.append_budget_tokens:
		# 追加预算被打爆 → 认一次整层重建（这正是 append_only 的失效点）
		trace.append(
			{
				"mode": MODE_APPEND_ONLY,
				"action": "rebuild",
				"why": f"追加预算超限 ({new_tokens}>{params.append_budget_tokens})",
			}
		)
		emitted = {}
		for header, items in sections:
			emitted[f"hdr:{header}"] = header
			for key, line in items:
				emitted[key] = line
		return _finish(
			full,
			{h: segment_text(groups[h]) for h in order},
			emitted,
			(),
			node_token_len(full),
			rebuilt=True,
		)

	appended = prev.appended + tuple(new_lines)
	text = prev.full_text
	if appended:
		text = text + "\n" + "\n".join(appended)
	trace.append(
		{
			"mode": MODE_APPEND_ONLY,
			"action": "append",
			"why": f"新增 {len(new_lines)} 行 / {new_tokens} tok",
		}
	)
	# 逐段累积文本：与 full_text 同步只追加，自检才描述真正发出去的文本
	seg_text: dict[str, str] = {}
	for header, items in sections:
		acc = prev_seg_text.get(header, "")
		add = "\n".join(new_by_h.get(header, []))
		seg_text[header] = (acc + "\n" + add) if (acc and add) else (acc or add)
	return _finish(
		text,
		seg_text,
		emitted,
		appended,
		prev.base_tokens + new_tokens,
		appends=len(new_lines),
	)



def pick_level(used_ratio: float) -> str:
	"""水位 → 压缩级别（设计文档§六的水位表）。"""
	if used_ratio >= 0.95:
		return "Hard"
	if used_ratio >= 0.85:
		return "Medium"
	if used_ratio >= 0.82:
		return "Medium+"
	if used_ratio >= 0.75:
		return "Light"
	return "Micro"
