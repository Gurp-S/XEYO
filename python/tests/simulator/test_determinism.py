"""1000× identical decisions + golden traces."""

from __future__ import annotations

import json
from pathlib import Path

from memory.simulator.decision import decide, decision_key
from memory.simulator.params import load_params
from memory.simulator.scenarios import list_scenarios

GOLDEN = Path(__file__).parent / "goldens" / "decision_traces.json"

_GOLDEN_IDS = ("empty_m", "short:1", "short:2", "short:3", "short:5")


def _run(sc, p, forecast="p0"):
	return decide(
		sc.state(),
		sc.cache(p),
		remaining_turns=sc.remaining_turns,
		params=p,
		delta_text=sc.delta_text,
		forecast=forecast,
	)


def test_determinism_1000x_p0():
	p = load_params()
	scs = [s for s in list_scenarios(smoke=True) if s.id in _GOLDEN_IDS]
	assert scs
	for sc in scs:
		first = decision_key(_run(sc, p, "p0"))
		for i in range(1000):
			got = decision_key(_run(sc, p, "p0"))
			assert got == first, f"{sc.id} run {i} {got} != {first}"


def test_determinism_p1_20x():
	p = load_params()
	sc = next(s for s in list_scenarios(smoke=True) if s.id == "empty_m")
	first = decision_key(_run(sc, p, "p1"))
	for i in range(20):
		assert decision_key(_run(sc, p, "p1")) == first, i


def _trace_dict(sc, p) -> dict:
	d = _run(sc, p, "p0")
	return {
		"id": sc.id,
		"a4": d.a4,
		"a8": d.a8,
		"a16": d.a16,
		"a_vote": d.a_vote,
		"a_hard": d.a_hard,
		"a_star": d.a_star,
		"hardtop": d.hardtop,
	}


def test_golden_decision_traces():
	p = load_params()
	by_id = {s.id: s for s in list_scenarios(smoke=True)}
	got = [_trace_dict(by_id[i], p) for i in _GOLDEN_IDS if i in by_id]
	GOLDEN.parent.mkdir(parents=True, exist_ok=True)
	if not GOLDEN.is_file():
		GOLDEN.write_text(json.dumps(got, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
	assert got == expected
