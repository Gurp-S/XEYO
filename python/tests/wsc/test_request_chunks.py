"""``[REQUESTS]`` 区间句柄回归（P1-b）。

四条不许破的契约：

1. **无损**：``reqs://<首>-<末>`` 展开回的文本与图节点逐字节一致；
2. **一致**：行里写的区间 = 句柄绑定的节点集 = ``request_chunk_ids`` 的分块
   （渲染与绑定共用同一实现，任何一侧单独改动都会在这里变红）；
3. **可见**：审计认区间句柄，``req_rendered == req_total``，``user`` 针仍 1.0；
4. **省行**：紧凑形态的行数远少于逐节点形态（行数才是 [REQUESTS] 的真实开销）。

注意区间与节点集**不是**同一件事：块内下标在图上并不连续（中间夹着非用户节点），
所以「区间」只能断言 ``(idxs[0], idxs[-1])``，节点集必须来自 ``request_chunk_ids``。
"""

from __future__ import annotations

import re

from synaptic.budget import (
	render_requests,
	render_requests_compact,
	request_chunk_ids,
	rendered_request_nodes,
)
from synaptic.coldstore import parse_handle, parse_reqs_payload
from synaptic.filestate import build_file_states
from synaptic.graph import build_graph
from synaptic.metrics import needle_survival
from synaptic.project import default_params, project
from synaptic.seeds import collect_seeds, request_skip
from synaptic.types import WscParams
from wsc._fixtures import synth_session

_EXPAND = re.compile(r"expand\(([^)]+)\)")
H_REQUESTS = "[REQUESTS]"


def _long_session(turns: int = 24) -> list[dict]:
	"""每条用户消息文本互不相同：分块与区间句柄才有可判定的对应关系。"""
	return synth_session(turns=turns, user_every=1)


def _seeds(msgs: list[dict]):
	graph = build_graph(msgs)
	fs = build_file_states(graph, msgs)
	return collect_seeds(graph, msgs, fs)


def _chunks(msgs: list[dict], params: WscParams) -> list[tuple[int, int, tuple[int, ...]]]:
	graph = build_graph(msgs)
	seeds = _seeds(msgs)
	return request_chunk_ids(
		graph,
		len(msgs),
		params,
		skip=request_skip(seeds),
		user_nodes=seeds.user_nodes,
	)


def _requests_lines(hot: str) -> list[str]:
	return [ln for ln in hot.splitlines() if ln.startswith(H_REQUESTS)]


def _handles(hot: str) -> list[str]:
	out: list[str] = []
	for ln in _requests_lines(hot):
		out.extend(_EXPAND.findall(ln))
	return out


# ---------------------------------------------------------------------------
# 1. 渲染形态
# ---------------------------------------------------------------------------


def test_compact_render_merges_old_nodes_into_interval_handles():
	msgs = _long_session()
	p = default_params()
	seeds = _seeds(msgs)
	compact = render_requests_compact(
		build_graph(msgs),
		len(msgs),
		p,
		skip=request_skip(seeds),
		user_nodes=seeds.user_nodes,
	)
	assert compact, "长会话不应渲染出空的 [REQUESTS]"
	assert any("expand(reqs://" in line for _, line in compact), "旧用户节点没有被合并成区间句柄"
	for _, line in compact:
		for handle in _EXPAND.findall(line):
			assert parse_handle(handle)[0] in {"node", "reqs"}, handle


def test_compact_render_has_far_fewer_lines_than_per_node_render():
	"""行数才是 [REQUESTS] 的真实开销（每行 10–15 tok），必须真的降下来。"""
	msgs = _long_session()
	p = default_params()
	seeds = _seeds(msgs)
	graph = build_graph(msgs)
	kwargs = {"skip": request_skip(seeds), "user_nodes": seeds.user_nodes}
	per_node = render_requests(graph, len(msgs), p, **kwargs)
	compact = render_requests_compact(graph, len(msgs), p, **kwargs)
	assert len(per_node) > len(compact) * 2, (len(per_node), len(compact))
	# 最近 K 条仍逐字可见（不是"全压成句柄"）
	verbatim = [ln for _, ln in compact if "用户: " in ln]
	assert len(verbatim) == p.request_recent_verbatim


# ---------------------------------------------------------------------------
# 2. 区间一致性（渲染 ↔ 绑定不得漂移）
# ---------------------------------------------------------------------------


def test_interval_handle_matches_shared_chunk_ids():
	msgs = _long_session()
	p = default_params()
	seeds = _seeds(msgs)
	compact = render_requests_compact(
		build_graph(msgs),
		len(msgs),
		p,
		skip=request_skip(seeds),
		user_nodes=seeds.user_nodes,
	)
	chunks = {(first, last): idxs for first, last, idxs in _chunks(msgs, p)}
	spans = [
		parse_reqs_payload(parse_handle(h)[1])
		for _, line in compact
		for h in _EXPAND.findall(line)
		if h.startswith("reqs://")
	]
	assert spans, "没有区间句柄可校验"
	for span in spans:
		assert span is not None
		assert span in chunks, f"{span} 不在 request_chunk_ids 的分块里"
		idxs = chunks[span]
		assert span == (idxs[0], idxs[-1]), "区间首末与块内首末节点不一致"
		assert len(idxs) <= p.request_old_group_size
	assert len(spans) == len(chunks), "区间句柄数量与分块数量不一致"


def test_expand_interval_returns_exact_node_texts():
	msgs = _long_session()
	p = default_params()
	proj = project(msgs, region_end=len(msgs), params=p, session="reqs-roundtrip")
	chunks = {(first, last): idxs for first, last, idxs in _chunks(msgs, p)}
	handles = [h for h in _handles(proj.text) if h.startswith("reqs://")]
	assert handles, "project() 的 [REQUESTS] 里没有区间句柄"
	for handle in handles:
		payload = parse_handle(handle)[1]
		span = parse_reqs_payload(payload)
		assert span is not None and span in chunks, handle
		idxs = chunks[span]
		texts = proj.cold.expand(handle)
		assert len(texts) == len(idxs), (handle, len(texts), len(idxs))
		for idx, text in zip(idxs, texts):
			node = proj.graph.node(idx)
			assert node is not None, idx
			assert text == node.text, f"节点 {idx} 往返不无损"


# ---------------------------------------------------------------------------
# 3. 审计认区间 + user 针
# ---------------------------------------------------------------------------


def test_audit_counts_interval_handles_and_user_needle_is_full():
	msgs = _long_session()
	p = default_params()
	proj = project(msgs, region_end=len(msgs), params=p, session="reqs-audit")
	assert proj.state.req_total > 0
	assert proj.state.req_rendered == proj.state.req_total, (
		proj.state.req_rendered,
		proj.state.req_total,
	)
	lines = [(f"l{i}", ln) for i, ln in enumerate(_requests_lines(proj.text))]
	assert rendered_request_nodes(lines), "区间句柄没有被审计解析出来"
	needles = tuple(
		proj.graph.node(i).text
		for i in proj.seeds.user_nodes
		if proj.graph.node(i) is not None
	)
	surv = needle_survival(proj.text, {"user": needles})
	assert surv["user"]["rate"] == 1.0, surv["user"]


def test_user_nodes_stay_lossless_through_any_request_form():
	"""不管 [REQUESTS] 落在哪一档（区间 / 组句柄 / 仅句柄），每个用户节点都有出口。"""
	msgs = _long_session()
	p = default_params()
	proj = project(msgs, region_end=len(msgs), params=p, session="reqs-forms")
	for idx in proj.seeds.user_nodes:
		node = proj.graph.node(idx)
		if node is None or not node.text.strip():
			continue
		assert proj.cold.expand_loose(f"node://{idx}") == (node.text,)


# ---------------------------------------------------------------------------
# 4. for_level 显式透传（漏传会静默回落到默认值）
# ---------------------------------------------------------------------------


def test_for_level_passes_through_p1_params():
	custom = WscParams(
		request_recent_verbatim=7,
		request_excerpt_chars_old=120,
		request_old_group_size=3,
		path_index_limit=5,
		path_index_budget_tokens=64,
	)
	out = custom.for_level("Hard")
	assert out.request_recent_verbatim == 7
	assert out.request_excerpt_chars_old == 120
	assert out.request_old_group_size == 3
	assert out.path_index_limit == 5
	assert out.path_index_budget_tokens == 64
	# 反向自检：默认档不得被上例污染（for_level 是纯函数）
	assert WscParams().for_level("Medium+").request_old_group_size == 8
