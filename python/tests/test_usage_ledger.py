from __future__ import annotations

from model.openai_compat import parse_sse_usage
from usage.ledger import query_usage, record_from_openai_usage
from usage.pricing import estimate_cny, is_beijing_peak, split_usage


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
	# v4 三分类（dsh S1 disjoint）：只分 hit/miss/output，禁止相加成「总消耗」
	assert rep["totals"]["input_hit"] == 60
	assert rep["totals"]["input_miss"] == 90
	assert rep["totals"]["output"] == 30
	assert rep["totals"]["input_total"] == 150
	assert rep["totals"]["hit_rate"] == 40.0
	assert len(rep["models"]) == 2
	assert rep["keys"] == ["…stuv"]
	flash = query_usage(days=30, model="deepseek-v4-flash")
	assert flash["totals"]["requests"] == 1
	assert flash["totals"]["input_miss"] == 40
	assert flash["models"][0]["model"] == "deepseek-v4-flash"


def test_report_totals_money_free_schema(tmp_path, monkeypatch) -> None:
	"""v4 红线：聚合报表层全链路无金额 / 无吞吐大数。

	events 行保留 cost_cny / tokens 等原始字段（日志保留、供后端审计），但
	query_usage 的 totals / series / models 每层只允许三分类 + hit_rate +
	成功结算 requests —— 前端拿不到钱数，杜绝「估算不准却显示」。
	"""
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	record_from_openai_usage(
		provider="deepseek",
		model="deepseek-v4-flash",
		api_key="sk-abcdefghijklmnopqrstuv",
		usage={
			"prompt_tokens": 100,
			"prompt_cache_hit_tokens": 60,
			"prompt_cache_miss_tokens": 40,
			"completion_tokens": 20,
			"cost_cny": 0.42,
		},
	)
	rep = query_usage(days=7)
	assert set(rep["totals"]) == {
		"requests",
		"input_hit",
		"input_miss",
		"output",
		"input_total",
		"hit_rate",
	}
	assert rep["totals"]["requests"] == 1
	assert rep["totals"]["input_hit"] == 60
	assert rep["totals"]["input_miss"] == 40
	assert rep["totals"]["output"] == 20
	assert rep["totals"]["input_total"] == 100
	assert rep["totals"]["hit_rate"] == 60.0
	# 顶层与模型行同样无金额字段
	assert "cost" not in rep
	assert "tokens" not in rep
	assert "cost_source" not in rep
	assert "lifetime_cost" not in rep
	# 系列点：同一 schema + day 维度键
	p0 = rep["series"][-1]  # 今天（ts=None 落在窗口末位）
	assert p0["requests"] == 1
	assert p0["input_miss"] == 40
	assert set(p0) - {"day"} == set(rep["totals"])
