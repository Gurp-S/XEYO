"""Scenario matrix coverage and short-chat keep."""

from __future__ import annotations

from collections import Counter

from memory.simulator.decision import decide
from memory.simulator.params import load_params
from memory.simulator.report import run_synthetic
from memory.simulator.scenarios import LENGTH_TURNS, TOOL_SIZE_TOKENS, TTL_SECONDS, list_scenarios


def test_smoke_matrix_covers_dimensions():
	scs = list_scenarios(smoke=True)
	ids = [s.id for s in scs]
	assert "empty_m" in ids
	assert any(s.id.startswith("short:") for s in scs)
	kinds = {s.kind for s in scs}
	assert {"A", "B", "D", "F", "G"} <= kinds
	ttls = {s.ttl_key for s in scs}
	assert "T0" in ttls


def test_full_matrix_covers_s1_s6_t1_t5_ttl_and_huges():
	scs = list_scenarios(smoke=False)
	ls = {s.length_class for s in scs}
	ts = {s.tool_size_class for s in scs}
	assert set(LENGTH_TURNS) <= ls
	assert set(TOOL_SIZE_TOKENS) <= ts
	assert {s.ttl_key for s in scs} >= set(TTL_SECONDS)
	notes = {s.notes for s in scs}
	assert {"50k", "100k", "5x20k", "10x10k"} <= notes
	kinds = {s.kind for s in scs}
	assert set("ABCDEFGH") <= kinds


def test_short_chats_keep():
	p = load_params()
	for sc in list_scenarios(smoke=True):
		if not sc.id.startswith("short:"):
			continue
		d = decide(
			sc.state(),
			sc.cache(p),
			remaining_turns=sc.remaining_turns,
			params=p,
			delta_text=sc.delta_text,
			forecast="p0",
		)
		assert d.a_star == "keep", sc.id
		assert not d.hardtop


def test_empty_m_keep():
	sc = next(s for s in list_scenarios(smoke=True) if s.id == "empty_m")
	p = load_params()
	d = decide(sc.state(), sc.cache(p), remaining_turns=8, params=p, forecast="p0")
	assert d.a_star == "keep"


def test_mixed_text_c1_passes_quality_gate():
	from memory.simulator.quality_model import evaluate_quality
	from memory.simulator.state_model import apply

	sc = next(s for s in list_scenarios(smoke=True) if s.id == "mixed_c1")
	p = load_params()
	s0 = sc.state()
	q1 = evaluate_quality(apply("C1", s0, p), s0, p)
	assert q1.Q >= p.theta, q1.Q
	d = decide(s0, sc.cache(p), remaining_turns=16, params=p, forecast="p0")
	assert d.a_star in ("keep", "C1", "C2")


def test_endgame_keep():
	sc = next(s for s in list_scenarios(smoke=True) if s.id.endswith(":endgame") or s.remaining_turns == 1)
	p = load_params()
	# 若该收尾局仍放得进窗口，R=1 → keep
	from memory.simulator.projection import project

	s0 = sc.state()
	if project(s0).length <= p.l_max:
		d = decide(s0, sc.cache(p), remaining_turns=1, params=p, forecast="p0")
		assert d.a_star == "keep"


def test_smoke_suite_runs():
	rows = run_synthetic(smoke=True, forecast="p0")
	assert len(rows) >= 8
	c = Counter(r.a_star for r in rows)
	assert sum(c.values()) == len(rows)
	# 短对话不应全部 hardtop
	shorts = [r for r in rows if r.scenario_id.startswith("short:")]
	assert shorts and all(r.a_star == "keep" for r in shorts)


def test_oversized_tool_c0_prevents_l4():
	from memory.simulator.decision import decide
	from memory.simulator.projection import project

	p = load_params()
	for notes in ("50k", "100k"):
		sc = next(s for s in list_scenarios(smoke=False) if s.notes == notes)
		s0 = sc.state()
		L = project(s0).length
		d = decide(s0, sc.cache(p), remaining_turns=8, params=p, forecast="p0")
		assert L < p.l_max, (notes, L, p.l_max)
		assert d.a_star != "L4", notes
		assert not d.hardtop, notes
