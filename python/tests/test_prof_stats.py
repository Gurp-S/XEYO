"""test_prof_stats — P0 阶段耗时统计纯函数单测。"""
from __future__ import annotations

from engine.prof_stats import (
	format_table,
	group_records,
	percentile,
	summarize,
	summarize_grouped,
)


def test_percentile_nearest_rank() -> None:
	vals = [1.0, 2.0, 3.0, 4.0]
	assert percentile(vals, 50) == 2.0  # ceil(0.5*4)-1 = 1 → 2.0
	assert percentile(vals, 90) == 4.0  # ceil(0.9*4)-1 = 3
	assert percentile(vals, 100) == 4.0
	assert percentile(vals, 25) == 1.0  # ceil(0.25*4)-1 = 0
	assert percentile([], 50) == 0.0
	assert percentile([5.0], 99) == 5.0


def test_summarize_basic() -> None:
	s = summarize([1.0, 2.0, 3.0, 4.0])
	assert s["count"] == 4
	assert s["min"] == 1.0 and s["max"] == 4.0
	assert s["mean"] == 2.5
	assert s["p50"] == 2.0 and s["p99"] == 4.0
	empty = summarize([])
	assert empty["count"] == 0 and empty["p95"] == 0.0


def test_group_records_filters_bad_values() -> None:
	records = [
		{"stage": "assemble", "ms": 12.0},
		{"stage": "assemble", "ms": "bad"},
		{"stage": "first_byte", "ms": 8},
		{"stage": "", "ms": 3.0},  # 无 label 丢弃
	]
	g = group_records(records, label_key="stage", value_key="ms")
	assert g == {"assemble": [12.0], "first_byte": [8.0]}


def test_summarize_grouped_and_format_table() -> None:
	g = {"a": [10.0, 20.0], "b": [5.0]}
	rows = summarize_grouped(g)
	assert len(rows) == 2
	labels = [label for label, _ in rows]
	assert labels == ["a", "b"]
	text = format_table(rows)
	assert text.startswith("label")
	assert "a" in text and "p50" in text and "p99" in text
