from __future__ import annotations

from usage.combine import compose_usage_report, report_has_usage

# v4 totals / series / models 行 schema：三分类 + hit_rate + 成功结算 requests，
# 无 cost / tokens（B1 红线）。


def _totals(
	*,
	requests: int,
	input_hit: int = 0,
	input_miss: int = 0,
	output: int = 0,
) -> dict:
	den = input_hit + input_miss
	return {
		"requests": requests,
		"input_hit": input_hit,
		"input_miss": input_miss,
		"output": output,
		"input_total": den,
		"hit_rate": round(input_hit / den * 100.0, 1) if den else None,
	}


def _empty(*, vendor_ok: bool, vendor_error: str = "") -> dict:
	return {
		"days": ["2026-08-17"],
		"totals": _totals(requests=0),
		"source": "vendor" if vendor_ok else "local",
		"vendor_ok": vendor_ok,
		"vendor_error": vendor_error,
		"series": [dict({"day": "2026-08-17"}, **_totals(requests=0))],
		"models": [],
		"keys": [],
	}


def _local_with_chat() -> dict:
	return {
		"days": ["2026-08-17"],
		"totals": _totals(requests=2, input_miss=30, output=10),
		"source": "local",
		"series": [dict({"day": "2026-08-17"}, **_totals(requests=2, input_miss=30, output=10))],
		"models": [
			{
				"provider": "deepseek",
				"vendor": "deepseek",
				"model": "deepseek-chat",
				**_totals(requests=2, input_miss=30, output=10),
				"series": [],
			}
		],
		"keys": ["…abcd"],
	}


def _vendor_flash() -> dict:
	return {
		"days": ["2026-08-17"],
		"totals": _totals(requests=9, input_hit=600, input_miss=200, output=100),
		"source": "vendor",
		"vendor_ok": True,
		"vendor_error": "",
		"series": [
			dict(
				{"day": "2026-08-17"},
				**_totals(requests=9, input_hit=600, input_miss=200, output=100),
			)
		],
		"models": [
			{
				"provider": "deepseek",
				"vendor": "deepseek",
				"model": "deepseek-v4-flash",
				**_totals(requests=9, input_hit=600, input_miss=200, output=100),
				"series": [],
			}
		],
		"keys": [],
	}


def test_report_has_usage() -> None:
	assert not report_has_usage(_empty(vendor_ok=True))
	assert report_has_usage(_local_with_chat())
	assert report_has_usage(_vendor_flash())


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
	"""厂商 ok 但零用量 → core 用本机（report_has_usage=False）。"""
	out = compose_usage_report(_empty(vendor_ok=True), _local_with_chat())
	assert out["source"] == "local"
	assert out["totals"]["requests"] == 2
	assert out["totals"]["input_total"] == 30
	assert out["totals"]["output"] == 10


def test_compose_vendor_is_authority() -> None:
	out = compose_usage_report(_vendor_flash(), _local_with_chat())
	assert out["source"] == "vendor"
	assert out["totals"]["requests"] == 9
	assert out["totals"]["input_hit"] == 600
	assert out["totals"]["hit_rate"] == 75.0
	assert out["models"][0]["model"] == "deepseek-v4-flash"
	assert "cost" not in out["totals"]
	assert "tokens" not in out["totals"]


def test_compose_vendor_totals_local_models() -> None:
	"""厂商有总量但缺模型拆分 → core 用厂商总量、models 行退回本机（source=vendor）。"""
	vendor = _empty(vendor_ok=True)
	vendor["totals"] = _totals(requests=9, input_miss=900)
	vendor["series"][0]["requests"] = 9
	vendor["series"][0]["input_miss"] = 900
	out = compose_usage_report(vendor, _local_with_chat())
	assert out["source"] == "vendor"  # totals 厂商权威
	assert out["totals"]["requests"] == 9
	assert out["totals"]["input_miss"] == 900
	assert out["models"][0]["model"] == "deepseek-chat"
