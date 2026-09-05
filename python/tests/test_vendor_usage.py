from __future__ import annotations

from datetime import date

from usage.vendor import (
	_merge_report,
	fetch_vendor_usage,
	parse_platform_amount,
	parse_platform_cost,
)


SAMPLE_AMOUNT = {
	"code": 0,
	"data": {
		"biz_code": 0,
		"biz_data": {
			"days": [
				{
					"date": "2026-08-17",
					"data": [
						{
							"model": "deepseek-v4-flash",
							"usage": [
								{"type": "PROMPT_CACHE_HIT_TOKEN", "amount": "100"},
								{"type": "PROMPT_CACHE_MISS_TOKEN", "amount": "200"},
								{"type": "RESPONSE_TOKEN", "amount": "50"},
								{"type": "REQUEST", "amount": "1"},
							],
						}
					],
				}
			]
		},
	},
}

SAMPLE_COST = {
	"code": 0,
	"data": {
		"biz_code": 0,
		"biz_data": [
			{
				"days": [
					{
						"date": "2026-08-17",
						"data": [
							{
								"model": "deepseek-v4-flash",
								"usage": [{"type": "TOTAL", "amount": "0.0274"}],
							}
						],
					}
				]
			}
		],
	},
}


def test_parse_platform_amount_tokens() -> None:
	rows = parse_platform_amount(SAMPLE_AMOUNT)
	assert len(rows) == 1
	b = rows[0]["bucket"]
	assert rows[0]["model"] == "deepseek-v4-flash"
	assert b["cache_hit"] == 100
	assert b["cache_miss"] == 200
	assert b["output"] == 50
	assert b["tokens"] == 350
	assert b["requests"] == 1


def test_parse_platform_auth_failed() -> None:
	try:
		parse_platform_amount({"code": 40003, "msg": "Authorization Failed"})
	except RuntimeError as e:
		assert "Authorization" in str(e)
	else:
		raise AssertionError("expected auth failure")


def test_merge_vendor_cost() -> None:
	amount = parse_platform_amount(SAMPLE_AMOUNT)
	cost = parse_platform_cost(SAMPLE_COST)
	rep = _merge_report(
		days=1,
		provider="deepseek",
		amount_rows=amount,
		cost_rows=cost,
		model=None,
		end=date(2026, 8, 17),
	)
	assert rep["vendor_ok"] is True
	assert abs(rep["totals"]["cost"] - 0.0274) < 1e-6
	assert rep["totals"]["tokens"] == 350
	assert rep["models"][0]["model"] == "deepseek-v4-flash"


def test_fetch_missing_key() -> None:
	rep = fetch_vendor_usage(api_key="", provider="deepseek", days=7)
	assert rep["vendor_ok"] is False
	assert rep["vendor_error"] == "missing_key"
	assert rep["totals"]["requests"] == 0


def test_deepseek_does_not_call_platform_usage() -> None:
	rep = fetch_vendor_usage(api_key="sk-test-key", provider="deepseek", days=7)
	assert rep["vendor_ok"] is False
	assert "API Key" in (rep.get("vendor_error") or "")
	assert rep["totals"]["requests"] == 0
