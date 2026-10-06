"""热层双预算：固定段闸 + 主链闸。

旧实现只把 ``hot_budget_tokens`` 用在 ``kept`` 选择上；``[REQUESTS]``、``[WORKING SET]``
等固定段在预算外生长，长会话因此系统性超预算。这里把总预算拆成两个显式、可审计的闸：

* 固定段：PIN / WORKING SET / REQUESTS / NEXT；
* 主链：MAIN / DECISIONS / PRUNED（项目选择阶段另用 ``_CARD_RESERVE_SEED`` 预扣）。

固定段内部优先级固定为 ``PIN > WORKING SET > REQUESTS``。预算不足时只降级 REQUESTS：
先缩短内联摘录，再退化成合并句柄行；句柄也装不下时关闭该段，绝不主动突破硬上限。
冷层仍保留原文，因此截断不会破坏无损可恢复性。若受保护固定段自身已超固定预算，
审计单独记录不可避免的超额。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from synaptic.coldstore import node_handle, parse_reqs_payload, reqs_handle
from synaptic.fixed_budget import (
	trim_fixed_for_request_floor,
)
from synaptic.graph import Graph
from synaptic.handles import renderer_or_default
from synaptic.textutil import node_token_len
from synaptic.visible_paths import uncovered_path_lines
from synaptic.types import KIND_USER, WscParams

Line = tuple[str, str]

#: 一个块行内多条摘录的分隔符。选一个不会出现在正常用户原话里的可见分隔符：
#: 既不与内容歧义，也不影响「关键信息针按连续子串判定」（每条摘录各自连续）。
_EXCERPT_SEP = " ⏐ "

#: 固定段中不能为满足账面预算而静默省略的事实。PATHS / REQUESTS / NEXT 有各自的
#: 降级或关闭机制；PIN 与当前 working state 没有，故把两类超额分开审计。
_PROTECTED_FIXED_HEADERS = frozenset(
	{"[CONSTRAINTS]", "[UNRESOLVED]", "[TODO]", "[WORKING SET]"}
)

#: PIN 三段：**受保护事实**，不参与固定段配额竞争。
#:
#: 存在理由（实测）：原实现把它们算进固定段上限，于是「[UNRESOLVED] 变长」直接扣
#: [PATHS] 的额度——P0（错误签名升级）之后大会话的 [PATHS] 上限从 800 tok 掉到 172 tok，
#: `path_recent` 针 99.64% → 94.99%、`user` 针 99.57% → 97.93%。把 PIN 的实际占用从
#: 上限里扣除（等价于「PIN 不参与竞争」）后，[PATHS]/[REQUESTS] 恢复各自应有的额度；
#: PIN 自身超额仍由固定段审计单独记录（见本模块 ``HotBudgetAudit``）。
_PIN_HEADERS = frozenset({"[CONSTRAINTS]", "[UNRESOLVED]", "[TODO]"})
#: 索引桶里的两半**性质不同**，必须分开看：
#: ``[DECISIONS]`` 是信息（带错误签名的剪枝结论），``[PRUNED]`` 是可恢复性出口（句柄面）。
#: 要给它加上限，只可能对后者动（删前者=删信息，违反规则 1）；混成一桶就没法谈。
_DECISION_HEADERS = frozenset({"[DECISIONS]"})
_HANDLE_HEADERS = frozenset({"[PRUNED]"})


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


def rendered_request_nodes(
	items: list[Line] | tuple[Line, ...], *, handles: Any = None
) -> frozenset[int]:
	"""返回 ``[REQUESTS]`` 行中句柄实际覆盖的节点集合。

	``render_requests_grouped`` 会把这些节点合并为 ``node://i,j,...``；
	``render_requests_compact`` 会把旧节点合并成 ``reqs://<首>-<末>``。
	覆盖率审计若直接数行数，会变成「分母逐节点、分子逐行」的异源口径（踩过）。

	**解析收在 `handles.HandleRenderer.recoverable_nodes`**：渲染形态与解析必须同源，
	两处各写一份就会漂移——渲染换成 `Read` 形态而解析仍找 `expand(`，覆盖率会**静默归零**
	（审计报「用户原话全丢」而实际没丢）。本函数只负责把渲染器接进来。

	分页入口按显式完整 span 计恢复覆盖，首次实际正文覆盖另由 extract_nodes 计算。
	普通 Read 按实际跨度内完整正文计数；expand 使用已有精确绑定，缺绑定的旧式
	引用才按载荷解析。调用方与 ``request_nodes`` 求交，非用户节点不计入分子。
	"""
	hr = renderer_or_default(handles)
	out: set[int] = set()
	for _key, line in items:
		out.update(hr.recoverable_nodes(line))
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
	handles: Any = None,
) -> list[Line]:
	"""渲染逐节点 ``[REQUESTS]``；每个节点一条独立句柄。

	分层：最近 ``request_recent_verbatim`` 条用完整摘录，更早的用 ``request_excerpt_chars_old``。
	"""
	hr = renderer_or_default(handles)
	recent = _recent_verbatim_ids(user_nodes, params)
	out: list[Line] = []
	for idx, text in _request_nodes(
		graph, region_end, skip=skip, user_nodes=user_nodes
	):
		expr = hr.expression(node_handle(idx))
		if handle_only:
			line = f"#{idx} 用户 {expr}"
		else:
			limit = _node_excerpt_chars(idx, params, recent=recent, override=excerpt_chars)
			text = excerpt_preserving_needle(text, limit)
			if not text:
				continue
			line = f"#{idx} 用户: {text} {expr}"
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
	handles: Any = None,
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
	hr = renderer_or_default(handles)
	for key, idxs in groups.items():
		handle = "node://" + ",".join(str(i) for i in idxs)
		expr = hr.expression(handle)
		head = f"#{idxs[0]}"
		if len(idxs) > 1:
			head += f" 用户[{len(idxs)}]"
		else:
			head += " 用户"
		if handle_only:
			line = f"{head} {expr}"
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
			line = f"{head}: {text} {expr}"
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
	request_reserved_tokens: int
	fixed_overflow_tokens: int
	#: 受保护事实本身已超过固定预算；不是通过再裁 PATHS/REQUESTS 能解决的超额。
	fixed_unavoidable_overflow_tokens: int
	#: 可通过可降级固定段消除的超额。
	fixed_avoidable_overflow_tokens: int
	main_overflow_tokens: int
	#: 本轮固定段**没用完**、因而可让给主链的额度（``main_effective_cap`` 的浮动部分）。
	main_headroom_from_fixed_tokens: int = 0
	#: 主链的**生效**上限 = 声明值 + 上述浮动（声明值本身保持不动，便于跨轮对账）。
	main_effective_cap_tokens: int = 0
	#: 可恢复性索引（剪枝卡面）的独立额度与实际占用。
	index_budget_tokens: int = 0
	index_tokens: int = 0
	#: 高于观测线的量。**历史上就是纯观测**（一个字节都不裁），改名前它已被两侧口径
	#: 误读过一次：评测台几乎每枪"超"、生产一次不超（头不重建）——那量的是口径不是问题。
	index_overflow_tokens: int = 0
	#: 索引桶的两半分开计量（见 ``_DECISION_HEADERS`` / ``_HANDLE_HEADERS``）。
	#: 真正的事故信号不在这儿，而在报告的 ``recoverability.coverage < 1``：
	#: 有节点被剪却没有活句柄。
	decisions_tokens: int = 0
	handle_tokens: int = 0
	#: 送模型的真实总 tok = fixed + main + index。
	hot_total_tokens: int = 0

	def as_dict(self) -> dict[str, int | str]:
		return {
			"fixed_budget_tokens": self.fixed_budget_tokens,
			"main_budget_tokens": self.main_budget_tokens,
			"fixed_tokens": self.fixed_tokens,
			"main_tokens": self.main_tokens,
			"request_tokens": self.request_tokens,
			"request_mode": self.request_mode,
			"request_excerpt_chars": self.request_excerpt_chars,
			"request_reserved_tokens": self.request_reserved_tokens,
			"fixed_overflow_tokens": self.fixed_overflow_tokens,
			"fixed_unavoidable_overflow_tokens": self.fixed_unavoidable_overflow_tokens,
			"fixed_avoidable_overflow_tokens": self.fixed_avoidable_overflow_tokens,
			"main_overflow_tokens": self.main_overflow_tokens,
			"main_headroom_from_fixed_tokens": self.main_headroom_from_fixed_tokens,
			"main_effective_cap_tokens": self.main_effective_cap_tokens,
			"index_budget_tokens": self.index_budget_tokens,
			"index_tokens": self.index_tokens,
			"index_overflow_tokens": self.index_overflow_tokens,
			"decisions_tokens": self.decisions_tokens,
			"handle_tokens": self.handle_tokens,
			"hot_total_tokens": self.hot_total_tokens,
		}

	def describe(self) -> str:
		return (
			f"fixed {self.fixed_tokens}/{self.fixed_budget_tokens} tok, "
			f"main {self.main_tokens}/{self.main_effective_cap_tokens or self.main_budget_tokens} tok"
			# 生效上限里浮动来的那笔写进括号，避免读数的人以为主链配额被改大了。
			f"{'(含固定段让渡 ' + str(self.main_headroom_from_fixed_tokens) + ')' if self.main_headroom_from_fixed_tokens else ''}, "
			f"index {self.index_tokens} tok（内 决策卡 {self.decisions_tokens}"
			f" / 句柄面 {self.handle_tokens}；观测线 {self.index_budget_tokens}，不裁剪）, "
			f"total {self.hot_total_tokens} tok, "
			f"requests={self.request_mode}@{self.request_excerpt_chars}"
			+ (f", fixed_over={self.fixed_overflow_tokens}" if self.fixed_overflow_tokens else "")
			+ (f", main_over={self.main_overflow_tokens}" if self.main_overflow_tokens else "")
			+ (f", index_above_observation_line={self.index_overflow_tokens}"
			   if self.index_overflow_tokens else "")
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
	index_headers: tuple[str, ...] = (),
	handles: Any = None,
) -> tuple[dict[str, list[Line]], HotBudgetAudit]:
	"""对已渲染的 ``groups`` 应用固定段/主链预算并返回副本与审计。

	调用方负责先完成完整渲染；这里不会改 journal 里的旧行，只决定**本轮新增/重冻结**
	时应当发射哪一版文本。日志布局下旧行仍按 append-only 保留，重冻结时自动收敛到本次
	预算后的紧凑版本。
	"""
	out = {h: list(items) for h, items in groups.items()}
	# PIN 豁免：把 PIN 的实际占用加回上限 ⇒ 它们不再挤占 [PATHS]/[REQUESTS] 的额度。
	# 渲染侧（assemble._segment_groups 的 paths_budget）必须同口径，否则先渲染就被截了。
	pin_tokens = sum(segment_tokens(out.get(h, ())) for h in _PIN_HEADERS)
	exempt = pin_tokens
	fixed_cap = int(params.fixed_segment_budget_tokens) + exempt
	out, _request_floor = trim_fixed_for_request_floor(
		out,
		fixed_headers=fixed_headers,
		request_header=request_header,
		fixed_budget_tokens=fixed_cap,
		request_floor_tokens_=params.request_min_budget_tokens,
	)
	fixed_other = sum(
		segment_tokens(out.get(h, ())) for h in fixed_headers if h != request_header
	)
	request_available = max(0, fixed_cap - fixed_other)
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
			handles=handles,
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
					handles=handles,
				)
				if candidate and segment_tokens(candidate) <= request_available:
					chosen = candidate
					mode = "dedup_short"
					excerpt = cut
					break
		if chosen is None:
			# REQUESTS floor is a visibility floor, not a reason to discard every
			# old user needle.  Compact all user nodes to the 80-character needle
			# contract before falling back to handle-only rows.
			candidate = render_requests_compact(
				graph,
				region_end,
				params,
				skip=request_skip,
				user_nodes=user_nodes,
				excerpt_chars=80,
				handles=handles,
			)
			if candidate and segment_tokens(candidate) <= request_available:
				chosen = candidate
				mode = "compact_short"
				excerpt = 80

		if chosen is None:
			# 固定段是硬上限：文本针装不下时只保留可恢复句柄，
			# 句柄本身也装不下则关闭 REQUESTS；不再主动制造超预算段。
			chosen = render_requests_compact(
				graph,
				region_end,
				params,
				skip=request_skip,
				user_nodes=user_nodes,
				handle_only=True,
				handles=handles,
			)
			if chosen and segment_tokens(chosen) <= request_available:
				mode = "handles"
				excerpt = 0
			else:
				chosen = []
				mode = "dropped"
				excerpt = 0
		if chosen:
			out[request_header] = chosen
		else:
			out.pop(request_header, None)

	# Check the final surviving lines: earlier WS/REQUESTS text may be trimmed.
	if "[PATHS]" in out:
		visible = "\n".join(line for h, items in out.items() if h != "[PATHS]" for _, line in items)
		remaining = uncovered_path_lines(out["[PATHS]"], visible)
		if remaining:
			out["[PATHS]"] = remaining
		else:
			out.pop("[PATHS]")
	fixed_tokens = sum(segment_tokens(out.get(h, ())) for h in fixed_headers)
	# 请求行**在保留额度内**的部分与受保护事实同类：floor 已保证它不被裁
	# （见 ``trim_fixed_for_request_floor``），再把它计进"可消除超额"会让
	# 「avoidable>0」永远为真却无从消除——这是 09-21 挂账测试的真实底因。
	# 超出 floor 的部分仍算可消除（它确实要过降级梯）。
	request_in_floor = min(
		segment_tokens(out.get(request_header, ())), int(_request_floor)
	)
	protected_tokens = request_in_floor + sum(
		segment_tokens(out.get(h, ())) for h in fixed_headers if h in _PROTECTED_FIXED_HEADERS
	)
	fixed_overflow = max(0, fixed_tokens - int(params.fixed_segment_budget_tokens))
	fixed_unavoidable = max(0, protected_tokens - int(params.fixed_segment_budget_tokens))
	# **可恢复性索引（剪枝卡面）单列一桶**，不再算进主链超限。
	# 依据（实测两批语料 51 会话，末轮投影）：卡面 = ``[DECISIONS]``(带错误签名的卡)
	# + ``[PRUNED]``(其余卡)，两者都逐行走 ``handles.expression(...)`` ⇒ **卡片就是句柄
	# 的唯一出口**。它的规模 median 0 / p90 1189 / p95 1348 / max 2113 tok，p90 时占热层
	# **64%**，而它是「剪掉了多少」的函数，不是注意力稀缺性的旋钮 —— 拿 1200 的主链额度
	# 去装它，报出来的"主链超限"是记账错配；而真要压它只有一条路：删句柄，那等于削掉
	# 「被剪节点必可 expand 拉回」这条对外承诺。故此处只**分桶 + 报账**，一个字节都不删。
	index_tokens = sum(segment_tokens(out.get(h, ())) for h in index_headers)
	_index_set = frozenset(index_headers)
	main_tokens = sum(
		segment_tokens(out.get(h, ())) for h in main_headers if h not in _index_set
	)
	# **主链上限按固定段的实际未用量浮动**（不是再给主链一笔新预算）。
	# 静态 1800/1200 拆分的后果是实测 19/51 会话「主链超限」而固定段**一个都没超**
	# （0/51），且**总热层 50/51 都在 ``hot_budget_tokens`` 以内** ⇒ 那些超限是
	# 记账口径造成的假超支，不是真花超。按 (B) 的第一反应给主链装裁剪器会删掉
	# ``[DECISIONS]``（带错误签名的剪枝卡）与 ``[PRUNED]``（句柄索引）——那正是
	# WSC 招牌信息与可恢复性的载体，用假超限去换它属于自己削卖点。
	main_headroom = max(0, int(params.fixed_segment_budget_tokens) - fixed_tokens)
	main_cap = int(params.main_segment_budget_tokens) + main_headroom
	request_tokens = segment_tokens(out.get(request_header, ()))
	audit = HotBudgetAudit(
		fixed_budget_tokens=int(params.fixed_segment_budget_tokens),
		main_budget_tokens=int(params.main_segment_budget_tokens),
		fixed_tokens=fixed_tokens,
		main_tokens=main_tokens,
		request_tokens=request_tokens,
		request_mode=mode,
		request_excerpt_chars=excerpt,
		request_reserved_tokens=int(_request_floor),
		fixed_overflow_tokens=fixed_overflow,
		fixed_unavoidable_overflow_tokens=fixed_unavoidable,
		fixed_avoidable_overflow_tokens=max(0, fixed_overflow - fixed_unavoidable),
		main_overflow_tokens=max(0, main_tokens - main_cap),
		main_headroom_from_fixed_tokens=main_headroom,
		main_effective_cap_tokens=main_cap,
		index_budget_tokens=int(params.index_segment_budget_tokens),
		index_tokens=index_tokens,
		decisions_tokens=sum(segment_tokens(out.get(h, ())) for h in _DECISION_HEADERS),
		handle_tokens=sum(segment_tokens(out.get(h, ())) for h in _HANDLE_HEADERS),
		index_overflow_tokens=max(
			0, index_tokens - int(params.index_segment_budget_tokens)
		),
		#: 送模型的**真实总 tok**（三桶相加）。成本按这个算——分桶只是把"哪些额度属于
		#: 注意力内容、哪些属于可恢复性结构"说清楚，**不是**把超出的部分藏起来。
		hot_total_tokens=fixed_tokens + main_tokens + index_tokens,
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
	excerpt_chars: int | None = None,
	handle_only: bool = False,
	handles: Any = None,
) -> list[Line]:
	"""``[REQUESTS]`` 的紧凑形态（P1-b/P1-b′）：旧节点合并成区间句柄，行数封顶。

	行数是这段**唯一**的真实开销来源：每行约 10–15 token（``#<idx>`` + 头部 + ``expand(...)``），
	实测 93 行/回合 ≈ 1565 token。摘录字符数不是瓶颈——用户原话普遍短于上限时，
	320 与 80 两档输出逐字相同（见 docs §12.7 的负向结果与账目复核）。

	**P1-b′ 修正（必须记住的教训）**：P1-b 的第一版对旧块**只发句柄、不发摘录**，
	换来 +0.20pp 压缩率，却把 ``needle_survival.user`` 从 1.0000 打到 0.8320
	（segmented 臂 0.6560）——**「可恢复 ≠ 可见」**：原话能用 ``expand`` 逐字节拉回，
	但模型在热层文本里看不见它，关键信息针就没了。

	所以本形态改成：**一个块一行，块内每个节点的 80 字符摘录都内联在同一行里**，
	行尾挂一个区间句柄。行数仍降 ~``request_old_group_size`` 倍（省掉每行的
	``#<idx> 用户:`` 头部与 ``expand(...)`` 尾巴），而文本可见性与逐节点形态相同。

	发射顺序：**旧块（按 idx 升序）在前，最近 K 条在后**。理由与 ``[PATHS]`` 同一条：
	新内容一律追加在段尾，段内不因「某条原话翻进/翻出近期窗口」而整体重排。
	"""
	recent = _recent_verbatim_ids(user_nodes, params)
	hr = renderer_or_default(handles)
	old: dict[int, str] = {
		idx: text
		for idx, text in _request_nodes(graph, region_end, skip=skip, user_nodes=user_nodes)
		if idx not in recent
	}
	out: list[Line] = []
	for first, last, idxs in request_chunk_ids(
		graph, region_end, params, skip=skip, user_nodes=user_nodes
	):
		if handle_only:
			handle = node_handle(first) if len(idxs) == 1 else reqs_handle(first, last)
			head = f"#{first}" if len(idxs) == 1 else f"#{first}…{last} 用户[{len(idxs)}]"
			out.append((f"reqs:{first}", f"{head} {hr.expression(handle)}"))
			continue
		parts: list[str] = []
		for idx in idxs:
			limit = _node_excerpt_chars(idx, params, recent=recent, override=excerpt_chars)
			excerpt = excerpt_preserving_needle(old.get(idx, ""), limit)
			if excerpt:
				parts.append(excerpt)
		if not parts:
			# 块内一个可发射的摘录都没有（全是空白用户消息）：保留句柄行，
			# 否则这些节点在热层里就真的没有出口了。
			handle = node_handle(first) if len(idxs) == 1 else reqs_handle(first, last)
			head = f"#{first}" if len(idxs) == 1 else f"#{first}…{last} 用户[{len(idxs)}]"
			out.append((f"reqs:{first}", f"{head} {hr.expression(handle)}"))
			continue
		body = _EXCERPT_SEP.join(parts)
		if len(idxs) == 1:
			out.append(
				(
					f"req:{first}",
					f"#{first} 用户: {body} {hr.expression(node_handle(first))}",
				)
			)
			continue
		out.append(
			(
				f"reqs:{first}",
				f"#{first}…{last} 用户[{len(idxs)}]: {body} "
				f"{hr.expression(reqs_handle(first, last))}",
			)
		)
	for idx, text in _request_nodes(graph, region_end, skip=skip, user_nodes=user_nodes):
		if idx not in recent:
			continue
		if handle_only:
			out.append((f"req:{idx}", f"#{idx} 用户 {hr.expression(node_handle(idx))}"))
			continue
		limit = _node_excerpt_chars(idx, params, recent=recent, override=excerpt_chars)
		excerpt = excerpt_preserving_needle(text, limit)
		if not excerpt:
			continue
		out.append(
			(f"req:{idx}", f"#{idx} 用户: {excerpt} {hr.expression(node_handle(idx))}")
		)
	return out


__all__ = [
	"HotBudgetAudit",
	"apply_hot_budgets",
	"render_requests",
	"rendered_request_nodes",
	"segment_tokens",
]
