"""Wave 1: C2 热路径 / WorkingSnapshot sidecar / pair-safe 切点。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from engine.compact import project
from memory.runtime import (
	c2_cut_index,
	pair_safe_cut,
	project_for_model,
)
from memory.working import WorkingSnapshot, flush, hydrate, path_for


def _assistant_use(uid: str, name: str) -> dict:
	return {
		"role": "assistant",
		"content": [
			{"type": "tool_use", "id": uid, "name": name, "input": {"q": "x"}},
		],
	}


def _tool_result(uid: str, content: str, *, role: str = "user") -> dict:
	row: dict = {
		"role": role,
		"content": [
			{
				"type": "tool_result",
				"tool_use_id": uid,
				"content": content,
				"is_error": False,
			}
		],
	}
	if role == "tool":
		row["tool_call_id"] = uid
		row["name"] = "Grep"
	return row


def _short_history() -> list[dict]:
	return [
		{"role": "user", "content": "hello"},
		{"role": "assistant", "content": "hi"},
	]


def test_short_dialog_equals_project_cursor_zero():
	working = WorkingSnapshot()
	msgs = _short_history()
	out = project_for_model(msgs, working)
	assert out == project(msgs)
	assert working.compact_cursor == 0


def test_empty_m_keep_equals_project(monkeypatch):
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	working = WorkingSnapshot()
	msgs = [{"role": "user", "content": "ping"}]
	out = project_for_model(msgs, working)
	assert out == project(msgs)
	assert working.compact_cursor == 0


def test_l5_project_never_advances(monkeypatch, mem_switch):
	mem_switch(XEYO_L5="project")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	working = WorkingSnapshot()
	history: list[dict] = [{"role": "user", "content": "start"}]
	for i in range(20):
		uid = f"g{i}"
		history.append(_assistant_use(uid, "Grep"))
		history.append(_tool_result(uid, "x" * 20_000))
	out = project_for_model(history, working, include_memory_index=False)
	assert out == project(history)
	assert working.compact_cursor == 0


def test_cooldown_blocks_non_hardtop_c2(monkeypatch, mem_switch):
	mem_switch(XEYO_L5="v61")
	fake = SimpleNamespace(a_star="C2", hardtop=False)
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake)
	working = WorkingSnapshot()
	working.turns_since_c2 = 2
	msgs = _short_history() + [
		_assistant_use("g0", "Grep"),
		_tool_result("g0", "body"),
	]
	out = project_for_model(msgs, working)
	assert out == project(msgs)
	assert working.compact_cursor == 0


def test_hardtop_advances_cursor_store_len_unchanged(monkeypatch, mem_switch):
	mem_switch(XEYO_L5="v61")
	# 本测试验证 decide/HardTop 的基础机制（非公式路径）；显式关掉 Path A 公式开关
	# （默认已启用），保持其原「冻结契约」断言成立。
	mem_switch(XEYO_C2_PRESSURE_FORMULA="0", XEYO_C2_GAIN_FORMULA="0", XEYO_C2_EXTEND_FORMULA="0")
	fake = SimpleNamespace(a_star="C2", hardtop=True)
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake)
	working = WorkingSnapshot()
	history: list[dict] = [{"role": "user", "content": "start"}]
	for i in range(12):
		uid = f"g{i}"
		history.append(_assistant_use(uid, "Grep"))
		history.append(_tool_result(uid, "x" * 8000, role="tool"))
	n = len(history)
	out = project_for_model(history, working)
	assert working.compact_cursor > 0
	assert len(history) == n
	assert out[0].get("name") == "session_summary"
	assert working.compact_cursor < n


def test_kv1_two_non_c2_rounds_same_prefix():
	working = WorkingSnapshot()
	msgs = _short_history()
	a = project_for_model(msgs, working)
	b = project_for_model(msgs, working)
	assert json.dumps(a, ensure_ascii=False) == json.dumps(b, ensure_ascii=False)
	assert working.compact_cursor == 0


def test_pair_safe_cut_does_not_split_tool_calls():
	msgs: list[dict] = [{"role": "user", "content": "q"}]
	for i in range(8):
		uid = f"t{i}"
		msgs.append(_assistant_use(uid, "Grep"))
		msgs.append(_tool_result(uid, "hit", role="tool"))
	# naive KEEP_TAIL=6 would land inside a pair for some lengths
	cut = c2_cut_index(msgs, None)
	if cut < len(msgs):
		# if we start on a tool row, the owning assistant must also be on the right
		if msgs[cut].get("role") == "tool":
			assert cut == 0 or not (
				msgs[cut - 1].get("role") == "assistant"
				and any(
					isinstance(b, dict) and b.get("type") == "tool_use"
					for b in (msgs[cut - 1].get("content") or [])
				)
			)
	safe = pair_safe_cut(msgs, len(msgs) - 5)
	if 0 < safe < len(msgs):
		prev = msgs[safe - 1]
		cur = msgs[safe]
		prev_uses = [
			b.get("id")
			for b in (prev.get("content") or [])
			if isinstance(b, dict) and b.get("type") == "tool_use"
		]
		if prev_uses and cur.get("role") == "tool":
			raise AssertionError("cut still splits assistant/tool pair")


def test_c2_projection_keeps_tool_pairs(monkeypatch, mem_switch):
	mem_switch(XEYO_L5="v61")
	fake = SimpleNamespace(a_star="C2", hardtop=True)
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake)
	working = WorkingSnapshot()
	history: list[dict] = [{"role": "user", "content": "start"}]
	for i in range(10):
		uid = f"g{i}"
		history.append(_assistant_use(uid, "Grep"))
		history.append(_tool_result(uid, "x" * 100, role="tool"))
	out = project_for_model(history, working)
	pending: set[str] = set()
	for msg in out:
		if msg.get("role") == "assistant":
			content = msg.get("content")
			if isinstance(content, list):
				for block in content:
					if isinstance(block, dict) and block.get("type") == "tool_use":
						pending.add(str(block.get("id")))
		got = []
		if msg.get("role") == "tool":
			got.append(str(msg.get("tool_call_id") or ""))
		content = msg.get("content")
		if isinstance(content, list):
			for block in content:
				if isinstance(block, dict) and block.get("type") == "tool_result":
					got.append(str(block.get("tool_use_id") or ""))
		for uid in got:
			pending.discard(uid)
	# leftover pending would mean a tool_use with no following result in the projection
	assert not pending


def test_hydrate_missing_and_bad_json(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	snap = hydrate("never-seen")
	assert snap.compact_cursor == 0
	path = path_for("broken")
	path.write_text("{not json", encoding="utf-8")
	snap2 = hydrate("broken")
	assert snap2.compact_cursor == 0
	assert snap2.session_id == "broken"


def test_flush_then_hydrate_keeps_cursor(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	snap = WorkingSnapshot(session_id="s1", compact_cursor=7, turns_since_c2=3)
	snap.todos = [
		{"content": "run tests", "status": "pending", "activeForm": "Running tests"}
	]
	flush("s1", snap)
	got = hydrate("s1")
	assert got.compact_cursor == 7
	assert got.turns_since_c2 == 3
	assert got.todos[0]["content"] == "run tests"


def test_c2_does_not_change_message_ids(monkeypatch, mem_switch):
	mem_switch(XEYO_L5="v61")
	fake = SimpleNamespace(a_star="C2", hardtop=True)
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake)
	working = WorkingSnapshot()
	history: list[dict] = [{"role": "user", "content": "start", "id": "u0"}]
	for i in range(10):
		uid = f"g{i}"
		history.append({**_assistant_use(uid, "Grep"), "id": f"a{i}"})
		history.append({**_tool_result(uid, "x" * 50, role="tool"), "id": f"t{i}"})
	ids_before = [m.get("id") for m in history]
	project_for_model(history, working)
	assert [m.get("id") for m in history] == ids_before


def _long_history(n_pairs: int = 12, size: int = 8000) -> list[dict]:
	history: list[dict] = [{"role": "user", "content": "start"}]
	for i in range(n_pairs):
		uid = f"g{i}"
		history.append(_assistant_use(uid, "Grep"))
		history.append(_tool_result(uid, "x" * size, role="tool"))
	return history


def test_c1_freezes_middle_and_records_boundary(monkeypatch, mem_switch):
	mem_switch(XEYO_L5="v61")
	mem_switch(XEYO_C2_PRESSURE_FORMULA="0", XEYO_C2_GAIN_FORMULA="0", XEYO_C2_EXTEND_FORMULA="0")
	from engine.compact import KEEP_TAIL_MESSAGES, _iter_tool_result_blocks

	fake = SimpleNamespace(
		a_star="C1",
		hardtop=False,
		branches={
			"keep": SimpleNamespace(x="KEEP_X"),
			"C1": SimpleNamespace(x="C1_X"),
			"C2": SimpleNamespace(x="C2_X"),
		},
	)
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake)
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	working = WorkingSnapshot()
	working.turns_since_c2 = 5
	history = _long_history(12)
	n = len(history)
	out = project_for_model(history, working)
	assert working.c1_frozen_until == n - KEEP_TAIL_MESSAGES
	assert working.turns_since_c2 == 0
	assert working.last_x_sim == "C1_X"
	kept = [
		block["content"]
		for msg in out
		for block in _iter_tool_result_blocks(msg)
	]
	assert kept[0].startswith("[compacted] Grep:")
	assert len(history) == n
	# 冻结边界不重复前进：再跑一次仍是 keep 语义，边界不变
	working.turns_since_c2 = 5
	fake2 = SimpleNamespace(
		a_star="keep",
		hardtop=False,
		branches={
			"keep": SimpleNamespace(x="K"),
			"C1": SimpleNamespace(x="C"),
			"C2": SimpleNamespace(x="C2"),
		},
	)
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake2)
	_ = project_for_model(history, working)
	assert working.c1_frozen_until == n - KEEP_TAIL_MESSAGES


def test_c1_cooldown_blocks_and_records_keep_x(monkeypatch, mem_switch):
	mem_switch(XEYO_L5="v61")
	fake = SimpleNamespace(
		a_star="C1",
		hardtop=False,
		branches={
			"keep": SimpleNamespace(x="KEEP_X"),
			"C1": SimpleNamespace(x="C1_X"),
		},
	)
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake)
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	working = WorkingSnapshot()
	working.turns_since_c2 = 2  # 未满 4 轮 → 当 keep
	history = _long_history(12)
	out = project_for_model(history, working)
	assert working.c1_frozen_until == 0
	assert working.last_x_sim == "KEEP_X"
	assert out[0]["content"].startswith("start")


def test_keep_records_last_x_sim_for_next_hit(monkeypatch, mem_switch):
	mem_switch(XEYO_L5="v61")
	fake = SimpleNamespace(
		a_star="keep",
		hardtop=False,
		branches={
			"keep": SimpleNamespace(x="PREV_X"),
			"C1": SimpleNamespace(x=""),
			"C2": SimpleNamespace(x=""),
		},
	)
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake)
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	working = WorkingSnapshot()
	msgs = _short_history()
	project_for_model(msgs, working)
	assert working.last_x_sim == "PREV_X"


def test_project_path_also_appends_memory_index(monkeypatch, mem_switch):
	"""默认 project 路径也要把 MEMORY 索引挂到 T_now（不再只限 v61）。"""
	mem_switch.reset("XEYO_L5")
	mem_switch(XEYO_C2_GATE="0")
	monkeypatch.setattr(
		"memory.memdir.load_index_text",
		lambda wsid: "[feedback] keep-me -> topics/x.md",
	)
	working = WorkingSnapshot()
	out = project_for_model([{"role": "user", "content": "hi"}], working)
	last = out[-1]
	assert last["role"] == "user"
	assert isinstance(last["content"], list)
	joined = "\n".join(str(b.get("text") or "") for b in last["content"])
	assert "Memory index" in joined
	# P0 一行化：只发计数摘要，条目标题/路径不进投影（防弱模型把索引当任务）
	assert "entries" in joined
	assert "keep-me" not in joined
	assert "topics/" not in joined


def test_memory_index_tail_goes_to_t_now_not_system(monkeypatch, mem_switch):
	mem_switch(XEYO_L5="v61")
	monkeypatch.setattr(
		"memory.memdir.load_index_text",
		lambda wsid: "# Memory index\n[feedback] 真库 -> topics/x.md\n",
	)
	fake = SimpleNamespace(
		a_star="keep",
		hardtop=False,
		branches={
			"keep": SimpleNamespace(x="K"),
			"C1": SimpleNamespace(x="C"),
			"C2": SimpleNamespace(x="C2"),
		},
	)
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake)
	working = WorkingSnapshot()
	msgs = [{"role": "user", "content": "hi"}]
	out = project_for_model(msgs, working)
	last = out[-1]
	assert last["role"] == "user"
	assert isinstance(last["content"], list)
	joined = "\n".join(str(b.get("text") or "") for b in last["content"])
	assert "Memory index" in joined
	# P0 一行化：条目标题不进投影
	assert "真库" not in joined
	assert "entries" in joined


def _big_msgs(n: int, size: int = 5000) -> list[dict]:
	return [{"role": "user", "content": "x" * size} for _ in range(n)]



def test_try_extend_c2_appends_keeps_old_prefix():
	"""机制：满足收益/稀发/摊薄时，扩展只追加、绝不重写旧摘要（KV 前缀命中）。"""
	from memory.runtime import try_extend_c2
	from memory.simulator.params import Params

	msgs = _big_msgs(10)
	w = WorkingSnapshot()
	w.compact_cursor = 5
	w.c2_summary_text = "FROZEN_SUMMARY"
	relaxed = Params(c2_extend_ratio=0.5, c2_extend_min_remaining_turns=2, c2_extend_safety_margin=1.0, c2_extend_price_ratio=3.0)
	ok = try_extend_c2(w, msgs, 8, relaxed, remaining_turns=10)
	assert ok
	# 旧摘要作为前缀字节不变（KV 缓存可命中），扩展只追加到尾部
	assert w.c2_summary_text.startswith("FROZEN_SUMMARY")
	assert "[C2+EXT]" in w.c2_summary_text
	assert w.compact_cursor == 8


def test_try_extend_c2_denied_when_region_too_small():
	from memory.runtime import try_extend_c2
	from memory.simulator.params import Params

	msgs = [{"role": "user", "content": "hi"} for _ in range(10)]
	w = WorkingSnapshot()
	w.compact_cursor = 5
	w.c2_summary_text = "S"
	relaxed = Params(c2_extend_ratio=0.5, c2_extend_min_remaining_turns=2, c2_extend_safety_margin=1.0, c2_extend_price_ratio=3.0)
	ok = try_extend_c2(w, msgs, 8, relaxed, remaining_turns=10)
	assert not ok
	assert w.compact_cursor == 5 and w.c2_summary_text == "S"


def test_try_extend_c2_denied_when_few_remaining_turns():
	from memory.runtime import try_extend_c2
	from memory.simulator.params import Params

	msgs = _big_msgs(10)
	w = WorkingSnapshot()
	w.compact_cursor = 5
	w.c2_summary_text = "FROZEN_SUMMARY"
	ok = try_extend_c2(w, msgs, 8, Params(), remaining_turns=2)
	assert not ok
	assert w.compact_cursor == 5 and w.c2_summary_text == "FROZEN_SUMMARY"


def test_c2_compact_state_never_rewrites_summary(monkeypatch, mem_switch):
	"""已压缩态下 decide 反复给 C2 也不得重写冻结摘要（append-only）。

	hardtop=False（非必要性）：扩展被收益闸拒绝时必须保持原摘要字节；必要性
	（hardtop=True）才允许强制扩展，见 test_hardtop_forces_extension_despite_gates。
	"""
	from memory.runtime import project_for_model

	mem_switch(XEYO_L5="v61")
	mem_switch(XEYO_C2_PRESSURE_FORMULA="0", XEYO_C2_GAIN_FORMULA="0", XEYO_C2_EXTEND_FORMULA="0")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	fake = SimpleNamespace(a_star="C2", hardtop=False, branches={
		"keep": SimpleNamespace(x="K"),
		"C1": SimpleNamespace(x="C"),
		"C2": SimpleNamespace(x="C2"),
	})
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake)
	w = WorkingSnapshot()
	w.turns_since_c2 = 5  # 冷却已过（否则 cooling 会挡住首次 C2）
	msgs = _big_msgs(14)
	project_for_model(msgs, w, remaining_turns=10)
	assert w.compact_cursor > 0 and w.c2_summary_text
	frozen = w.c2_summary_text
	# 继续追加消息，decide 仍报 C2（非必要）：扩展被收益门拒绝时应保持原摘要
	msgs2 = _big_msgs(15)
	project_for_model(msgs2, w, remaining_turns=10)
	assert w.c2_summary_text == frozen


def test_c2_compact_state_extension_appends(monkeypatch, mem_switch):
	"""已压缩态下新区足够大且剩余轮次多时才允许追加式扩展，旧前缀保留。"""
	from memory.runtime import project_for_model

	mem_switch(XEYO_L5="v61")
	mem_switch(XEYO_C2_PRESSURE_FORMULA="0", XEYO_C2_GAIN_FORMULA="0", XEYO_C2_EXTEND_FORMULA="0")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	fake = SimpleNamespace(a_star="C2", hardtop=True, branches={
		"keep": SimpleNamespace(x="K"),
		"C1": SimpleNamespace(x="C"),
		"C2": SimpleNamespace(x="C2"),
	})
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake)
	w = WorkingSnapshot()
	msgs = _big_msgs(14, 6000)
	project_for_model(msgs, w, remaining_turns=30)
	assert w.compact_cursor > 0 and w.c2_summary_text
	frozen = w.c2_summary_text
	# 会话翻倍到 40 条且剩余 30 轮 → 保守默认仍允许 append-only 扩展
	msgs2 = _big_msgs(40, 6000)
	project_for_model(msgs2, w, remaining_turns=30)
	assert w.c2_summary_text.startswith(frozen)
	assert "[C2+EXT]" in w.c2_summary_text
	assert w.compact_cursor > 14



def test_c2_decoupled_extension_fires_when_decide_keeps(monkeypatch, mem_switch):
	"""压缩态 + c2_extend_decouple=True：decide 返回 keep 也按 append 闸门扩展（θ 门不再卡死尾部）。"""
	from memory.runtime import project_for_model
	from memory.simulator.params import Params

	mem_switch(XEYO_L5="v61")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	monkeypatch.setattr(
		"memory.simulator.params.load_params",
		lambda: Params(
			c2_extend_decouple=True,
			c2_extend_ratio=0.5,
			c2_extend_min_remaining_turns=2,
			c2_extend_safety_margin=1.0,
			c2_extend_price_ratio=3.0,
		),
	)
	fake_keep = SimpleNamespace(a_star="keep", hardtop=False, branches={
		"keep": SimpleNamespace(x="K"),
		"C1": SimpleNamespace(x="C"),
		"C2": SimpleNamespace(x="C2"),
	})
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake_keep)
	w = WorkingSnapshot()
	w.compact_cursor = 8
	w.c2_summary_text = "FROZEN_SUMMARY"
	msgs = _big_msgs(24, 6000)
	project_for_model(msgs, w, remaining_turns=30)
	assert w.c2_summary_text.startswith("FROZEN_SUMMARY")
	assert "[C2+EXT]" in w.c2_summary_text
	assert w.compact_cursor > 8


def test_c2_decoupled_extension_off_by_default(monkeypatch, mem_switch):
	"""显式 c2_extend_decouple=False：decide 返回 keep 时不做扩展。"""
	from memory.runtime import project_for_model
	from memory.simulator.params import Params

	mem_switch(XEYO_L5="v61")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	monkeypatch.setattr(
		"memory.simulator.params.load_params",
		lambda: Params(c2_extend_decouple=False),
	)
	fake_keep = SimpleNamespace(a_star="keep", hardtop=False, branches={
		"keep": SimpleNamespace(x="K"),
		"C1": SimpleNamespace(x="C"),
		"C2": SimpleNamespace(x="C2"),
	})
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake_keep)
	w = WorkingSnapshot()
	w.compact_cursor = 8
	w.c2_summary_text = "FROZEN_SUMMARY"
	msgs = _big_msgs(24, 6000)
	project_for_model(msgs, w, remaining_turns=30)
	assert w.c2_summary_text == "FROZEN_SUMMARY"
	assert w.compact_cursor == 8

def test_c2_projection_prefix_stable_across_rounds(monkeypatch, mem_switch):
	"""已压缩态连续两轮：投影首段（摘要）字节级一致，KV 前缀可命中。"""
	import json as _json

	from memory.runtime import project_for_model

	mem_switch(XEYO_L5="v61")
	mem_switch(XEYO_C2_PRESSURE_FORMULA="0", XEYO_C2_GAIN_FORMULA="0", XEYO_C2_EXTEND_FORMULA="0")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	fake = SimpleNamespace(a_star="C2", hardtop=True, branches={
		"keep": SimpleNamespace(x="K"),
		"C1": SimpleNamespace(x="C"),
		"C2": SimpleNamespace(x="C2"),
	})
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake)
	w = WorkingSnapshot()
	msgs = _big_msgs(14)
	out1 = project_for_model(msgs, w, remaining_turns=10)
	assert w.compact_cursor > 0
	fake_keep = SimpleNamespace(a_star="keep", hardtop=False, branches={
		"keep": SimpleNamespace(x="K"),
		"C1": SimpleNamespace(x="C"),
		"C2": SimpleNamespace(x="C2"),
	})
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake_keep)
	msgs2 = _big_msgs(15)
	out2 = project_for_model(msgs2, w, remaining_turns=10)
	j1 = _json.dumps(out1, ensure_ascii=False, separators=(",", ":"))
	j2 = _json.dumps(out2, ensure_ascii=False, separators=(",", ":"))
	assert out1[0] == out2[0]
	assert j2.startswith(j1[:-1]) or out1[0] == out2[0]


def test_hardtop_forces_extension_despite_gates(monkeypatch, mem_switch):
	"""缺口①：压缩态 HardTop（必要性）绕过四闸门强制扩展——即使剩余轮次远低于
	c2_extend_min_remaining_turns 且收益不达标，也必须推进 cursor，防止窗口溢出。"""
	from memory.runtime import project_for_model

	mem_switch(XEYO_L5="v61")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	fake_hard = SimpleNamespace(
		a_star="C2",
		hardtop=True,
		branches={
			"keep": SimpleNamespace(x="K"),
			"C1": SimpleNamespace(x="C"),
			"C2": SimpleNamespace(x="C2"),
		},
	)
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake_hard)
	w = WorkingSnapshot()
	w.compact_cursor = 8
	w.c2_summary_text = "FROZEN_SUMMARY"
	w.turns_since_c2 = 5
	msgs = _big_msgs(30, 6000)
	# 剩余轮次=2 远低于默认 min_remaining=20 → 非 force 的 try_extend_c2 必然拒绝；
	# HardTop 强制扩展必须仍然执行
	out = project_for_model(msgs, w, remaining_turns=2)
	assert w.compact_cursor > 8
	assert w.c2_summary_text.startswith("FROZEN_SUMMARY")
	assert "[C2+EXT]" in w.c2_summary_text
	assert out[0].get("name") == "session_summary"


def test_hardtop_no_extension_when_no_region(monkeypatch, mem_switch):
	"""缺口①边界：HardTop 但无可前进切点（cursor 已到末端）→ 不崩溃、光标不动。"""
	from memory.runtime import project_for_model

	mem_switch(XEYO_L5="v61")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	fake_hard = SimpleNamespace(
		a_star="C2",
		hardtop=True,
		branches={
			"keep": SimpleNamespace(x="K"),
			"C1": SimpleNamespace(x="C"),
			"C2": SimpleNamespace(x="C2"),
		},
	)
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake_hard)
	w = WorkingSnapshot()
	w.compact_cursor = 10
	w.c2_summary_text = "FROZEN_SUMMARY"
	w.turns_since_c2 = 5
	msgs = _big_msgs(12, 6000)
	# len=12，c2_cut 取 len-KEEP_TAIL=6 < cursor=10 → new_cursor 无法前进 → 保持原样
	out = project_for_model(msgs, w, remaining_turns=2)
	assert w.compact_cursor == 10
	assert w.c2_summary_text == "FROZEN_SUMMARY"
	assert out[0].get("name") == "session_summary"


def test_remaining_capped_by_r_cap(monkeypatch, mem_switch):
	"""r_cap 接线：runtime 传给 decide 的 remaining_turns 按 params.r_cap 封顶。"""
	from memory.runtime import project_for_model
	from memory.simulator.params import Params

	mem_switch(XEYO_L5="v61")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	captured = {}
	fake = SimpleNamespace(
		a_star="keep",
		hardtop=False,
		branches={"keep": SimpleNamespace(x="K"), "C1": SimpleNamespace(x="C"), "C2": SimpleNamespace(x="C2")},
	)

	def spy_decide(s0, cache, **kw):
		captured["remaining"] = kw.get("remaining_turns")
		return fake

	monkeypatch.setattr("memory.simulator.decision.decide", spy_decide)
	monkeypatch.setattr("memory.simulator.params.load_params", lambda: Params(r_cap=4))
	w = WorkingSnapshot()
	w.turns_since_c2 = 5
	out = project_for_model(_short_history(), w, remaining_turns=99)
	assert captured["remaining"] == 4
	assert out == project(_short_history())


def test_c2_compressed_right_side_freezes_after_c1(monkeypatch, mem_switch):
	"""缺口②：压缩态 C1（原地冻结，不动 cursor）后，右段中间 tool_result 被占位、
	尾部原文保留——「压完即回血」被截断。"""
	from engine.compact import _iter_tool_result_blocks
	from memory.runtime import project_for_model

	mem_switch(XEYO_L5="v61")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	fake_c1 = SimpleNamespace(
		a_star="C1",
		hardtop=False,
		branches={
			"keep": SimpleNamespace(x="K"),
			"C1": SimpleNamespace(x="C1X"),
			"C2": SimpleNamespace(x="C2X"),
		},
	)
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake_c1)
	w = WorkingSnapshot()
	w.compact_cursor = 8
	w.c2_summary_text = "FROZEN_SUMMARY"
	w.turns_since_c2 = 5  # 冷却已过
	history = _long_history(12, 8000)
	out = project_for_model(history, w)
	assert out[0].get("name") == "session_summary"
	assert w.c1_frozen_until > 0
	content = [
		block["content"] for msg in out for block in _iter_tool_result_blocks(msg)
	]
	# 冻结边界之前：占位；之后（尾部）：原文
	assert any(isinstance(c, str) and c.startswith("[compacted]") for c in content)
	assert any(isinstance(c, str) and c.startswith("xxx") for c in content[-3:]) or any(
		isinstance(c, str) and len(c) > 100 for c in content[-3:]
	)
