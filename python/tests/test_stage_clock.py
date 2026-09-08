"""test_stage_clock — P0 阶段计时纯件单测。"""
from __future__ import annotations

import time

from engine.stage_clock import StageClock, to_summary_report


def test_stage_contextmanager_accumulates() -> None:
	c = StageClock()
	with c.stage("assemble"):
		time.sleep(0.01)
	with c.stage("assemble"):
		time.sleep(0.005)
	r = c.result()
	assert "assemble" in r
	assert r["assemble"] >= 13.0  # 两次累计 ≈15ms(留余量)
	assert len(r) == 1


def test_nested_stage_both_recorded() -> None:
	c = StageClock()
	with c.stage("outer"):
		time.sleep(0.05)
		with c.stage("inner"):
			time.sleep(0.03)
	r = c.result()
	assert set(r) == {"outer", "inner"}
	assert r["outer"] >= 45.0  # 外层含内层
	assert r["inner"] >= 20.0


def test_lap_and_external_add() -> None:
	c = StageClock()
	time.sleep(0.05)
	c.lap("first_byte")
	c.add("serialize", 3.0)
	r = c.result()
	assert r["first_byte"] >= 30.0
	assert r["serialize"] == 3.0


def test_finish_sink_called_once_with_result() -> None:
	got: list[dict[str, float]] = []
	c = StageClock(sink=got.append)
	with c.stage("a"):
		pass
	first = c.finish()
	second = c.finish()  # 幂等:不再回调
	assert len(got) == 1
	assert got[0] == first == second


def test_to_summary_report() -> None:
	c = StageClock()
	c.add("a", 1.0)
	text = to_summary_report(c.result())
	assert "a" in text and "TOTAL" in text
	assert to_summary_report({}) == "(no stages)"
