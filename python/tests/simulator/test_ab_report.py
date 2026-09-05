"""Baseline A/B gate: cost ↓ and success/correction not worse."""

from __future__ import annotations

from memory.simulator.report import ab_success, build_report, _ab_from_rows, SuiteRow


def _row(**kwargs) -> SuiteRow:
	base = dict(
		scenario_id="x",
		kind="A",
		length_class="S1",
		a_star="keep",
		a4="keep",
		a8="keep",
		a16="keep",
		hardtop=False,
		G_beta=0,
		L=100,
		Q=1.0,
		D=0.0,
		H=0.0,
		cost=1.0,
		baseline_tokens=120,
		v61_tokens=100,
		baseline_cost=1.2,
	)
	base.update(kwargs)
	return SuiteRow(**base)


def test_ab_pass_when_cheaper_same_success():
	rows = [_row(cost=0.8, baseline_cost=1.0, a_star="keep") for _ in range(5)]
	ab = _ab_from_rows(rows)
	gate = ab_success(ab)
	assert gate["passed"]


def test_ab_fail_when_success_drops():
	rows = [_row(cost=0.5, baseline_cost=1.0, a_star="L4") for _ in range(5)]
	ab = _ab_from_rows(rows)
	gate = ab_success(ab)
	assert not gate["passed"]
	assert "success_drop" in gate["reasons"]


def test_ab_fail_when_cost_not_down():
	rows = [_row(cost=1.5, baseline_cost=1.0) for _ in range(3)]
	ab = _ab_from_rows(rows)
	gate = ab_success(ab)
	assert not gate["passed"]
	assert "cost_not_down" in gate["reasons"]


def test_build_report_smoke_has_gate(tmp_path, monkeypatch):
	rep = build_report(smoke=True, include_replay=False, forecast="p0")
	assert "ab_gate" in rep
	assert "action_distribution" in rep
	assert "business" in rep
	assert "task_quality" in rep
	assert "user_correction" in rep
	assert "tool_loop" in rep
	assert rep["quality_invariants"]["D_negative"] == 0


def test_write_report(tmp_path):
	from memory.simulator.report import write_report

	rep = build_report(smoke=True, include_replay=False, forecast="p0")
	jp, mp = write_report(rep, tmp_path)
	assert jp.is_file() and mp.is_file()
	assert "P2 Calibration Report" in mp.read_text(encoding="utf-8")
	assert "keep" in jp.read_text(encoding="utf-8")
