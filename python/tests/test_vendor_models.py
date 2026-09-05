from __future__ import annotations

from model.vendor_models import fetch_vendor_models, parse_vendor_models_payload


def test_parse_sorts_by_created_desc() -> None:
	payload = {
		"object": "list",
		"data": [
			{"id": "old", "owned_by": "x", "created": 10},
			{"id": "new", "owned_by": "x", "created": 99},
			{"id": "mid", "owned_by": "x", "created": 50},
		],
	}
	rows = parse_vendor_models_payload(payload, provider="openai")
	assert [r["id"] for r in rows] == ["new", "mid", "old"]


def test_deepseek_thinking_modes_attached() -> None:
	payload = {"data": [{"id": "deepseek-v4-flash", "owned_by": "deepseek"}]}
	rows = parse_vendor_models_payload(payload, provider="deepseek")
	assert rows[0]["modes"]["thinking"]
	assert rows[0]["modes"]["reasoning_effort"]


def test_passthrough_context_and_pricing() -> None:
	payload = {
		"data": [
			{
				"id": "m1",
				"context_length": 128000,
				"pricing": {"input": "1", "output": "2"},
			}
		]
	}
	rows = parse_vendor_models_payload(payload, provider="openai")
	assert rows[0]["context_length"] == 128000
	assert rows[0]["pricing"]["input"] == "1"


def test_pick_context_nested_shapes() -> None:
	payload = {
		"data": [
			{"id": "a", "max_sequence_length": 32768},
			{"id": "b", "top_provider": {"context_length": 65536}},
			{"id": "c", "metadata": {"context_window": 8192}},
			{"id": "d", "owned_by": "x"},
		]
	}
	rows = parse_vendor_models_payload(payload, provider="openai")
	by_id = {r["id"]: r["context_length"] for r in rows}
	assert by_id["a"] == 32768
	assert by_id["b"] == 65536
	assert by_id["c"] == 8192
	assert by_id["d"] is None


def test_fetch_missing_key() -> None:
	rep = fetch_vendor_models(api_key="", provider="deepseek", base_url="https://api.deepseek.com/v1")
	assert rep["vendor_ok"] is False
	assert rep["data"] == []
