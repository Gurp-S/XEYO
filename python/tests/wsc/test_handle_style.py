"""句柄形态重排的验收契约：热层句柄 ``expand(node://N)`` → ``Read(file_path=…, offset=…, limit=…)``。

## 为什么必须单独立一组测试

句柄是**热层里唯一的信息出口**（剪枝不是删除，是降级成缺口 + 可展开句柄），而形态一改
会牵动**三件互相独立的事**，任何一件没跟上都不会立刻报错、只会静默降级：

| # | 契约 | 没跟上时的症状 |
|---|---|---|
| ① | 渲染出的 `Read` 引用**按 offset/limit 真能取回该节点原文** | 模型照抄引用 → 拿回错内容/报错（坏引用比没有引用更糟） |
| ② | `[REQUESTS]` 覆盖审计（分子分母同源）在 `read` 档下仍为 1.0 | 审计报「用户原话全丢」而实际没丢（**实测过：24 条用户消息只数进 1 条**） |
| ③ | 可恢复性 `lossless_rate` 仍为 1.0 | 剪枝内容真的丢了 |
| ④ | 缺区间时**回落** `expand`，绝不渲染坏引用 | 引用指向不存在的行区间 |

## 口径同源纪律（不自己另写）

- 取回**用真的 `FileReadTool`**（`offset` 1 起 / `limit` 行数），不自己切片 ⇒
  「测试里的切片」与「工具里的切片」不可能漂移；
- 「剥行号」与「LF 归一化」两个口径直接复用 `test_cold_read_view` 的实现 ⇒ 两处不会各写一份；
- 解析侧一律走 `handles.HandleRenderer`（生产同一实现），不在测试里另写正则去认引用。
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from synaptic.budget import rendered_request_nodes
from synaptic.coldstore import head_handle, node_handle
from synaptic.handles import HandleRenderer
from synaptic.metrics import recoverability
from synaptic.project import default_params, project
from tools.file_read_tool.file_read_tool import FileReadTool
from wsc._fixtures import synth_session

# 口径复用：剥 `cat -n` 前缀 / LF 归一化 / 经真实工具取回（唯一实现见 test_cold_read_view）
from wsc.test_cold_read_view import _lf, _read, _strip_line_numbers

H_REQUESTS = "[REQUESTS]"

#: 生产形态：``Read(file_path='…', offset=N, limit=K)``（与 `handles._READ_RE` 同形）。
_READ_CALL = re.compile(
	r"Read\(file_path='(?P<path>[^']*)'\s*,\s*offset=(?P<offset>\d+)\s*,\s*limit=(?P<limit>\d+)\)"
)


# ---------------------------------------------------------------------------
# 夹具：刻意用 Hard 档
# ---------------------------------------------------------------------------


def _session() -> list[dict]:
	"""24 轮 / 每轮一条后续用户消息：既产生真实剪枝，也产生 [REQUESTS] 区间句柄。"""
	return synth_session(turns=24, user_every=1)


def _refs(text: str) -> list[tuple[str, int, int]]:
	"""热层文本里模型能直接照抄的取回引用（**只解析文本本身**，不看内部状态）。"""
	return [
		(m.group("path"), int(m.group("offset")), int(m.group("limit")))
		for m in _READ_CALL.finditer(text)
	]


@pytest.fixture()
def hard_read(tmp_path):
	"""Hard 档 + `read` 形态 + 视图落在 offload 根下。

	**Hard 是刻意选的**：Medium+ 在这种会话上被剪节点为 0，句柄只出现在骨架行里，
	覆盖不到剪枝卡那条发射路径（实测：Hard → pruned=78 / cards=29；Medium+ → pruned=0）。
	"""
	view = tmp_path / ".xeyo_offload" / "wsc" / "cold.txt"
	msgs = _session()
	params = replace(default_params(level="Hard"), handle_style="read")
	proj = project(msgs, region_end=len(msgs), params=params, view_path=view)
	return proj, view, msgs


@pytest.fixture()
def hard_read_rel(tmp_path):
	"""同 `hard_read`，但引用渲染成**工作区相对路径**（生产形态：引用在每个句柄上重复）。

绝对路径的代价是实测的：同语料只换引用形态，热层 token median 3407，相对形态见
`memory/offload.py::ref_path_for` 的表与 docs §15.17。
	"""
	view = tmp_path / ".xeyo_offload" / "wsc" / "cold.txt"
	msgs = _session()
	params = replace(default_params(level="Hard"), handle_style="read")
	ref = view.relative_to(tmp_path).as_posix()
	proj = project(msgs, region_end=len(msgs), params=params, view_path=view, view_ref=ref)
	return proj, view, ref


def _renderer(proj, view: Path) -> HandleRenderer:
	"""按投影的冷层重建渲染器（区间表由同一份冷层重新导出，幂等）。

	测试不去偷 `project()` 的内部变量：区间表是**冷层的函数**，重建它才是「渲染 ↔ 取回」
	这条链路的真实校验（若重建结果与投影时不同，下面的逐字节比对就会红）。
	"""
	ranges = proj.cold.write_text_view(view)
	return HandleRenderer(
		style="read",
		path=str(view),
		node_ranges=ranges,
		handle_nodes=dict(proj.cold.handles),
	)


# ---------------------------------------------------------------------------
# ① 渲染形态：read 档下只出现 Read 引用，且都能取回
# ---------------------------------------------------------------------------


def test_read_style_hot_layer_exposes_read_refs_only(hard_read):
	proj, view, _msgs = hard_read
	assert proj.view_path == str(view), "投影没有记录取回视图路径"
	assert view.exists(), "取回视图没有落盘（模型拿不到可就地取回的路径）"
	assert proj.result.hot.pruned_nodes, "本用例必须真的发生剪枝，否则句柄只出现在骨架行里"
	refs = _refs(proj.text)
	assert refs, "热层没有渲染出任何取回引用"
	assert "expand(" not in proj.text, "read 档下仍渲染了 expand 形态（本用例所有句柄都有区间）"
	assert {p for p, _o, _l in refs} == {str(view)}, "引用指向的路径不是取回视图"


def test_read_refs_retrieve_the_node_text_they_stand_for(hard_read, tmp_path):
	"""逐字节取回：模型照抄引用 → 内容等于该节点原文（剥掉 `cat -n` 前缀后）。"""
	proj, view, _msgs = hard_read
	# 取回一律走**生产工具**（25k token / 2000 行闸门也在它里面，不能旁路掉）
	tool = FileReadTool(cwd=str(tmp_path))
	raw = view.read_text(encoding="utf-8").split("\n")

	# (a) 机械比对：每个引用取回的文本 == 视图对应行区间（含边界行）
	for _p, off, lim in _refs(proj.text):
		got = _strip_line_numbers(_read(tool, view, offset=off, limit=lim))
		assert got == "\n".join(raw[off - 1 : off - 1 + lim]), f"offset={off} limit={lim} 切片不等"

	# (b) 节点级：单节点句柄的引用必须正好是该节点原文（逐字节，剥前缀后）
	hr = _renderer(proj, view)
	checked = 0
	for handle in hr.extract(proj.text):
		nodes = proj.cold.handles.get(handle) or ()
		if len(nodes) != 1:
			continue  # 多节点句柄渲染成跨整组的区间（见 handles 模块文档），单节点才可逐字节判
		node = proj.graph.node(nodes[0])
		if node is None or _lf(node.text) == "":
			continue  # 空节点的已知限制：Read 把空切片当越界（docs §15.16.3(b)，别处已锁）
		expr = hr.expression(handle)
		assert expr in proj.text, f"句柄 {handle} 的表达式不在热层里：{expr}"
		off, lim = _refs(expr)[0][1:]
		assert _strip_line_numbers(_read(tool, view, offset=off, limit=lim)) == _lf(node.text), (
			f"{handle} 取回内容与原文不等"
		)
		checked += 1
	assert checked >= 3, f"逐字节比对的样本过少（{checked}）——断言空洞"


# ---------------------------------------------------------------------------
# ② [REQUESTS] 覆盖审计：分子分母同源（**本组最关键的一条**）
# ---------------------------------------------------------------------------


def test_requests_coverage_audit_survives_read_style(hard_read):
	"""渲染换了而解析没跟 ⇒ 覆盖率**静默归零**（审计报用户原话全丢，而实际没丢）。

	实测伪影：`read` 档下 24 条用户消息只数进 1 条（= `user_requests_rendered/total = 1/24`，
	唯一数进去的是那条作为 pin 渲染的用户节点）——原因就是审计的解析器只认 `expand(`。
	"""
	proj, view, _msgs = hard_read
	total = int(proj.result.user_requests_total)
	assert total > 1, f"分母太小，审计无意义（total={total}）"
	assert int(proj.result.user_requests_rendered) == total, (
		f"[REQUESTS] 覆盖率不是 1.0：{proj.result.user_requests_rendered}/{total}"
	)

	lines = [ln for ln in proj.text.splitlines() if ln.startswith(H_REQUESTS)]
	assert lines, "热层里没有 [REQUESTS] 段"
	items = [(f"l{i}", ln) for i, ln in enumerate(lines)]

	# 防回归探针（这条是**故意**不传渲染器）：同一批文本，旧解析器必然漏掉 Read 形态的句柄。
	# 若它哪天不再更少，说明热层里已经没有 Read 形态的句柄 —— 那本文件其余断言也就空了。
	blind = rendered_request_nodes(items)
	assert len(blind) < total, (
		f"旧（形态盲）解析器也认全了 {total} 条 —— 热层里没有 Read 形态的句柄，本用例失效"
	)

	# 同源解析（生产口径）认得出这些句柄：认全 `seeds.user_nodes`，只差**那个 pin 节点**
	# （首个用户节点渲染成 [CONSTRAINTS] 的「目标」，不占 [REQUESTS] 行；assemble 的审计
	# 同样把它单独补进分子 —— 这里按同一口径对齐，不然就是自己另造一个分母）。
	request_nodes, pin = _request_nodes(_msgs)
	assert len(request_nodes) == total, f"测试重建的分母与审计分母不同源：{len(request_nodes)} vs {total}"
	wired = rendered_request_nodes(items, handles=_renderer(proj, view))
	assert not (request_nodes - wired - {pin}), (
		f"[REQUESTS] 行里没有出口的用户节点：{sorted(request_nodes - wired - {pin})}"
	)


def _request_nodes(msgs: list[dict]) -> tuple[set[int], int | None]:
	"""重建 `assemble` 的审计分母：`seeds.user_nodes` 与首个 pin 节点。"""
	from synaptic.filestate import build_file_states
	from synaptic.graph import build_graph
	from synaptic.seeds import collect_seeds

	graph = build_graph(msgs)
	seeds = collect_seeds(graph, msgs, build_file_states(graph, msgs))
	nodes = {i for i in seeds.user_nodes if i < len(msgs)}
	pin = seeds.pin_nodes[0] if seeds.pin_nodes and seeds.pin_nodes[0] in nodes else None
	return nodes, pin


# ---------------------------------------------------------------------------
# ③ 可恢复性：剪枝内容仍无损可取回
# ---------------------------------------------------------------------------


def test_recoverability_still_lossless_under_read_style(hard_read):
	proj, view, _msgs = hard_read
	rec = recoverability(proj)
	assert rec["pruned"] > 0, f"没有被剪节点，可恢复性断言是空的：{rec}"
	assert rec["unbound"] == 0, f"有被剪节点没有句柄：{rec['unbound_idx']}"
	assert rec["checked"] > 0
	assert rec["lossless_rate"] == 1.0, f"句柄往返不再逐字节无损：{rec}"
	# 权威副本（gzip+JSON）不随渲染形态改变：取回视图只是它的可读投影
	for handle in list(proj.cold.handles)[:20]:
		proj.cold.expand(handle)  # 不抛 KeyError = 句柄在冷层里自洽


# ---------------------------------------------------------------------------
# ④ 回落：缺区间 / 缺路径 / expand 档
# ---------------------------------------------------------------------------


def test_missing_range_falls_back_to_expand():
	"""**坏引用比没有引用更糟**：缺任一成员区间就不渲染 `Read`，回落 `expand`。"""
	hr = HandleRenderer(
		style="read",
		path="v.txt",
		node_ranges={"node://7": (4, 6)},
		handle_nodes={"node://7": (7,), "reqs://7-9": (7, 8, 9), "branch://B1": (7, 8)},
	)
	assert hr.expression("node://7") == "Read(file_path='v.txt', offset=4, limit=3)"
	# 部分成员有区间也不行：只覆盖部分成员 = 静默的部分丢失，往返比对还看不出来
	assert hr.expression("reqs://7-9") == "expand(reqs://7-9)"
	assert hr.expression("branch://B1") == "expand(branch://B1)"
	assert hr.expression("node://999") == "expand(node://999)"
	# 没给路径 ⇒ 整档回落（配置错，不许渲染出取不回的引用）
	assert (
		HandleRenderer(style="read", node_ranges={"node://7": (4, 6)}).expression("node://7")
		== "expand(node://7)"
	)
	# expand 档（默认）与历史逐字节同形
	assert (
		HandleRenderer(style="expand", path="v.txt", node_ranges={"node://7": (4, 6)}).expression(
			"node://7"
		)
		== "expand(node://7)"
	)


def test_handle_renderer_caches_finalized_read_ranges():
	hr = HandleRenderer(
		style="read",
		path="v.txt",
		node_ranges={"node://7": (4, 6)},
		handle_nodes={"node://7": (7,)},
	)
	expr = "Read(file_path='v.txt', offset=4, limit=3)"
	assert hr.expression("node://7") == expr
	first = hr._reverse_index()
	assert hr.extract(expr) == ("node://7",)
	assert hr._reverse_index() is first


def test_read_style_without_view_path_degrades_to_expand(tmp_path):
	"""调用方给了 `read` 却没给视图路径 = 配置错 ⇒ 回落（绝不渲染取不回的引用）。"""
	msgs = _session()
	params = replace(default_params(level="Hard"), handle_style="read")
	proj = project(msgs, region_end=len(msgs), params=params, view_path=None)
	assert proj.view_path == ""
	assert "Read(file_path=" not in proj.text
	assert "expand(" in proj.text
	assert int(proj.result.user_requests_rendered) == int(proj.result.user_requests_total)


def test_expand_style_is_unchanged_by_view_path(tmp_path):
	"""默认档零行为变更：给了视图路径也不写、不渲染（历史口径逐字节保持）。"""
	msgs = _session()
	view = tmp_path / ".xeyo_offload" / "wsc" / "cold.txt"
	params = default_params(level="Hard")
	with_view = project(msgs, region_end=len(msgs), params=params, view_path=view)
	without = project(msgs, region_end=len(msgs), params=params)
	assert with_view.text == without.text
	assert with_view.view_path == ""
	assert not view.exists(), "expand 档不该写取回视图"
	assert "Read(file_path=" not in with_view.text
	assert with_view.text.count("expand(") > 0


# ---------------------------------------------------------------------------
# ⑤ 跨轮稳定性：头是 append-only 的，视图重排会让**老引用静默指向别的节点**
# ---------------------------------------------------------------------------


def _blocks(lines: list[str]) -> list[tuple[int, int, int]]:
	"""取回视图里的 ``#node idx`` 块：``(idx, 首行, 末行)``（1 起、含端点）。"""
	out: list[tuple[int, int, int]] = []
	cur: tuple[int, int] | None = None
	for i, ln in enumerate(lines, start=1):
		if ln.startswith("#node "):
			if cur is not None:
				out.append((cur[0], cur[1], i - 1))
			cur = (int(ln.split()[1]), i + 1)
	if cur is not None:
		out.append((cur[0], cur[1], len(lines)))
	return out


def _span_nodes(lines: list[str], off: int, lim: int) -> frozenset[int]:
	"""一个引用区间在**给定视图**里覆盖到的节点集合。"""
	end = off + lim - 1
	return frozenset(idx for idx, a, b in _blocks(lines) if a <= end and b >= off)


def _ref_nodes(lines: list[str], text: str) -> dict[str, frozenset[int]]:
	"""头里每个 `Read(…)` 引用 → 它**在该视图下**覆盖的节点集合。"""
	out: dict[str, frozenset[int]] = {}
	for m in _READ_CALL.finditer(text):
		out[m.group(0)] = _span_nodes(lines, int(m.group("offset")), int(m.group("limit")))
	return out


def _walk_turns(msgs: list[dict], view: Path, *, carry_cold: bool):
	"""逐轮投影（生产形态）：返回每轮的 (头文本, 该轮视图行)。

	`carry_cold=True` 时把冷层与 `AssemblyState` **一起**跨轮携带（接线要求）；
	`False` 模拟「只传状态、每轮新建冷层」——用于证明这条要求不是摆设。
	"""
	params = replace(default_params(level="Hard"), handle_style="read")
	prev = None
	cold = None
	out = []
	for t in range(12, len(msgs) + 1, 4):
		proj = project(
			msgs[:t], region_end=t, params=params, prev=prev, cold=cold, view_path=view
		)
		prev = proj.state
		if carry_cold:
			cold = proj.cold
		out.append((proj.text, view.read_text(encoding="utf-8").split("\n")))
	return out


def test_cross_turn_refs_keep_pointing_at_their_nodes(tmp_path):
	"""头里第 3 轮写的引用，到第 9 轮**必须还指向同一个节点**。

	为什么这条不能只靠单轮测试：头是 `assemble` 的 append-only 日志
	（只为前缀稳定才存在），老行一直在；而取回视图是**重写**的。
	两者一旦不同步，引用「自洽、能被解析、能取回内容」——只是**内容是别的节点**，
	单轮往返比对（本文件 ①②③）**一条都测不出来**。

	实测（`_wsc_out/_stale_ref_probe.py`，synth 40 轮）：不修时 1047 条引用样本里
	115 条含义漂移；修后 0 条。
	"""
	view = tmp_path / ".xeyo_offload" / "wsc" / "cold.txt"
	steps = _walk_turns(_session_long(), view, carry_cold=True)
	prev_map: dict[str, frozenset[int]] = {}
	carried = 0
	drift: list[str] = []
	for text, lines in steps:
		cur = _ref_nodes(lines, text)
		for ref, nodes in cur.items():
			old = prev_map.get(ref)
			if old is not None:
				carried += 1
				if old != nodes:
					drift.append(f"{ref} 旧={sorted(old)} 新={sorted(nodes)}")
		prev_map = cur
	assert not drift, "头保留了老行而视图已重排（跨轮坏引用）：\n" + "\n".join(drift[:5])
	# 防空断言：老引用必须**真的**被带到后面几轮（否则本用例什么都没验）
	assert carried >= 20, f"跨轮存活的老引用太少（{carried}）——断言空洞"
	assert len(prev_map) >= 20, f"最后一轮头里的引用太少（{len(prev_map)}）"


def test_without_cold_carry_the_same_refs_drift(tmp_path):
	"""接线要求的**另一半**：只传 `prev` 不够，冷层必须一起带。

	留着这条负向断言的理由：它把「为什么必须在接线点携带冷层」变成可执行的证据。
	若哪天视图结构上不再依赖携带（例如冷层落盘 + 真正 append-only），
	本测试会红 —— 那时**删掉它**并在接线说明里更新，而不是让要求悬空。
	"""
	view = tmp_path / ".xeyo_offload" / "wsc" / "cold.txt"
	steps = _walk_turns(_session_long(), view, carry_cold=False)
	prev_map: dict[str, frozenset[int]] = {}
	drift = 0
	for text, lines in steps:
		cur = _ref_nodes(lines, text)
		drift += sum(1 for ref, nodes in cur.items() if prev_map.get(ref, nodes) != nodes)
		prev_map = cur
	assert drift > 0, "未携带冷层时竟不漂移 —— 接线要求变了，见本测试 docstring"


def _session_long() -> list[dict]:
	"""40 轮：够长以走到「选择集变化（更小 idx 的新被剪节点插入）」那种工况。"""
	return synth_session(turns=40, user_every=1)


def test_logical_refreeze_keeps_old_head_snapshot_readable(tmp_path):
	"""逻辑换头只追加：旧头句柄仍能经生产 Read 取回原热层。"""
	msgs = _session()
	view = tmp_path / ".xeyo_offload" / "wsc" / "cold.txt"
	params = replace(default_params(level="Hard"), handle_style="read", journal_growth_tokens=1)
	mid = len(msgs) // 2
	p1 = project(msgs[:mid], region_end=mid, params=params, view_path=view)
	p2 = project(
		msgs,
		region_end=len(msgs),
		params=params,
		prev=p1.state,
		cold=p1.cold,
		view_path=view,
	)
	assert p2.result.journal_refroze is True
	assert p2.result.rebuilt is False
	assert p2.text.startswith(p1.text)
	handle = head_handle(p1.text)
	assert p2.cold.expand(handle) == (p1.text,)
	ranges = p2.cold.write_text_view(view)
	hr = HandleRenderer(style="read", path=str(view), node_ranges=ranges)
	expr = hr.expression(handle)
	assert expr in p2.text
	_off, _lim = _refs(expr)[0][1:]
	got = _strip_line_numbers(
		_read(FileReadTool(cwd=str(tmp_path)), view, offset=_off, limit=_lim)
	)
	assert got == _lf(p1.text)
