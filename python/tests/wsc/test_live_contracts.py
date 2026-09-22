"""WSC 对模型侧的跨请求契约（不是单回合快照，而是"连续几枪之间不许发生什么"）。

已有的 `test_invariants.py` 只管单回合（压缩率、句柄绑定、层级有效性）。生产冒烟暴露的
两个缺陷都在**回合之间**：交界每枪前移打断缓存、收益门拒折时回退 C2 换掉整段头。
所以这里专门锁跨请求关系。
"""

from __future__ import annotations

import dataclasses
import re

import pytest

from tests.wsc._fixtures import msg_asst_text, msg_asst_use, msg_tool, synth_session

pytest.importorskip("synaptic")

HANDLE_RE = re.compile(r"(?:head|node|branch|reqs)://[^\s,|、）)]+")


class _W:
	def __init__(self, cursor: int, frozen: int = 0, sid: str = "s") -> None:
		self.session_id = sid
		self.compact_cursor = cursor
		self.c1_frozen_until = frozen


@pytest.fixture
def live(monkeypatch, tmp_path):
	import importlib

	WP = importlib.import_module("memory.wsc_projection")
	WP._STATE.clear()
	monkeypatch.setenv("XEYO_WSC", "1")
	monkeypatch.delenv("XEYO_WSC_FROZEN_HEAD", raising=False)
	monkeypatch.delenv("XEYO_WSC_CADENCE_ABSORB", raising=False)
	monkeypatch.setenv("XEYO_OFFLOAD_DIR", str(tmp_path))
	monkeypatch.setenv("XEYO_CWD", str(tmp_path))
	yield WP
	WP._STATE.clear()


def _body(out) -> str:
	return "\n".join(str(m.get("content") or "") for m in out)


def test_emitted_prompt_only_ever_appends(live) -> None:
	"""折叠事件之后，任意连续两枪必须满足：后一枪以"整份前一枪"为前缀。

	这是 KV 缓存能命中的**充要**条件；生产今晚破在它（交界每枪前移 ⇒ 旧头之后全重排）。
	"""
	WP = live
	from engine.compact import keep_tail_cut

	msgs = synth_session(turns=22, error_turn=4)
	cut = int(keep_tail_cut(msgs))
	first = WP.project_c2_messages(msgs, _W(cut), cwd=None)
	assert first is not None
	body1 = _body(first)
	grown = msgs + [
		msg_asst_use("t9", "Bash", {"command": "grep -rn pat src"}),
		msg_tool("t9", "Bash", "命中\n" + ("内容 " * 120)),
		msg_asst_text("小结 " * 60),
		msg_asst_use("t10", "Bash", {"command": "sed -n '1,80p' src/x.ts"}),
		msg_tool("t10", "Bash", "行内容\n" + ("代码 " * 130)),
	]
	second = WP.project_c2_messages(grown, _W(cut), cwd=None)
	assert second is not None
	assert _body(second).startswith(body1), (
		"未发生折叠事件却打断了发射前缀 ⇒ 厂商缓存从头之后整段失效"
	)


def test_unresolved_segment_only_holds_live_failures(live) -> None:
	"""`[UNRESOLVED]` 的每一行都必须对得上一个**未被判已解决**的失败签名。"""
	import importlib

	from synaptic.graph import build_graph
	from synaptic import freshness as fresh_mod

	fixture = synth_session(turns=18, error_turn=3)
	g = build_graph(fixture, include_soft_edges=False)
	proj_mod = importlib.import_module("synaptic.project")
	wp = importlib.import_module("memory.wsc_projection")
	p = proj_mod.project(fixture, region_end=len(fixture), params=wp.production_params(),
	                     session="s", region_baseline_tokens=10 ** 9)
	assert p.result.compressed
	resolved = set(fresh_mod.analyze(g, region_end=len(fixture)).resolved_idx) \
		if hasattr(fresh_mod, "analyze") else set()
	sigs = {n.error_sig for n in g.nodes
	        if n.is_error and n.error_sig and n.idx not in resolved}
	lines = [l for l in p.text.splitlines() if l.startswith("[UNRESOLVED]")]
	if not lines:
		pytest.skip("该合成会话没有未解决失败可渲染（换一个带 error 的夹具）")
	unclaimed = [l for l in lines if not any(s and s in l for s in sigs)]
	assert not unclaimed, (
		f"[UNRESOLVED] 里有 {len(unclaimed)} 行对不上任何未解决失败签名："
		f"{unclaimed[0][:90]!r}"
	)


def test_boundary_never_splits_a_tool_pair(live) -> None:
	"""交界只能落在成对边界上。把一次调用和它的结果拆到头/尾两侧，发给厂商的就是
	「孤儿 ``tool_result``」——生产那批 ``ProviderError 400`` 的形状。

	两边都钉：先证**朴素交界确实会被拆散**（否则这条是空转），再证活路径实际用的交界没拆。
	"""
	WP = live
	from engine.compact import keep_tail_cut
	from memory.runtime import _pair_ranges, pair_safe_cut

	msgs = synth_session(turns=26, error_turn=4)
	raw = int(keep_tail_cut(msgs))
	splittable = [(s, e) for (s, e) in _pair_ranges(msgs) if s + 1 > raw and s + 1 < e]
	assert splittable, "夹具里没有可拆散的调用批 ⇒ 本条失去看守对象"
	cursor = splittable[0][0] + 1                 # 游标故意落在调用与结果之间
	naive = min(len(msgs), max(raw, cursor))     # 修之前的交界公式
	assert any(s < naive < e for (s, e) in _pair_ranges(msgs)), (
		"朴素交界本身是安全的 ⇒ 夹具退化，这条测不到东西"
	)
	assert pair_safe_cut(msgs, naive) < naive

	assert WP.project_c2_messages(msgs, _W(cursor), cwd=None) is not None, "该尺寸应当真折叠"
	used = next(iter(WP._STATE.values())).region_end
	assert used <= naive
	split = [(s, e) for (s, e) in _pair_ranges(msgs) if s < used < e]
	assert not split, (
		f"活路径交界 {used} 落在调用批 {split[0]} 内部 ⇒ 尾部会出现孤儿 tool_result"
	)


def test_every_handle_in_head_is_parseable(live) -> None:
	"""生产档（``handle_style="read"``）头里的每个取回入口都必须是一次可执行的 Read。

	⚠️ 该档**不印** ``node://`` 这类字面量（第一版按 ``node://`` 找，得到 0 个句柄就
	以为契约失效——那是探针读错形态）。expand 形态的"被剪节点必有句柄"由
	``test_invariants.py``（``unbound == 0``）与回放台 ``recoverability``（逐字节 expand
	比对）从另一侧把关，这里不重复。
	"""
	import importlib
	import json

	wp = importlib.import_module("memory.wsc_projection")
	proj_mod = importlib.import_module("synaptic.project")
	fixture = synth_session(turns=26, error_turn=5)

	p = proj_mod.project(fixture, region_end=len(fixture), params=wp.production_params(),
	                     session="s", region_baseline_tokens=10 ** 9)
	calls = re.findall(r"Read\((\{.*?\})\)", p.text)
	assert calls, "读形态没产出任何 Read(...) 取回入口 ⇒ 渲染档变了，本契约失去看守对象"
	bad = []
	for c in calls:
		try:
			d = json.loads(c)
		except Exception:
			bad.append(c)
			continue
		if not d.get("path") or not isinstance(d.get("offset"), int) \
		   or not isinstance(d.get("limit"), int):
			bad.append(c)
	assert not bad, f"印出了不可执行的取回入口：{bad[:2]}"
