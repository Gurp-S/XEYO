from __future__ import annotations

from model.openai_compat import parse_sse_usage
from usage.ledger import query_usage, record_from_openai_usage
from usage.pricing import estimate_cny, is_beijing_peak, official_cost_cny, split_usage


def test_parse_sse_usage_from_empty_choices() -> None:
	line = 'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1}}'
	u = parse_sse_usage(line)
	assert u is not None
	assert u["prompt_tokens"] == 3
	assert parse_sse_usage("data: [DONE]") is None


def test_split_usage_prefers_explicit_cache_fields() -> None:
	hit, miss, out = split_usage(
		{
			"prompt_tokens": 100,
			"prompt_cache_hit_tokens": 80,
			"prompt_cache_miss_tokens": 20,
			"completion_tokens": 10,
		}
	)
	assert (hit, miss, out) == (80, 20, 10)


def test_split_usage_openai_cached_details() -> None:
	hit, miss, out = split_usage(
		{
			"prompt_tokens": 50,
			"completion_tokens": 5,
			"prompt_tokens_details": {"cached_tokens": 40},
		}
	)
	assert hit == 40
	assert miss == 10
	assert out == 5


def test_peak_hours_beijing() -> None:
	# 10:00 CST = 02:00 UTC（高峰）；03:00 CST = 前一日 19:00 UTC（空闲）
	peak = datetime_ts(2026, 8, 17, 2, 0)
	idle = datetime_ts(2026, 8, 16, 19, 0)
	assert is_beijing_peak(peak) is True
	assert is_beijing_peak(idle) is False


def datetime_ts(y: int, m: int, d: int, hour_utc: int, minute: int) -> float:
	from datetime import datetime, timezone

	return datetime(y, m, d, hour_utc, minute, tzinfo=timezone.utc).timestamp()


def test_deepseek_flash_idle_cost() -> None:
	# 空闲：未命中 1.5 / 输出 4.5 每百万
	ts = datetime_ts(2026, 8, 16, 19, 0)
	cost = estimate_cny(
		provider="deepseek",
		model="deepseek-v4-flash",
		usage={
			"prompt_tokens": 1_000_000,
			"prompt_cache_hit_tokens": 0,
			"prompt_cache_miss_tokens": 1_000_000,
			"completion_tokens": 1_000_000,
		},
		ts=ts,
	)
	assert abs(cost - 6.0) < 1e-6


def test_record_and_query(tmp_path, monkeypatch) -> None:
	from datetime import datetime, timedelta, timezone

	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	ts = datetime.now(tz=timezone(timedelta(hours=8))).timestamp()
	record_from_openai_usage(
		provider="deepseek",
		model="deepseek-v4-flash",
		api_key="sk-abcdefghijklmnopqrstuv",
		usage={
			"prompt_tokens": 100,
			"prompt_cache_hit_tokens": 60,
			"prompt_cache_miss_tokens": 40,
			"completion_tokens": 20,
		},
		ts=ts,
	)
	record_from_openai_usage(
		provider="deepseek",
		model="deepseek-v4-pro",
		api_key="sk-abcdefghijklmnopqrstuv",
		usage={
			"prompt_tokens": 50,
			"prompt_cache_hit_tokens": 0,
			"prompt_cache_miss_tokens": 50,
			"completion_tokens": 10,
		},
		ts=ts,
	)
	rep = query_usage(days=30)
	assert rep["totals"]["requests"] == 2
	assert rep["totals"]["tokens"] == 180
	assert len(rep["models"]) == 2
	assert rep["keys"] == ["…stuv"]
	flash = query_usage(days=30, model="deepseek-v4-flash")
	assert flash["totals"]["requests"] == 1
	assert flash["models"][0]["model"] == "deepseek-v4-flash"


def test_official_cost_field_wins_over_estimate(tmp_path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	assert official_cost_cny({"prompt_tokens": 10}) is None
	assert official_cost_cny({"cost_cny": 1.25}) == 1.25
	record_from_openai_usage(
		provider="deepseek",
		model="deepseek-v4-flash",
		api_key="sk-abcdefghijklmnopqrstuv",
		usage={
			"prompt_tokens": 100,
			"completion_tokens": 20,
			"total_tokens": 120,
			"cost_cny": 0.42,
		},
	)
	rep = query_usage(days=7)
	assert rep["totals"]["tokens"] == 120
	assert abs(rep["totals"]["cost"] - 0.42) < 1e-9
	assert rep["cost_source"] == "api"
