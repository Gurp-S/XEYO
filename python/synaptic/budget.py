"""热层双预算：固定段闸 + 主链闸。

旧实现只把 ``hot_budget_tokens`` 用在 ``kept`` 选择上；``[REQUESTS]``、``[WORKING SET]``
等固定段在预算外生长，长会话因此系统性超预算。这里把总预算拆成两个显式、可审计的闸：

* 固定段：PIN / WORKING SET / REQUESTS / NEXT；
* 主链：MAIN / DECISIONS / PRUNED（项目选择阶段另用 ``_CARD_RESERVE_SEED`` 预扣）。

固定段内部优先级固定为 ``PIN > WORKING SET > REQUESTS``。预算不足时只降级 REQUESTS：
先缩短内联摘录，再退化成仅句柄行；``expand(node://<idx>)`` 永不丢，因此截断不会悄悄破坏
无损可恢复性。若 PIN + WORKING SET 自身已超固定预算，REQUESTS 仍保留句柄行并如实记
over-budget，而不是为了账面好看丢信息。
"""

from __future__ import annotations

from dataclasses import dataclass

from synaptic.coldstore import parse_reqs_payload
from synaptic.graph import Graph
from synaptic.textutil import node_token_len
from synaptic.types import KIND_USER, WscParams

Line = tuple[str, str]


def one_line(text: str, limit: int = 0) -> str:
	"""单行化；``limit`` 为正时保留尾部省略号。"""
	s = " ".join(str(text or "").split())
	if limit and len(s) > limit:
		return s[: limit - 1] + "…"
	return s


def excerpt_preserving_needle(text: str, limit: int = 0) -> str:
	"""按前 ``limit`` 个字符保留摘录，再追加省略号。

	关键信息针按原话前 80 字符判定；若沿用 ``one_line`` 的 ``limit-1 + …``，
	即便摘录档位标成 80，实际也只留下 79 个原字符，长原话会被误判为丢失。
	"""
	s = " ".join(str(text or "").split())
	if limit and len(s) > limit:
		return s[:limit] + "…"
	return s


def rendered_request_nodes(items: list[Line] | tuple[Line, ...]) -> frozenset[int]:
	"""返回 ``[REQUESTS]`` 行中句柄实际覆盖的节点集合。

	``render_requests_grouped`` 会把这些节点合并为 ``node://i,j,...``；
	``render_requests_compact`` 会把旧节点合并成 ``reqs://<首>-<末>``。
	覆盖率审计若直接数行数，会变成「分母逐节点、分子逐行」的异源口径（踩过）。

	**区间句柄按 [首, 末] 全展开是安全的**：调用方始终拿它与 ``request_nodes`` 求交，
	区间内混进的非用户节点会被交集滤掉；而区间内真正的用户节点，要么属于该块、
	要么属于按 idx 升序的相邻块——两种情形它们**都有出口**，不存在「虚报可见」。
	"""
	out: set[int] = set()
	for _key, line in items:
		marker = line.rfind("expand(node://")
		if marker >= 0:
			start = marker + len("expand(node://")
			end = line.find(")", start)
			if end >= 0:
				for part in line[start:end].split(","):
					part = part.strip()
					if part.isdigit():
						out.add(int(part))
		rmarker = line.rfind("expand(reqs://")
		if rmarker >= 0:
			start = rmarker + len("expand(reqs://")
			end = line.find(")", start)
			if end >= 0:
				span = parse_reqs_payload(line[start:end])
				if span is not None:
					out.update(range(span[0], span[1] + 1))
	return frozenset(out)


def _request_nodes(
	graph: Graph,
	region_end: int,
	*,
	skip: frozenset[int],
	user_nodes: tuple[int, ...],
) -> list[tuple[int, str]]:
	"""返回区域内可渲染的实质用户节点（idx, 原文）。"""
	out: list[tuple[int, str]] = []
	for idx in user_nodes:
		if idx >= region_end or idx in skip:
			continue
		n = graph.node(idx)
		if n is None or n.kind != KIND_USER or not n.text.strip():
			continue
		out.append((idx, n.text))
	return out


def _recent_verbatim_ids(user_nodes: tuple[int, ...], params: WscParams) -> frozenset[int]:
	"""最近 N 条用户节点（要求逐字可见的那一批）。``user_nodes`` 已按 idx 升序。"""
	k = max(0, int(params.request_recent_verbatim))
	if k <= 0:
		return frozenset()
	return frozenset(user_nodes[-k:])


def _node_excerpt_chars(
	idx: int,
	params: WscParams,
	*,
	recent: frozenset[int],
	override: int | None,
) -> int:
	"""单条用户节点的内联摘录上限（分层 + 80 字符硬地板）。

	硬地板的理由：关键信息针按原话前 80 字符判定，摘录低于 80 就等于「有摘录但针不可见」，
	报告会把它算成 ``user`` 针丢失（这是假缺口，但一样要避免——它会让降级阶梯失去刻度）。
	"""
	if override is not None:
		return max(0, int(override))
	old = max(80, int(params.request_excerpt_chars_old))
	full = max(old, int(params.request_excerpt_chars))
	return full if idx in recent else old


def render_requests(
	graph: Graph,
	region_end: int,
	params: WscParams,
	*,
	skip: frozenset[int],
	user_nodes: tuple[int, ...],
	excerpt_chars: int | None = None,
	handle_only: bool = False,
) -> list[Line]:
	"""渲染逐节点 ``[REQUESTS]``；每个节点一条独立句柄。

	分层：最近 ``request_recent_verbatim`` 条用完整摘录，更早的用 ``request_excerpt_chars_old``。
	"""
	recent = _recent_verbatim_ids(user_nodes, params)
	out: list[Line] = []
	for idx, text in _request_nodes(
		graph, region_end, skip=skip, user_nodes=user_nodes
	):
		if handle_only:
			line = f"#{idx} 用户 expand(node://{idx})"
		else:
			limit = _node_excerpt_chars(idx, params, recent=recent, override=excerpt_chars)
			text = excerpt_preserving_needle(text, limit)
			if not text:
				continue
			line = f"#{idx} 用户: {text} expand(node://{idx})"
		out.append((f"req:{idx}", line))
	return out


def render_requests_grouped(
	graph: Graph,
	region_end: int,
	params: WscParams,
	*,
	skip: frozenset[int],
	user_nodes: tuple[int, ...],
	excerpt_chars: int | None = None,
	handle_only: bool = False,
) -> list[Line]:
	"""按原话文本去重渲染 ``[REQUESTS]``。

	同一文本只保留一份摘录；该文本的所有原始节点合并进一个 ``node://i,j,...``
	组句柄，因此每个节点仍可从冷层无损拉回。预算不足时再退化成整组仅句柄。
	"""
	limit_default = params.request_excerpt_chars if excerpt_chars is None else excerpt_chars
	recent = _recent_verbatim_ids(user_nodes, params)
	groups: dict[str, list[int]] = {}
	texts: dict[str, str] = {}
	for idx, raw in _request_nodes(
		graph, region_end, skip=skip, user_nodes=user_nodes
	):
		key = " ".join(raw.split())
		if not key:
			continue
		groups.setdefault(key, []).append(idx)
		texts.setdefault(key, raw)
	out: list[Line] = []
	for key, idxs in groups.items():
		handle = "node://" + ",".join(str(i) for i in idxs)
		head = f"#{idxs[0]}"
		if len(idxs) > 1:
			head += f" 用户[{len(idxs)}]"
		else:
			head += " 用户"
		if handle_only:
			line = f"{head} expand({handle})"
		else:
			# 同一文本的节点可能横跨两个分层 ⇒ 取该组里**最宽松**的那一档
			# （组内文本完全相同，多留字符不会误导，只会少压一点）。
			limit = max(
				_node_excerpt_chars(i, params, recent=recent, override=excerpt_chars)
				if excerpt_chars is None
				else limit_default
				for i in idxs
			)
			text = excerpt_preserving_needle(texts[key], limit)
			if not text:
				continue
			line = f"{head}: {text} expand({handle})"
		out.append((f"reqgroup:{idxs[0]}", line))
	return out


def segment_tokens(items: list[Line] | tuple[Line, ...]) -> int:
	"""按实际发射行计 token；与 project.py 的固定段 overhead 使用同一口径。"""
	return sum(node_token_len(line) + 1 for _, line in items)


@dataclass(frozen=True)
class HotBudgetAudit:
	"""本轮双预算的实际账目。"""

	fixed_budget_tokens: int
	main_budget_tokens: int
	fixed_tokens: int
	main_tokens: int
	request_tokens: int
	request_mode: str
	request_excerpt_chars: int
	fixed_overflow_tokens: int
	main_overflow_tokens: int

	def as_dict(self) -> dict[str, int | str]:
		return {
			"fixed_budget_tokens": self.fixed_budget_tokens,
			"main_budget_tokens": self.main_budget_tokens,
			"fixed_tokens": self.fixed_tokens,
			"main_tokens": self.main_tokens,
			"request_tokens": self.request_tokens,
			"request_mode": self.request_mode,
			"request_excerpt_chars": self.request_excerpt_chars,
			"fixed_overflow_tokens": self.fixed_overflow_tokens,
			"main_overflow_tokens": self.main_overflow_tokens,
		}

	def describe(self) -> str:
		return (
			f"fixed {self.fixed_tokens}/{self.fixed_budget_tokens} tok, "
			f"main {self.main_tokens}/{self.main_budget_tokens} tok, "
			f"requests={self.request_mode}@{self.request_excerpt_chars}"
			+ (f", fixed_over={self.fixed_overflow_tokens}" if self.fixed_overflow_tokens else "")
			+ (f", main_over={self.main_overflow_tokens}" if self.main_overflow_tokens else "")
		)


def _excerpt_ladder(initial: int) -> list[int]:
	"""从完整摘录逐级减半到 16 字符；保持确定性且覆盖明显不同的压缩档。"""
	x = max(1, int(initial))
	out = [x]
	while x > 16:
		x = max(16, x // 2)
		if x not in out:
			out.append(x)
	return out


def apply_hot_budgets(
	groups: dict[str, list[Line]],
	params: WscParams,
	*,
	graph: Graph,
	region_end: int,
	request_header: str,
	request_skip: frozenset[int],
	user_nodes: tuple[int, ...],
	fixed_headers: tuple[str, ...],
	main_headers: tuple[str, ...],
) -> tuple[dict[str, list[Line]], HotBudgetAudit]:
	"""对已渲染的 ``groups`` 应用固定段/主链预算并返回副本与审计。

	调用方负责先完成完整渲染；这里不会改 journal 里的旧行，只决定**本轮新增/重冻结**
	时应当发射哪一版文本。日志布局下旧行仍按 append-only 保留，重冻结时自动收敛到本次
	预算后的紧凑版本。
	"""
	out = {h: list(items) for h, items in groups.items()}
	fixed_other = sum(
		segment_tokens(out.get(h, ())) for h in fixed_headers if h != request_header
	)
	request_available = max(0, int(params.fixed_segment_budget_tokens) - fixed_other)
	req = out.get(request_header, [])
	mode = "none" if not req else "full"
	excerpt = int(params.request_excerpt_chars)

	if req and segment_tokens(req) > request_available:
		# 先试「按原话去重」：重复用户消息只保留一份摘录，其余节点用组句柄覆盖。
		# 这比直接退化成仅句柄保留了文本针，又比逐节点摘录更省固定预算。
		chosen: list[Line] | None = None
		grouped_full = render_requests_grouped(
			graph,
			region_end,
			params,
			skip=request_skip,
			user_nodes=user_nodes,
		)
		if grouped_full and segment_tokens(grouped_full) <= request_available:
			chosen = grouped_full
			mode = "dedup"
			excerpt = int(params.request_excerpt_chars)
		else:
			# 关键信息针按前 80 字符判定；低于 80 的摘录不再算文本保留，
			# 直接退整组仅句柄，避免报出「有摘录但针不可见」的假覆盖。
			for cut in [x for x in _excerpt_ladder(excerpt)[1:] if x >= 80]:
				candidate = render_requests_grouped(
					graph,
					region_end,
					params,
					skip=request_skip,
					user_nodes=user_nodes,
					excerpt_chars=cut,
				)
				if candidate and segment_tokens(candidate) <= request_available:
					chosen = candidate
					mode = "dedup_short"
					excerpt = cut
					break
		if chosen is None:
			# 用户原话的文本针优先级高于固定段预算：离预算只差一点时，
			# 仍保留每段原话的前 80 字符，否则 long-session 会静默退化成
			# 纯句柄并让 needle_survival.user 掉档。溢出在下面的审计里如实记账。
			chosen = render_requests_grouped(
				graph,
				region_end,
				params,
				skip=request_skip,
				user_nodes=user_nodes,
				excerpt_chars=80,
			)
			if chosen:
				mode = "dedup_min80_overflow"
				excerpt = 80
			else:
				chosen = render_requests(
					graph,
					region_end,
					params,
					skip=request_skip,
					user_nodes=user_nodes,
					handle_only=True,
				)
				mode = "handles"
				excerpt = 0
		if chosen:
			out[request_header] = chosen
		else:
			out.pop(request_header, None)

	fixed_tokens = sum(segment_tokens(out.get(h, ())) for h in fixed_headers)
	main_tokens = sum(segment_tokens(out.get(h, ())) for h in main_headers)
	request_tokens = segment_tokens(out.get(request_header, ()))
	audit = HotBudgetAudit(
		fixed_budget_tokens=int(params.fixed_segment_budget_tokens),
		main_budget_tokens=int(params.main_segment_budget_tokens),
		fixed_tokens=fixed_tokens,
		main_tokens=main_tokens,
		request_tokens=request_tokens,
		request_mode=mode,
		request_excerpt_chars=excerpt,
		fixed_overflow_tokens=max(0, fixed_tokens - int(params.fixed_segment_budget_tokens)),
		main_overflow_tokens=max(0, main_tokens - int(params.main_segment_budget_tokens)),
	)
	return out, audit


def request_chunk_ids(
	graph: Graph,
	region_end: int,
	params: WscParams,
	*,
	skip: frozenset[int],
	user_nodes: tuple[int, ...],
) -> list[tuple[int, int, tuple[int, ...]]]:
	"""旧用户节点的分块 ``[(首, 末, idxs)]``（P1-b）。

	**渲染与冷层绑定必须共用这一个实现**：渲染侧决定「哪一行写哪个区间」，
	绑定侧决定「那个区间展开回哪些节点」。两处各写一份分块逻辑，就会出现
	「行里写的区间」与「句柄绑定的节点集」不一致——那正是可恢复性被悄悄破坏的形态。
	"""
	recent = _recent_verbatim_ids(user_nodes, params)
	items = [
		(idx, text)
		for idx, text in _request_nodes(graph, region_end, skip=skip, user_nodes=user_nodes)
		if idx not in recent
	]
	size = max(1, int(params.request_old_group_size))
	out: list[tuple[int, int, tuple[int, ...]]] = []
	for i in range(0, len(items), size):
		chunk = items[i : i + size]
		idxs = tuple(idx for idx, _ in chunk)
		out.append((idxs[0], idxs[-1], idxs))
	return out


def render_requests_compact(
	graph: Graph,
	region_end: int,
	params: WscParams,
	*,
	skip: frozenset[int],
	user_nodes: tuple[int, ...],
) -> list[Line]:
	"""``[REQUESTS]`` 的紧凑形态（P1-b）：旧节点合并成区间句柄，行数封顶。

	行数是这段**唯一**的真实开销来源：每行约 10–15 token（``#<idx>`` + 头部 + ``expand(...)``），
	实测 93 行/回合 ≈ 1565 token。摘录字符数不是瓶颈——用户原话普遍短于上限时，
	320 与 80 两档输出逐字相同（见 docs §12.7 的负向结果与账目复核）。

	发射顺序：**旧块（按 idx 升序）在前，最近 K 条在后**。理由与 ``[PATHS]`` 同一条：
	新内容一律追加在段尾，段内不因「某条原话翻进/翻出近期窗口」而整体重排。
	"""
	recent = _recent_verbatim_ids(user_nodes, params)
	out: list[Line] = []
	for first, last, idxs in request_chunk_ids(
		graph, region_end, params, skip=skip, user_nodes=user_nodes
	):
		if len(idxs) == 1:
			out.append((f"req:{first}", f"#{first} 用户 expand(node://{first})"))
			continue
		out.append(
			(
				f"reqs:{first}",
				f"#{first}…{last} 用户[{len(idxs)}] expand(reqs://{first}-{last})",
			)
		)
	for idx, text in _request_nodes(graph, region_end, skip=skip, user_nodes=user_nodes):
		if idx not in recent:
			continue
		limit = _node_excerpt_chars(idx, params, recent=recent, override=None)
		excerpt = excerpt_preserving_needle(text, limit)
		if not excerpt:
			continue
		out.append((f"req:{idx}", f"#{idx} 用户: {excerpt} expand(node://{idx})"))
	return out


__all__ = [
	"HotBudgetAudit",
	"apply_hot_budgets",
	"render_requests",
	"rendered_request_nodes",
	"segment_tokens",
]