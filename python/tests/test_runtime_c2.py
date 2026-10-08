"""Runtime compaction contracts: model requests, declared capacity and generations.

Direct legacy economics helpers remain tested as helpers; they do not own
ordinary runtime scheduling. Old automatic C1/HardTop expectations were
migrated after the explicit model-owned timing decision (2026-10-08).
"""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest


from engine.compact import project
from memory.runtime import (
	c2_cut_index,
	pair_safe_cut,
	project_for_model,
)
from memory.working import WorkingSnapshot, flush, hydrate, path_for


@pytest.fixture(autouse=True)
def isolated_runtime_home(monkeypatch, tmp_path):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path))
	monkeypatch.setenv("XEYO_WSC", "0")
	monkeypatch.setenv("XEYO_CWD", str(tmp_path))


def assert_unfolded_receipts(emitted, original, start=0):
	"""Identity headers may change representation; result bodies remain exact."""
	from engine.compact import _iter_tool_result_blocks
	actual = {b["tool_use_id"]: b["content"] for row in emitted for b in _iter_tool_result_blocks(row)}
	for row in original[start:]:
		for block in _iter_tool_result_blocks(row):
			body = actual[block["tool_use_id"]]
			prefix = "执行回执身份=" + json.dumps({"call_id": block["tool_use_id"]}, separators=(",", ":")) + "\n"
			assert body == block["content"] or body == prefix + block["content"]


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
    history = _long_history(20, 20000)
    original = deepcopy(history)
    working = WorkingSnapshot()
    out = project_for_model(history, working, include_memory_index=False)
    assert working.compact_cursor == 0 and working.c1_frozen_until == 0
    assert_unfolded_receipts(out, history)
    assert history == original


def test_no_model_request_keeps_history_even_when_old_c2_policy_would_fold(monkeypatch):
    def obsolete(*args, **kwargs):
        raise AssertionError("old scheduling policy executed")
    monkeypatch.setattr("memory.simulator.decision.decide", obsolete)
    working = WorkingSnapshot(turns_since_c2=100)
    messages = _short_history() + [_assistant_use("g0", "Grep"), _tool_result("g0", "body")]
    out = project_for_model(messages, working, context_limit=1000000, include_memory_index=False)
    assert working.compact_cursor == 0
    assert_unfolded_receipts(out, messages)


def test_declared_capacity_forces_fold_without_mutating_source(monkeypatch):
    monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: pytest.fail("old HardTop invoked"))
    working = WorkingSnapshot(session_id="capacity-fold")
    history = _long_history(12, 8000)
    original = deepcopy(history)
    out = project_for_model(history, working, context_limit=10000, include_memory_index=False)
    assert 0 < working.compact_cursor < len(history)
    assert history == original
    assert out[0].get("name") == "session_summary"
    assert_unfolded_receipts(out, history, working.compact_cursor)


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
	# 朴素的 KEEP_TAIL=6 在某些长度会落进配对中间
	cut = c2_cut_index(msgs, None)
	if cut < len(msgs):
		# 若起点是 tool 行，所属 assistant 也必须在右侧
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


def test_c2_projection_keeps_tool_pairs(tmp_path):
	from memory.runtime import force_compact
	working = WorkingSnapshot()
	history: list[dict] = [{"role": "user", "content": "start"}]
	for i in range(10):
		uid = f"g{i}"
		history.append(_assistant_use(uid, "Grep"))
		history.append(_tool_result(uid, "x" * 100, role="tool"))
	out = force_compact(history, working, cwd=tmp_path)
	assert working.compact_cursor > 0
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
	# 残留 pending 意味着投影里出现没有后续结果的 tool_use
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


def test_c2_does_not_change_message_ids(tmp_path):
	from memory.runtime import force_compact
	working = WorkingSnapshot()
	history: list[dict] = [{"role": "user", "content": "start", "id": "u0"}]
	for i in range(10):
		uid = f"g{i}"
		history.append({**_assistant_use(uid, "Grep"), "id": f"a{i}"})
		history.append({**_tool_result(uid, "x" * 50, role="tool"), "id": f"t{i}"})
	ids_before = [m.get("id") for m in history]
	force_compact(history, working, cwd=tmp_path)
	assert working.compact_cursor > 0
	assert [m.get("id") for m in history] == ids_before


def _long_history(n_pairs: int = 12, size: int = 8000) -> list[dict]:
	history: list[dict] = [{"role": "user", "content": "start"}]
	for i in range(n_pairs):
		uid = f"g{i}"
		history.append(_assistant_use(uid, "Grep"))
		history.append(_tool_result(uid, "x" * size, role="tool"))
	return history


def test_old_c1_policy_cannot_freeze_unconsumed_history(monkeypatch):
    monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: pytest.fail("old C1 invoked"))
    history = _long_history(12)
    working = WorkingSnapshot(turns_since_c2=100)
    out = project_for_model(history, working, context_limit=1000000, include_memory_index=False)
    assert working.c1_frozen_until == 0 and working.compact_cursor == 0
    assert_unfolded_receipts(out, history)
    again = project_for_model(history, working, context_limit=1000000, include_memory_index=False)
    assert out == again


def test_keep_does_not_depend_on_old_c1_cooldown(monkeypatch):
    monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: pytest.fail("old C1 invoked"))
    history = _long_history(12)
    results = []
    for age in (0, 2, 100):
        working = WorkingSnapshot(turns_since_c2=age, last_x_sim="stored observation")
        results.append(project_for_model(history, working, context_limit=1000000, include_memory_index=False))
        assert working.compact_cursor == 0 and working.c1_frozen_until == 0
        assert working.last_x_sim == "stored observation"
    assert results[0] == results[1] == results[2]


def test_keep_does_not_run_cost_predictor_or_replace_its_stored_observation(monkeypatch):
    monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: pytest.fail("cost predictor invoked"))
    working = WorkingSnapshot(last_x_sim="prior observation")
    project_for_model(_short_history(), working, remaining_turns=999, include_memory_index=False)
    assert working.last_x_sim == "prior observation"
    assert working.compact_cursor == 0


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
	"""机制：满足收益/稀发/经济门时，扩展只追加、绝不重写旧摘要（KV 前缀命中）。"""
	from memory.runtime import try_extend_c2
	from memory.simulator.params import Params

	msgs = _big_msgs(10)
	w = WorkingSnapshot()
	w.compact_cursor = 5
	w.c2_summary_text = "FROZEN_SUMMARY"
	acct: dict = {}
	ok = try_extend_c2(w, msgs, 8, Params(c2_extend_ratio=0.5), account=acct)
	assert ok
	# 放行判据是经济门本身（净省 3,635 ≥ θ×重发面 2,615），不是被别的闸挡过后残留
	assert acct["reason"] == "worth_fold"
	assert acct["theta"] == 1.0
	assert acct["saved_net"] >= acct["transition"]
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
	acct: dict = {}
	ok = try_extend_c2(w, msgs, 8, Params(c2_extend_ratio=0.5), account=acct)
	assert not ok
	assert acct["reason"] == "gain_below_floor"
	assert w.compact_cursor == 5 and w.c2_summary_text == "S"


def _theta_denied_msg(count: int = 10):
	"""折一小段、留一长尾的形状：净省 < 重发面 ⇒ θ=1 必拒。"""
	return _big_msgs(count)


def test_extend_gate_denies_when_net_saving_below_resend_face():
	"""θ=1 的含义：本枪净省必须 ≥ 本枪重发面（不依赖未来任何一枪）。"""
	from memory.runtime import try_extend_c2
	from memory.simulator.params import Params

	msgs = _theta_denied_msg()
	w = WorkingSnapshot()
	w.compact_cursor = 5
	w.c2_summary_text = "FROZEN_SUMMARY"
	acct: dict = {}
	ok = try_extend_c2(w, msgs, 6, Params(c2_extend_ratio=0.02), account=acct)
	assert not ok
	assert acct["reason"] == "pays_back_too_slow"
	assert acct["saved_net"] < acct["theta"] * acct["transition"]
	assert w.compact_cursor == 5 and w.c2_summary_text == "FROZEN_SUMMARY"


def test_extend_gate_is_moved_only_by_theta(monkeypatch):
	"""同一形状：把 θ 调小就放行 ⇒ 挡它的是经济门，不是隐藏的尺寸闸（反证）。"""
	from memory.runtime import try_extend_c2
	from memory.simulator.params import Params

	monkeypatch.setenv("XEYO_C2_MARGIN", "0.1")
	msgs = _theta_denied_msg()
	w = WorkingSnapshot()
	w.compact_cursor = 5
	w.c2_summary_text = "FROZEN_SUMMARY"
	acct: dict = {}
	assert try_extend_c2(w, msgs, 6, Params(c2_extend_ratio=0.02), account=acct)
	assert acct["reason"] == "worth_fold"
	assert acct["theta"] == pytest.approx(0.1)


def test_extend_gate_carries_no_future_prediction():
	"""判据里不许再出现"还剩几轮"：函数签名与该 params 字段一起删掉了。"""
	import inspect

	from memory.runtime import try_extend_c2
	from memory.simulator.params import Params

	params = {p for p in inspect.signature(Params).parameters}
	assert not [p for p in params if "remaining" in p], params
	sig = str(inspect.signature(try_extend_c2))
	assert "remaining" not in sig, sig


def _fold_rows(path):
	import json as _json

	if not path.is_file():
		return []
	return [
		_json.loads(line)
		for line in path.read_text(encoding="utf-8").splitlines()
		if line.strip().startswith("{")
	]


def test_keep_assessment_is_ledgered_without_economics_scheduling(monkeypatch, tmp_path):
    import usage.ledger as ledger
    monkeypatch.setattr(ledger, "usage_dir", lambda: tmp_path)
    messages = _big_msgs(30, 6000)
    for native in (False, True):
        monkeypatch.setenv("XEYO_WSC", str(int(native)))
        monkeypatch.setenv("XEYO_C2_MARGIN", "0.01" if native else "1000")
        working = WorkingSnapshot(session_id="assessment-" + str(native))
        project_for_model(messages, working, context_limit=1000000, include_memory_index=False)
        assert working.compact_cursor == 0
    rows = _fold_rows(tmp_path / "fold_events.jsonl")
    assert len(rows) == 2
    assert [r["arm"] for r in rows] == ["c2", "wsc"]
    for row in rows:
        assert row["fold"] is False and row["forced"] is False
        assert row["timing_action"] == "keep" and row["input_tokens"] > 0


def test_offline_replay_does_not_write_the_production_fold_ledger(monkeypatch, tmp_path):
	"""离线重放台不传 account ⇒ 结构上写不出折叠账（防止把评测数据混进生产账本）。"""
	import usage.ledger as L
	from memory.runtime import c2_cut_index, try_extend_c2
	from memory.simulator.params import load_params

	monkeypatch.setattr(L, "usage_dir", lambda: tmp_path)
	w = WorkingSnapshot()
	w.compact_cursor = 8
	w.c2_summary_text = "FROZEN_SUMMARY"
	msgs = _big_msgs(30, 6000)
	assert try_extend_c2(w, msgs, c2_cut_index(msgs, None), load_params())
	assert _fold_rows(tmp_path / "fold_events.jsonl") == []


def test_compact_generation_remains_frozen_without_new_request(monkeypatch, tmp_path):
    from memory.runtime import force_compact
    monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: pytest.fail("old C2 invoked"))
    working = WorkingSnapshot(session_id="generation-keep")
    messages = _big_msgs(14)
    first = force_compact(messages, working, cwd=tmp_path)
    cursor, frozen = working.compact_cursor, working.c2_summary_text
    messages.append({"role": "user", "content": "continue"})
    following = project_for_model(messages, working, context_limit=1000000, include_memory_index=False, cwd=tmp_path)
    assert cursor > 0 and working.compact_cursor == cursor
    assert working.c2_summary_text == frozen and following[0] == first[0]


def test_new_explicit_fold_replaces_generation_and_preserves_archives(tmp_path):
    from memory.runtime import force_compact
    working = WorkingSnapshot(session_id="generation-replace")
    messages = _big_msgs(14, 6000)
    first = force_compact(messages, working, cwd=tmp_path)
    cursor = working.compact_cursor
    archived = {p: p.read_bytes() for p in tmp_path.rglob("*.txt")}
    assert archived
    messages.extend(_big_msgs(26, 6000))
    original = deepcopy(messages)
    second = force_compact(messages, working, cwd=tmp_path)
    assert working.compact_cursor > cursor
    assert second[0] != first[0]
    assert not second[0]["content"].startswith(first[0]["content"])
    assert messages == original
    assert all(p.read_bytes() == content for p, content in archived.items())



def test_old_decoupled_extension_flag_cannot_advance_cursor(monkeypatch):
    from memory.simulator.params import Params
    monkeypatch.setattr("memory.simulator.params.load_params", lambda: Params(c2_extend_decouple=True, c2_extend_ratio=0.5))
    monkeypatch.setenv("XEYO_C2_MARGIN", "0.01")
    working = WorkingSnapshot(compact_cursor=8, c2_summary_text="FROZEN_SUMMARY")
    project_for_model(_big_msgs(24, 6000), working, context_limit=1000000, include_memory_index=False)
    assert working.compact_cursor == 8 and working.c2_summary_text == "FROZEN_SUMMARY"


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

def test_c2_projection_prefix_stable_across_rounds(tmp_path):
    from memory.runtime import force_compact
    working = WorkingSnapshot(session_id="prefix")
    messages = _big_msgs(14)
    first = force_compact(messages, working, cwd=tmp_path)
    cursor = working.compact_cursor
    messages.append({"role": "user", "content": "next"})
    second = project_for_model(messages, working, context_limit=1000000, include_memory_index=False, cwd=tmp_path)
    assert cursor > 0 and working.compact_cursor == cursor
    assert second[0] == first[0]


def test_capacity_force_bypasses_old_economics_and_cooldown(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_C2_MARGIN", "1000")
    monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: pytest.fail("old HardTop invoked"))
    working = WorkingSnapshot(session_id="capacity-extension", compact_cursor=8, c2_summary_text="FROZEN_SUMMARY", c2_gap_shots=1000)
    messages = _big_msgs(30, 6000)
    original = deepcopy(messages)
    out = project_for_model(messages, working, context_limit=10000, include_memory_index=False, cwd=tmp_path)
    assert working.compact_cursor > 8
    assert not working.c2_summary_text.startswith("FROZEN_SUMMARY")
    assert out[0].get("name") == "session_summary"
    assert messages == original


def test_force_no_extension_when_no_eligible_region(tmp_path):
    """An explicit fold cannot move a cursor past the safe recent boundary."""
    from memory.runtime import force_compact
    working = WorkingSnapshot(session_id="no-region", compact_cursor=10, c2_summary_text="FROZEN_SUMMARY")
    messages = _big_msgs(12, 6000)
    original = deepcopy(messages)
    out = force_compact(messages, working, cwd=tmp_path)
    assert working.compact_cursor == 10
    assert working.c2_summary_text == "FROZEN_SUMMARY"
    assert out[0].get("name") == "session_summary"
    assert messages == original


def test_remaining_turns_cannot_schedule_or_change_projection(monkeypatch):
    monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: pytest.fail("remaining-turns predictor invoked"))
    messages = _long_history(12)
    outputs = []
    for remaining in (0, 1, 4, 99):
        working = WorkingSnapshot()
        outputs.append(project_for_model(messages, working, remaining_turns=remaining, context_limit=1000000, include_memory_index=False))
        assert working.compact_cursor == 0
    assert all(output == outputs[0] for output in outputs)


def test_existing_compact_generation_keeps_unfrozen_tool_results(monkeypatch):
    monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: pytest.fail("old C1 invoked"))
    working = WorkingSnapshot(compact_cursor=8, c2_summary_text="FROZEN_SUMMARY", c1_frozen_until=8)
    messages = _long_history(12, 8000)
    original = deepcopy(messages)
    out = project_for_model(messages, working, context_limit=1000000, include_memory_index=False)
    assert out[0]["content"] == "FROZEN_SUMMARY"
    assert working.compact_cursor == 8 and working.c1_frozen_until == 8
    assert_unfolded_receipts(out, messages, 8)
    assert messages == original


# ---------------------------------------------------------------------------
# 活路径折叠落地：把实测回本枪数写进 working，冷却闸读它（触发频率整改）
# ---------------------------------------------------------------------------

def test_fold_writes_payback_and_never_blocks_the_next(monkeypatch):
	"""折叠的成本真付了：落地写实测回本枪数，冷却闸按它拦；关掉 A1 = 历史"只记账"；force 不受阻。

	2026-09-30 起 A1（`XEYO_WSC_FOLD_COOLDOWN_VETO`）**默认开** ⇒ "不否决"只是
	回退开关那一侧的契约，两边都要钉。
	"""
	from memory.runtime import try_extend_c2
	from memory.simulator.params import Params
	from synaptic.cadence import MAX_GAP_SHOTS, MIN_GAP_SHOTS

	msgs = _big_msgs(10)
	params = Params(c2_extend_ratio=0.5)

	w = WorkingSnapshot()
	w.compact_cursor = 5
	w.c2_summary_text = "FROZEN_SUMMARY"
	acct: dict = {}
	assert try_extend_c2(w, msgs, 8, params, account=acct)
	gap = int(w.c2_gap_shots)
	assert gap >= MIN_GAP_SHOTS, "落地必须记下回本枪数（且不低于结构下限）"
	assert acct["gap_next"] == gap, "判定出口与落地写入必须是同一个数"

	# 默认态（A1 开）：冷却窗口内再折必须被拦 —— 这是新的默认语义
	monkeypatch.delenv("XEYO_WSC_FOLD_COOLDOWN_VETO", raising=False)
	w2 = WorkingSnapshot()
	w2.compact_cursor = 5
	w2.c2_summary_text = "FROZEN_SUMMARY"
	w2.c2_gap_shots = MIN_GAP_SHOTS + 3
	w2.turns_since_c2 = 1
	acct2: dict = {}
	assert try_extend_c2(w2, msgs, 8, params, account=acct2) is False, "默认态下冷却窗口内不该再折"
	assert acct2["reason"] == "cooldown_veto"
	assert w2.compact_cursor == 5, "否决不许动游标"

	# 回退开关（A1=0）：逐字回到"只记账、不否决"的历史行为
	monkeypatch.setenv("XEYO_WSC_FOLD_COOLDOWN_VETO", "0")
	w2b = WorkingSnapshot()
	w2b.compact_cursor = 5
	w2b.c2_summary_text = "FROZEN_SUMMARY"
	w2b.c2_gap_shots = MIN_GAP_SHOTS + 3
	w2b.turns_since_c2 = 1
	acct2b: dict = {}
	assert try_extend_c2(w2b, msgs, 8, params, account=acct2b), "关掉 A1 后冷却读数不得拦下一次划算的折叠"
	assert acct2b["gap_shots"] == MIN_GAP_SHOTS + 3, "判定当时的冷却读数仍要留账（落地后会被本次实测改写）"
	assert w2b.compact_cursor == 8
	monkeypatch.delenv("XEYO_WSC_FOLD_COOLDOWN_VETO", raising=False)

	# 折叠落地后冷却按**本次**实测重设（不是沿用旧值）
	w3 = WorkingSnapshot()
	w3.compact_cursor = 5
	w3.c2_summary_text = "FROZEN_SUMMARY"
	w3.c2_gap_shots = MIN_GAP_SHOTS + 3
	w3.turns_since_c2 = w3.c2_gap_shots + 1
	acct3: dict = {}
	assert try_extend_c2(w3, msgs, 8, params, account=acct3)
	assert w3.compact_cursor == 8
	assert acct3["gap_shots"] == MIN_GAP_SHOTS + 3, "账目要留下判定当时的冷却读数"
	assert w3.c2_gap_shots == acct3["gap_next"]
	assert MIN_GAP_SHOTS <= w3.c2_gap_shots <= MAX_GAP_SHOTS, "冷却夹在[结构下限, 结构上界]"

	# 冷却只由**本次**实测决定，不对历史取 max：把上一轮人为顶到结构上界，折叠结果必须一模一样
	w4 = WorkingSnapshot()
	w4.compact_cursor = 5
	w4.c2_summary_text = "FROZEN_SUMMARY"
	w4.c2_gap_shots = MAX_GAP_SHOTS
	w4.turns_since_c2 = MAX_GAP_SHOTS + 1
	acct4: dict = {}
	assert try_extend_c2(w4, msgs, 8, params, account=acct4)
	assert w4.c2_gap_shots == acct4["gap_next"] == w3.c2_gap_shots, "冷却不得累积（越折越久）"

	# force（窗口硬顶兜底）不受冷却限制，且不改动冷却账本
	w5 = WorkingSnapshot()
	w5.compact_cursor = 5
	w5.c2_summary_text = "FROZEN_SUMMARY"
	w5.c2_gap_shots = MIN_GAP_SHOTS + 9
	w5.turns_since_c2 = 1
	assert try_extend_c2(w5, msgs, 8, params, force=True)
	assert w5.compact_cursor == 8
	assert w5.c2_gap_shots == MIN_GAP_SHOTS + 9, "force 是必要性通道，不得改写冷却实测"
