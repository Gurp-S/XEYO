"""用量真实厂商(vendor)归属与计价口径契约（2026-09-09 P0-1 / P1-2 修复）。

覆盖：
- canonical_vendor：通道语义(local/fake)、base_url 主机、模型名前缀、回退通道。
- 记账：错位通道(openai×deepseek 模型 / deepseek×glm 模型)按 vendor 归组计价。
- 计价：无官方价目厂商走中性估算档（不落 2/8 美元预算兜底）。
- P1-2：XEYO_TIME_TIERS_JSON 自定义倍率对 estimate_cny / unit_prices 生效。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from usage.attribution import canonical_vendor, vendor_from_host, vendor_from_model_name
from usage.ledger import query_usage, record_from_openai_usage
from usage.pricing import estimate_cny, split_usage, unit_prices_cny_per_mtoken


def utc_ts(y: int, mo: int, d: int, h: int, mi: int = 0) -> float:
	return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp()


# ---------------------------------------------------------------------------
# canonical_vendor 归属
# ---------------------------------------------------------------------------

def test_model_prefix_glm_is_zhipu() -> None:
	assert vendor_from_model_name("glm-4.5-air") == "zhipu"
	assert vendor_from_model_name("glm-5.3-flash") == "zhipu"
	assert vendor_from_model_name("chatglm-turbo") == "zhipu"


def test_model_prefix_deepseek_gpt_qwen() -> None:
	assert vendor_from_model_name("deepseek-v4-flash") == "deepseek"
	assert vendor_from_model_name("deepseek-chat") == "deepseek"
	assert vendor_from_model_name("gpt-4o") == "openai"
	assert vendor_from_model_name("o1-preview") == "openai"
	assert vendor_from_model_name("qwen2.5:7b") == "qwen"
	assert vendor_from_model_name("claude-3-5-sonnet") == "anthropic"


def test_unknown_model_keeps_no_match() -> None:
	assert vendor_from_model_name("mystery-model") == ""
	assert vendor_from_model_name("") == ""


def test_host_wins_over_model_prefix() -> None:
	# 模型名是 openai 系、但 base_url 指向智谱 → 主机白名单优先。
	assert (
		canonical_vendor(model="gpt-4o", provider="openai", base_url="https://open.bigmodel.cn/api/paas/v4")
		== "zhipu"
	)


def test_channel_local_preserved() -> None:
	assert canonical_vendor(model="llama3.1", provider="local") == "local"
	assert canonical_vendor(model="fake-model", provider="fake") == "fake"


def test_fallback_to_channel() -> None:
	assert canonical_vendor(model="custom-thing", provider="openai") == "openai"


def test_deepseek_under_openai_channel() -> None:
	assert canonical_vendor(model="deepseek-v4-flash", provider="openai") == "deepseek"


# ---------------------------------------------------------------------------
# 记账：vendor 归组 + 按真实厂商计价
# ---------------------------------------------------------------------------

def test_ledger_groups_by_vendor_not_channel(tmp_path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	# openai 通道 + deepseek 模型（真实存在的错位行形态）
	record_from_openai_usage(
		provider="openai",
		model="deepseek-v4-flash",
		api_key="sk-abcdefghijklmnopqrstuv",
		usage={"prompt_tokens": 100, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 100, "completion_tokens": 10},
		ts=utc_ts(2026, 8, 17, 19, 0),  # 北京 03:00 空闲
	)
	# deepseek 通道 + glm 模型
	record_from_openai_usage(
		provider="deepseek",
		model="glm-4.5-air",
		api_key="sk-abcdefghijklmnopqrstuv",
		usage={"prompt_tokens": 200, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 200, "completion_tokens": 20},
		ts=utc_ts(2026, 8, 17, 19, 0),
	)
	rep = query_usage(days=30)
	by_model = {m["model"]: m for m in rep["models"]}
	assert by_model["deepseek-v4-flash"]["provider"] == "deepseek"  # 归位，不是 openai
	assert by_model["glm-4.5-air"]["provider"] == "zhipu"  # 归位，不是 deepseek
	assert rep["totals"]["requests"] == 2
	assert rep["totals"]["cache_miss"] == 300  # totals 拆分字段
	assert rep["totals"]["output"] == 30


def test_ledger_estimate_uses_real_vendor_prices(tmp_path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	# openai 通道 + deepseek 模型：不能再按 gpt-4o-mini 兜底价，应按 DeepSeek 官方空闲档。
	record_from_openai_usage(
		provider="openai",
		model="deepseek-v4-flash",
		api_key="sk-abcdefghijklmnopqrstuv",
		usage={"prompt_tokens": 1_000_000, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 1_000_000, "completion_tokens": 1_000_000},
		ts=utc_ts(2026, 8, 16, 19, 0),  # 空闲
	)
	rep = query_usage(days=30)
	# deepseek flash 空闲：未命中 1.5 + 输出 4.5 = 6.0
	assert abs(rep["totals"]["cost"] - 6.0) < 1e-6


def test_ledger_glm_neutral_estimate(tmp_path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	# glm 无本地官方价目：中性估算档 = deepseek-flash 空闲（1.5/0.05/4.5），不暴涨。
	record_from_openai_usage(
		provider="deepseek",
		model="glm-4.5-air",
		api_key="sk-abcdefghijklmnopqrstuv",
		usage={"prompt_tokens": 1_000_000, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 1_000_000, "completion_tokens": 1_000_000},
		ts=utc_ts(2026, 8, 16, 19, 0),
	)
	rep = query_usage(days=30)
	assert abs(rep["totals"]["cost"] - 6.0) < 1e-6
	assert rep["cost_source"] == "estimate"


# ---------------------------------------------------------------------------
# 计价：中性档 / time-tier 覆盖
# ---------------------------------------------------------------------------

def test_unknown_vendor_neutral_cny_not_budget_default() -> None:
	# 中性档未命中 1.5 / 输出 4.5；而非 _DEFAULT_USD_PRICES(2/8 USD → 14.4/57.6 CNY)
	ts = utc_ts(2026, 8, 16, 19, 0)
	cost = estimate_cny(
		provider="zhipu",
		model="glm-4.5-air",
		usage={"prompt_tokens": 1_000_000, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 1_000_000, "completion_tokens": 1_000_000},
		ts=ts,
	)
	assert abs(cost - 6.0) < 1e-6


def test_time_tier_override_affects_estimate(monkeypatch) -> None:
	cfg = {
		"deepseek": {
			"windows": {"peak": (("09:00", "12:00"), ("14:00", "18:00"))},
			"multipliers": {"peak": 1.5, "offpeak": 1.0},
		}
	}
	monkeypatch.setenv("XEYO_TIME_TIERS_JSON", json.dumps(cfg))
	ts_peak = utc_ts(2026, 8, 17, 2, 0)  # 北京 10:00 高峰
	usage = {"prompt_tokens": 1_000_000, "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 1_000_000, "completion_tokens": 1_000_000}
	cost = estimate_cny(provider="deepseek", model="deepseek-v4-flash", usage=usage, ts=ts_peak)
	# 自定义倍率 1.5 生效（非硬编码 2×）：1.5*1.5 + 4.5*1.5 = 9.0
	assert abs(cost - 9.0) < 1e-6
	# 空闲档仍 ×1.0
	ts_idle = utc_ts(2026, 8, 16, 19, 0)
	cost_idle = estimate_cny(provider="deepseek", model="deepseek-v4-flash", usage=usage, ts=ts_idle)
	assert abs(cost_idle - 6.0) < 1e-6


def test_time_tier_override_affects_unit_prices(monkeypatch) -> None:
	cfg = {
		"deepseek": {
			"windows": {"peak": (("09:00", "12:00"), ("14:00", "18:00"))},
			"multipliers": {"peak": 1.5, "offpeak": 1.0},
		}
	}
	monkeypatch.setenv("XEYO_TIME_TIERS_JSON", json.dumps(cfg))
	ts_peak = utc_ts(2026, 8, 17, 2, 0)
	p_hit, p_miss, p_out, p_w = unit_prices_cny_per_mtoken(
		provider="deepseek", model="deepseek-v4-flash", ts=ts_peak
	)
	assert abs(p_miss - 2.25) < 1e-9  # 1.5 × 1.5
	assert abs(p_out - 6.75) < 1e-9  # 4.5 × 1.5
	assert p_w == 0.0
	# 强制 offpeak 覆盖
	p2 = unit_prices_cny_per_mtoken(
		provider="deepseek", model="deepseek-v4-flash", ts=ts_peak, slot="offpeak"
	)
	assert abs(p2[1] - 1.5) < 1e-9


# ---------------------------------------------------------------------------
# lifetime_cost 语义（P1-1）：尊重厂商/模型/Key 筛选，忽略时间窗口
# ---------------------------------------------------------------------------

def test_lifetime_filters_non_day_dimensions(tmp_path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	old_ts = utc_ts(2026, 6, 1, 19, 0)  # 30 天窗口之外（距今 ~100 天）
	record_from_openai_usage(
		provider="deepseek", model="deepseek-v4-flash",
		api_key="sk-abcdefghijklmnopqrstuv",
		usage={"prompt_tokens": 1_000_000, "completion_tokens": 0}, ts=old_ts,
	)
	# 新行：真·deepseek 官方档空闲 cost 0.0045*? -> 直接按 flash 空闲估算 1.5 元
	record_from_openai_usage(
		provider="deepseek", model="deepseek-v4-flash",
		api_key="sk-abcdefghijklmnopqrstuv",
		usage={"prompt_tokens": 100, "prompt_cache_miss_tokens": 100, "completion_tokens": 0}, ts=None,
	)
	rep30 = query_usage(days=30)
	# 30 天窗口内 totals 只含新行；lifetime 含 90 天外旧行
	assert rep30["totals"]["requests"] == 1
	assert rep30["lifetime_cost"] > rep30["totals"]["cost"]
	# 厂商筛选同样作用于 lifetime
	rep_deep = query_usage(days=30, provider="deepseek")
	assert rep_deep["lifetime_cost"] == rep30["lifetime_cost"]
	# 模型筛选作用
	rep_other = query_usage(days=30, model="nonexistent-model")
	assert rep_other["lifetime_cost"] == 0.0
	assert rep_other["totals"]["requests"] == 0


def test_key_detail_not_emptied_by_vendor_filter(tmp_path, monkeypatch) -> None:
	"""厂商过滤只在「纯厂商视图」生效；key_fp/model 已唯一化子集时不再按厂商卡。

	回归场景：错位通道 key（openai 通道下全是 vendor=deepseek 的 deepseek-v4-flash
	行）单选该 key 时必须显示其全部用量，而不是被 vendor=openai 过滤卡空。
	"""
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	record_from_openai_usage(
		provider="openai",  # 错位通道
		model="deepseek-v4-flash",
		api_key="sk-abcdefghijklmnopqrstuv",
		usage={"prompt_tokens": 100, "prompt_cache_miss_tokens": 100, "completion_tokens": 10},
		ts=utc_ts(2026, 8, 17, 19, 0),
	)
	# 纯厂商视图：provider=openai 只应命中 vendor=openai 的行（该 key 行 vendor=deepseek，滤掉）
	assert query_usage(days=30, provider="openai")["totals"]["requests"] == 0
	# key detail 视图：同一查询带上 key_fp 后必须命中（厂商过滤让位给 key）
	rep = query_usage(days=30, provider="openai", key_fp="…stuv")
	assert rep["totals"]["requests"] == 1
	assert rep["lifetime_cost"] == rep["totals"]["cost"]
	# model detail 视图同理
	assert query_usage(days=30, provider="openai", model="deepseek-v4-flash")["totals"]["requests"] == 1
