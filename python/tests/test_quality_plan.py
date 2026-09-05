"""docs/12 质量验证计划书：单元测试（无 live）。

覆盖：默认关 + C2 单开开关、C2 摘要双风格、overlay r_summary、
题库 schema、判题确定性、θ* 选取规则、表D 行合并与 docs/12 渲染。
"""

from __future__ import annotations

import json

import pytest

from scripts import memory_stack_eval as M
from memory.l5_flag import DEFAULT_MODE, c2_gate, use_v61


def _assistant_use(uid: str, name: str) -> dict:
	return {
		"role": "assistant",
		"content": [{"type": "tool_use", "id": uid, "name": name, "input": {"q": "x"}}],
	}


def _tool_result(uid: str, content: str, *, role: str = "user") -> dict:
	row: dict = {
		"role": role,
		"content": [{"type": "tool_result", "tool_use_id": uid, "content": content, "is_error": False}],
	}
	if role == "tool":
		row["tool_call_id"] = uid
		row["name"] = "Grep"
	return row


def _long_history() -> list[dict]:
	msgs: list[dict] = [{"role": "user", "content": "start"}]
	for i in range(12):
		uid = f"g{i}"
		msgs.append(_assistant_use(uid, "Grep"))
		msgs.append(_tool_result(uid, "x" * 8000, role="tool"))
	return msgs


# ---------- l5_flag / runtime（运行时）----------

def test_l5_flag_default_project(monkeypatch, mem_switch):
	# 2026-09-06 用户决策：v61 默认开启（DEFAULT_MODE="v61"）；显式覆盖保证隔离
	mem_switch(XEYO_L5="v61")
	assert DEFAULT_MODE == "v61"
	assert use_v61()
	# 固化：C2_GATE 恒 True（v61 默认开启后不再作为开关）
	assert c2_gate()


def test_c2_gate_env(monkeypatch, mem_switch):
	# 固化：C2_GATE 恒 True（已删注册表键，env/settings 均不参与）
	assert c2_gate()
	mem_switch(XEYO_L5="project")
	assert c2_gate()  # project 回退也恒 True（Path A 公式裁决）


def test_project_gate_off_equals_compact_project(monkeypatch, mem_switch):
	from engine.compact import project as project_c0c1
	from memory.runtime import project_for_model
	from memory.working import WorkingSnapshot

	mem_switch.reset("XEYO_L5")
	mem_switch(XEYO_C2_GATE="0")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	w = WorkingSnapshot()
	out = project_for_model(_long_history(), w, include_memory_index=False)
	assert out == project_c0c1(_long_history())
	assert w.compact_cursor == 0


def test_project_gate_on_allows_c2(monkeypatch, mem_switch):
	from types import SimpleNamespace

	from engine.compact import project as project_c0c1
	from memory.runtime import project_for_model
	from memory.working import WorkingSnapshot

	# 2026-09-06 固化：C2_GATE / Path A 三公式已删（v61 默认开启后冗余）。
	# v61 下 decide 自主（公式不参与）——本测试验证「decide C2 → 压缩」路径。
	mem_switch(XEYO_L5="v61")
	monkeypatch.setattr("memory.memdir.load_index_text", lambda wsid: "")
	fake = SimpleNamespace(a_star="C2", hardtop=True)
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake)
	w = WorkingSnapshot()
	history = _long_history()
	out = project_for_model(history, w, include_memory_index=False)
	assert w.compact_cursor > 0
	assert out[0].get("name") == "session_summary"
	# project 模式：C0+C1 快路径（不跑 decide），产物等于 project_c0c1
	mem_switch(XEYO_L5="project")
	w2 = WorkingSnapshot()
	out2 = project_for_model(history, w2, include_memory_index=False)
	assert out2 == project_c0c1(history)
	assert w2.compact_cursor == 0


def test_v61_path_still_c2(monkeypatch, mem_switch):
	from types import SimpleNamespace

	from memory.runtime import project_for_model
	from memory.working import WorkingSnapshot

	mem_switch(XEYO_L5="v61")
	fake = SimpleNamespace(a_star="C2", hardtop=True)
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake)
	w = WorkingSnapshot()
	history = _long_history()
	out = project_for_model(history, w)
	assert w.compact_cursor > 0
	assert out[0].get("name") == "session_summary"


def test_c2_summary_legacy_vs_new():
	from memory.runtime import deterministic_c2_summary

	left = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi there"}]
	legacy = deterministic_c2_summary(left, style="legacy")
	new = deterministic_c2_summary(left, style="new")
	assert " :: " not in legacy
	assert " :: hi there" in new
	assert " :: hello" in new


def test_overlay_r_summary_override(tmp_path):
	from memory.simulator.params import Params, load_params, write_overlay

	assert Params().r_summary == 0.6  # 冻结默认不动
	ov = tmp_path / "ov.json"
	write_overlay({"r_summary": 0.4}, ov)
	assert load_params(ov).r_summary == 0.4  # overlay 可覆盖


# ---------- 题库 schema / 判题 ----------

def test_real_probe_bank_schema():
	probes = M.load_probes("real")
	qs = probes.get("questions", [])
	assert len(qs) >= 20, len(qs)
	ids = [q.get("id") for q in qs]
	assert len(ids) == len(set(ids)), "duplicate ids"
	layers = {q.get("layer") for q in qs}
	assert layers <= {"fact", "reasoning", "instruction"}
	for q in qs:
		assert q.get("q"), q
		assert q.get("expect_contains"), q
	assert probes.get("session_summary"), "session_summary 缺失"


def test_synthetic_probes_schema():
	probes = M.synthetic_probes()
	qs = probes.get("questions", [])
	assert len(qs) >= 12, len(qs)
	ids = [q.get("id") for q in qs]
	assert len(ids) == len(set(ids))
	layers = {q.get("layer") for q in qs}
	assert {"fact", "reasoning", "instruction"} <= layers
	assert probes.get("session_summary")


def test_judge_answer_deterministic():
	assert M.judge_answer({"expect_contains": ["b148fda"]}, "提交号是 B148FDA。")
	assert M.judge_answer({"expect_contains": ["7"]}, "共 7 类")
	assert not M.judge_answer({"expect_contains": ["7"]}, "七类")
	assert not M.judge_answer({"expect_contains": []}, "任意回答")


# ---------- θ* 选取规则 ----------

def _scan(theta, *, c2=1, avg_q=0.6, saves=0.1, cost=1.0) -> dict:
	return {"theta": theta, "c2_count": c2, "avg_q_c2": avg_q, "saves": saves, "total_cost": cost}


def test_pick_theta_star_min_cost_then_larger_theta():
	scans = [_scan(0.35, cost=2.0), _scan(0.40, cost=1.0), _scan(0.45, cost=1.0)]
	theta_star, accepted, feasible = M._pick_theta_star(scans)
	assert accepted
	assert theta_star == 0.45  # 成本并列时取较大 θ
	assert feasible == [0.35, 0.40, 0.45]


def test_pick_theta_star_empty_fallback():
	theta_star, accepted, feasible = M._pick_theta_star([_scan(0.35, c2=0)])
	assert not accepted
	assert theta_star == 0.50
	assert feasible == []


def test_pick_theta_star_low_quality_infeasible():
	theta_star, accepted, _ = M._pick_theta_star([_scan(0.35, avg_q=0.40, saves=0.2)])
	assert not accepted
	assert theta_star == 0.50


def test_pick_theta_star_no_savings_infeasible():
	theta_star, accepted, _ = M._pick_theta_star([_scan(0.35, saves=-0.1)])
	assert not accepted


# ---------- 表D 行合并 / 渲染 ----------

def test_upsert_keeps_previous_accepted(tmp_path, monkeypatch):
	monkeypatch.setattr(M, "QUALITY_JSON", tmp_path / "qv.json")
	M.upsert_quality_row("x1", source="表A", input_tokens=1, cache_hit=1, cache_miss=0, action="a", output="o", accepted=True)
	M.upsert_quality_row("x1", source="表A", input_tokens=2, cache_hit=2, cache_miss=0, action="a2", output="o2")
	row = M.load_quality_rows()["x1"]
	assert row["accepted"] is True
	assert row["input_tokens"] == 2  # 新数据覆盖，验收保留


def test_accept_row_merges_and_renders(tmp_path, monkeypatch):
	qv = tmp_path / "qv.json"
	monkeypatch.setattr(M, "QUALITY_JSON", qv)
	doc12 = tmp_path / "12.md"
	doc12.write_text("# 计划书\n<!-- 表D:begin -->\n占位\n<!-- 表D:end -->\n", encoding="utf-8")
	monkeypatch.setattr(M, "DOCS12", doc12)
	M.upsert_quality_row("ab_real_old_v61", source="表A", input_tokens=100, cache_hit=90, cache_miss=10, action="A/B", output="Δ=+1.0pp")
	assert M._accept_row_cli("ab_real_old_v61") == 0
	text = doc12.read_text(encoding="utf-8")
	assert "| 来源表 | 用例ID | 输入token数 | 命中数 | 未命中数 | 做了什么动作 | 结果产出 | 是否验收 |" in text
	assert "☑" in text and "`ab_real_old_v61`" in text
	assert "占位" not in text


def test_render_table_d_columns():
	rows = {
		"r1": {"case_id": "r1", "source": "表B", "input_tokens": 5, "cache_hit": 4, "cache_miss": 1, "action": "act", "output": "r=0.8", "accepted": False},
	}
	md = M.render_table_d(rows)
	assert "| 来源表 | 用例ID | 输入token数 | 命中数 | 未命中数 | 做了什么动作 | 结果产出 | 是否验收 |" in md
	assert "☐" in md


# ---------- A3 投影冻结断言 ----------

def test_freeze_synth_compressed():
	f = M._freeze_projections(M.long_history_api(20, 8000), source="synth")
	assert f["compressed"], f
	assert f["cursor"] > 0
	assert f["chars_v61"] < f["chars_project"]


def test_freeze_real_compressed_if_present():
	if not M.AB_REAL_SESSION.is_file():
		pytest.skip("无真实会话文件")
	api = M._real_session_api()
	assert len(api) > 0
	f = M._freeze_projections(api, source="real")
	assert f["compressed"], f
	assert f["cursor"] > 0


# ---------- A/B 统计 ----------

def test_ab_stats_layers():
	probes = {"questions": [
		{"id": "a", "layer": "fact", "q": "q", "expect_contains": ["x"]},
		{"id": "b", "layer": "fact", "q": "q", "expect_contains": ["x"]},
		{"id": "c", "layer": "instruction", "q": "q", "expect_contains": ["x"]},
	]}
	ab = {"real": {"old": {"v61": {"a": {"ok": 3, "n": 3}, "b": {"ok": 0, "n": 3}, "c": {"ok": 2, "n": 3}}}}}
	stats = M._ab_stats(ab, "real", "old", "v61", probes)
	assert stats["pass_rate"] == pytest.approx(2 / 3)
	assert stats["zero_three_fact"] == ["b"]


# ---------- C4 每日监控（ledger + c2 事件） ----------

def _write_ledger(tmp_path, *, day: str, events: list[dict], c2: int = 0) -> None:
	from usage.ledger import events_path, c2_events_path

	path = events_path()
	path.parent.mkdir(parents=True, exist_ok=True)
	lines = [json.dumps({**e, "day": day}, ensure_ascii=False) for e in events]
	path.write_text("\n".join(lines) + "\n", encoding="utf-8")
	c2p = c2_events_path()
	c2p.parent.mkdir(parents=True, exist_ok=True)
	c2p.write_text(
		"\n".join([json.dumps({"ts": 1, "day": day, "type": "c2", "session_id": "s", "cursor": 9})] * c2) + "\n",
		encoding="utf-8",
	)


def test_record_c2_event(monkeypatch, tmp_path):
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	from usage.ledger import read_c2_events, record_c2_event

	assert read_c2_events() == []
	record_c2_event(session_id="sess_x", cursor=42)
	evs = read_c2_events()
	assert len(evs) == 1
	assert evs[0]["type"] == "c2"
	assert evs[0]["session_id"] == "sess_x"
	assert evs[0]["cursor"] == 42


def test_monitor_daily_aggregates_and_writes_row(monkeypatch, tmp_path):
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	_write_ledger(
		tmp_path,
		day="2026-08-19",
		events=[
			{"provider": "deepseek", "model": "m", "prompt_tokens": 1000, "cache_hit": 900, "cache_miss": 100, "output": 50, "cost_cny": 0.01},
			{"provider": "deepseek", "model": "m", "prompt_tokens": 1000, "cache_hit": 900, "cache_miss": 100, "output": 50, "cost_cny": 0.01},
		],
		c2=1,
	)
	monkeypatch.setattr(M, "QUALITY_JSON", tmp_path / "quality_validation.json")
	monkeypatch.setattr(M, "DOCS12", tmp_path / "12.md")
	# A3（deploy_project_mode_*）行按 update_docs12_table_d 路由到 A3_MONITOR，
	# 而非 docs/12 表D（表D 只留 non_a3 行）。把 A3_MONITOR 也指到 tmp 以便断言。
	monkeypatch.setattr(M, "A3_MONITOR", tmp_path / "A3-monitor.md")
	monkeypatch.setattr(M, "A3_HTML", tmp_path / "A3-monitor.html")
	(tmp_path / "12.md").write_text("# t\n<!-- 表D:begin -->\nx\n<!-- 表D:end -->\n", encoding="utf-8")
	(tmp_path / "A3-monitor.md").write_text("# t\n<!-- A3:begin -->\nx\n<!-- A3:end -->\n", encoding="utf-8")
	rc = M._monitor_daily_cli("2026-08-19")
	assert rc == 0
	rows = M.load_quality_rows()
	row = rows["deploy_project_mode_2026-08-19"]
	assert row["source"] == "表C"
	assert row["input_tokens"] == 2000
	assert row["cache_hit"] == 1800
	assert row["cache_miss"] == 200
	assert row["detail"]["hit_rate"] == 0.9
	assert row["detail"]["c2_count"] == 1
	assert "命中率=90.00% (1800/2000)" in row["output"]
	# A3 行已落 QUALITY_JSON（权威存储 + load_quality_rows 可读）；A3_MONITOR 渲染当天摘要
	# （人类可读总表/分模型表，不含内部行 ID —— 行 ID 是 JSON key，不是渲染文本）。
	a3_doc = (tmp_path / "A3-monitor.md").read_text(encoding="utf-8")
	assert "2026-08-19" in a3_doc
	# 表D（12.md）只收 non_a3 行，不应凭空出现 A3 行 ID
	doc12 = (tmp_path / "12.md").read_text(encoding="utf-8")
	assert "deploy_project_mode_2026-08-19" not in doc12


def test_monitor_daily_auto_latest_day(monkeypatch, tmp_path):
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	_write_ledger(
		tmp_path,
		day="2026-08-18",
		events=[{"provider": "deepseek", "model": "m", "prompt_tokens": 500, "cache_hit": 250, "cache_miss": 250, "output": 10, "cost_cny": 0.001}],
	)
	_write_ledger(
		tmp_path,
		day="2026-08-19",
		events=[{"provider": "deepseek", "model": "m", "prompt_tokens": 800, "cache_hit": 760, "cache_miss": 40, "output": 20, "cost_cny": 0.002}],
	)
	monkeypatch.setattr(M, "QUALITY_JSON", tmp_path / "quality_validation.json")
	monkeypatch.setattr(M, "DOCS12", tmp_path / "12.md")
	(tmp_path / "12.md").write_text("# t\n<!-- 表D:begin -->\nx\n<!-- 表D:end -->\n", encoding="utf-8")
	rc = M._monitor_daily_cli("auto")
	assert rc == 0
	row = M.load_quality_rows()["deploy_project_mode_2026-08-19"]
	assert row["input_tokens"] == 800


def test_monitor_daily_empty_ledger(monkeypatch, tmp_path):
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	monkeypatch.setattr(M, "QUALITY_JSON", tmp_path / "quality_validation.json")
	assert M._monitor_daily_cli("2026-08-19") == 1


def test_runtime_c2_records_ledger_event(monkeypatch, tmp_path, mem_switch):
	from types import SimpleNamespace

	from memory.runtime import project_for_model
	from memory.working import WorkingSnapshot

	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	mem_switch(XEYO_L5="v61")
	# 隔离到「decide C2 → 记 ledger」机制；关掉 Path A 公式（默认启用），避免压力门拦截
	mem_switch(XEYO_C2_PRESSURE_FORMULA="0", XEYO_C2_GAIN_FORMULA="0", XEYO_C2_EXTEND_FORMULA="0")
	fake = SimpleNamespace(a_star="C2", hardtop=True)
	monkeypatch.setattr("memory.simulator.decision.decide", lambda *a, **k: fake)
	w = WorkingSnapshot(session_id="mon_sess")
	project_for_model(_long_history(), w)
	from usage.ledger import read_c2_events

	evs = read_c2_events()
	assert len(evs) == 1
	assert evs[0]["session_id"] == "mon_sess"
	assert evs[0]["cursor"] == w.compact_cursor


# ---------- 压缩态持久 + live 投影序列 ----------

def test_projection_sequence_project_matches_compact():
	from engine.compact import project as project_c0c1
	from memory.simulator.params import load_params
	from memory.simulator.replay import _user_turn_indices

	api = [
		{"role": "user", "content": "u0"},
		{"role": "assistant", "content": "a0"},
		{"role": "user", "content": "u1"},
		{"role": "assistant", "content": "a1"},
	]
	seq = list(M._projection_sequence(api, mode="project", sys_text="SYS", params=load_params()))
	starts = _user_turn_indices(api)
	assert len(seq) == len(starts)
	for (t, msgs, plen, _tr), start in zip(seq, starts):
		end = starts[t + 1] if t + 1 < len(starts) else len(api)
		assert msgs[0] == {"role": "system", "content": "SYS"}
		assert msgs[1:] == project_c0c1(api[:end])


def test_projection_sequence_c2_persists_compact():
	from memory.simulator.params import load_params

	if not M.AB_REAL_SESSION.is_file():
		pytest.skip("无真实会话文件")
	api = M._real_session_api()
	assert api
	params = load_params()
	seq = list(M._projection_sequence(api, mode="c2", sys_text="SYS", params=params))
	# 至少一次出现压缩态：首条为 session_summary
	compacted = [msgs for (_t, msgs, _p, _tr) in seq if msgs[1].get("name") == "session_summary"]
	assert compacted
	# 压缩态之间投影稳定：摘要文本只增不改（append-only 扩展合法，重写非法）
	texts = []
	for (_t, msgs, _p, _tr) in seq:
		if msgs[1].get("name") == "session_summary":
			texts.append(msgs[1].get("content"))
	# 冻结/追加语义：每个后续摘要都必须以某前驱为前缀（或相等），即旧文本不被重写。
	# 原先 "len(set(texts)) <= 2" 断言过时——try_extend_c2 追加式扩展会合法地多次变长。
	prefix_ok = True
	for i in range(1, len(texts)):
		if not any(texts[i].startswith(prev) for prev in texts[:i]):
			prefix_ok = False
			break
	assert prefix_ok, f"摘要被重写（非 append-only）: {len(texts)} 个不同文本"
	assert len(texts) >= 1


def test_projection_sequence_c2_eventually_smaller():
	from memory.simulator.params import load_params

	if not M.AB_REAL_SESSION.is_file():
		pytest.skip("无真实会话文件")
	api = M._real_session_api()
	params = load_params()
	pseq = list(M._projection_sequence(api, mode="project", sys_text="SYS", params=params))
	cseq = list(M._projection_sequence(api, mode="c2", sys_text="SYS", params=params))
	p_last = M._chars(pseq[-1][1][1:])
	c_last = M._chars(cseq[-1][1][1:])
	assert c_last < p_last
