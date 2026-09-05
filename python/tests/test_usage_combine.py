from __future__ import annotations

from usage.combine import compose_usage_report, report_has_usage


def _empty(*, vendor_ok: bool, vendor_error: str = "") -> dict:
	return {
		"days": ["2026-08-17"],
		"totals": {"cost": 0.0, "requests": 0, "tokens": 0},
		"lifetime_cost": 0.0,
		"cost_source": "vendor",
		"source": "vendor",
		"vendor_ok": vendor_ok,
		"vendor_error": vendor_error,
		"series": [
			{
				"day": "2026-08-17",
				"cost": 0.0,
				"requests": 0,
				"tokens": 0,
				"cache_hit": 0,
				"cache_miss": 0,
				"output": 0,
			}
		],
		"models": [],
		"keys": [],
	}


def _local_with_chat() -> dict:
	return {
		"days": ["2026-08-17"],
		"totals": {"cost": 0.01, "requests": 2, "tokens": 40},
		"lifetime_cost": 0.01,
		"cost_source": "estimate",
		"series": [
			{
				"day": "2026-08-17",
				"cost": 0.01,
				"requests": 2,
				"tokens": 40,
				"cache_hit": 0,
				"cache_miss": 30,
				"output": 10,
			}
		],
		"models": [
			{
				"provider": "deepseek",
				"model": "deepseek-chat",
				"requests": 2,
				"tokens": 40,
				"cost": 0.01,
				"series": [],
			}
		],
		"keys": ["…abcd"],
	}


def test_report_has_usage() -> None:
	assert not report_has_usage(_empty(vendor_ok=True))
	assert report_has_usage(_local_with_chat())


def test_compose_vendor_unavailable_uses_local() -> None:
	out = compose_usage_report(
		_empty(vendor_ok=False, vendor_error="invalid json"),
		_local_with_chat(),
	)
	assert out["source"] == "local"
	assert out["totals"]["requests"] == 2
	assert out["models"][0]["model"] == "deepseek-chat"
	assert out["vendor_ok"] is False
	assert out["keys"] == ["…abcd"]


def test_compose_vendor_empty_ok_uses_local() -> None:
	out = compose_usage_report(_empty(vendor_ok=True), _local_with_chat())
	assert out["source"] == "local"
	assert out["totals"]["tokens"] == 40


def test_compose_vendor_is_authority() -> None:
	vendor = _empty(vendor_ok=True)
	vendor["totals"] = {"cost": 1.5, "requests": 9, "tokens": 900}
	vendor["series"][0]["requests"] = 9
	vendor["series"][0]["tokens"] = 900
	vendor["series"][0]["cost"] = 1.5
	vendor["models"] = [
		{
			"provider": "deepseek",
			"model": "deepseek-v4-flash",
			"requests": 9,
			"tokens": 900,
			"cost": 1.5,
			"series": [],
		}
	]
	out = compose_usage_report(vendor, _local_with_chat())
	assert out["source"] == "vendor"
	assert out["totals"]["requests"] == 9
	assert out["models"][0]["model"] == "deepseek-v4-flash"


def test_compose_vendor_totals_local_models() -> None:
	vendor = _empty(vendor_ok=True)
	vendor["totals"] = {"cost": 1.5, "requests": 9, "tokens": 900}
	vendor["series"][0]["requests"] = 9
	out = compose_usage_report(vendor, _local_with_chat())
	assert out["source"] == "mixed"
	assert out["totals"]["requests"] == 9
	assert out["models"][0]["model"] == "deepseek-chat"
