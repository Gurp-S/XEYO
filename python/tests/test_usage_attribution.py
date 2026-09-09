"""用量真实厂商(vendor)归属与口径契约（2026-09-09 P0-1 / P1-2 修复；B1 v4 去金额）。

覆盖：
- canonical_vendor：通道语义(local/fake)、base_url 主机、模型名前缀、回退通道。
- 记账：错位通道(openai×deepseek 模型 / deepseek×glm 模型)按 vendor 归组。
- v4：聚合报表无金额 —— totals/models 只回三分类 + hit_rate + 成功结算 requests；
  价目估算只留在 usage.pricing 纯函数层与事件行日志（无官方价目厂商走中性估算档，
  不落 2/8 美元预算兜底）。
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
# 记账：vendor 归组（v4 无金额，只验三分类）
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
	assert rep["totals"]["input_miss"] == 300
	assert rep["totals"]["input_hit"] == 0
	assert rep["totals"]["output"] == 30
	assert rep["totals"]["hit_rate"] == 0.0


def test_ledger_report_money_free_by_vendor(tmp_path, monkeypatch) -> None:
	"""v4 红线：记账行即使带真实官方 cost_cny，聚合报表也不回金额。

	错位通道（openai×deepseek）按真实厂商归组；大额行只以三分类形式呈现。
	"""
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	record_from_openai_usage(
		provider="openai",
		model="deepseek-v4-flash",
		api_key="sk-abcdefghijklmnopqrstuv",
		usage={
			"prompt_tokens": 1_000_000,
			"prompt_cache_hit_tokens": 0,
			"prompt_cache_miss_tokens": 1_000_000,
			"completion_tokens": 1_000_000,
			"cost_cny": 6.0,
		},
		ts=utc_ts(2026, 8, 16, 19, 0),
	)
	rep = query_usage(days=30)
	m0 = rep["models"][0]
	assert m0["provider"] == "deepseek"  # 归位，不是 openai
	assert m0["model"] == "deepseek-v4-flash"
	assert rep["totals"]["input_miss"] == 1_000_000
	assert rep["totals"]["output"] == 1_000_000
	assert rep["totals"]["input_total"] == 1_000_000
	assert rep["totals"]["hit_rate"] == 0.0
	assert "cost" not in rep["totals"]
	assert "tokens" not in rep["totals"]
	assert "cost_source" not in rep
	assert "lifetime_cost" not in rep


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
# 窗口 / 维度筛选语义：totals 只计窗口内成功结算请求，厂商/模型/Key 筛选各司其职
# ---------------------------------------------------------------------------

def test_window_and_filter_dimensions(tmp_path, monkeypatch) -> None:
	"""窗口过滤：30 天窗口外旧行不进 totals；厂商/模型筛选仍精确。"""
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	old_ts = utc_ts(2026, 6, 1, 19, 0)  # 30 天窗口之外（距今 ~100 天）
	record_from_openai_usage(
		provider="deepseek", model="deepseek-v4-flash",
		api_key="sk-abcdefghijklmnopqrstuv",
		usage={"prompt_tokens": 1_000_000, "prompt_cache_miss_tokens": 1_000_000, "completion_tokens": 0}, ts=old_ts,
	)
	record_from_openai_usage(
		provider="deepseek", model="deepseek-v4-flash",
		api_key="sk-abcdefghijklmnopqrstuv",
		usage={"prompt_tokens": 100, "prompt_cache_miss_tokens": 100, "completion_tokens": 0}, ts=None,
	)
	rep30 = query_usage(days=30)
	# 30 天窗口只含新行；旧行（~100 天前）被窗口滤掉
	assert rep30["totals"]["requests"] == 1
	assert rep30["totals"]["input_miss"] == 100
	assert rep30["totals"]["hit_rate"] == 0.0
	# 厂商筛选
	rep_deep = query_usage(days=30, provider="deepseek")
	assert rep_deep["totals"]["requests"] == rep30["totals"]["requests"]
	# 不存在的模型 → 全零桶 + hit_rate None（无输入不做除法）
	rep_other = query_usage(days=30, model="nonexistent-model")
	assert rep_other["totals"]["requests"] == 0
	assert rep_other["totals"]["input_miss"] == 0
	assert rep_other["totals"]["hit_rate"] is None


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
	assert rep["totals"]["input_miss"] == 100
	assert rep["totals"]["output"] == 10
	# model detail 视图同理
	assert query_usage(days=30, provider="openai", model="deepseek-v4-flash")["totals"]["requests"] == 1


# ---------------------------------------------------------------------------
# B0.5 记账地基：request_id/attempt/kind 归因（对齐 DeepSeek Harness S2/S4/D-3）
# ---------------------------------------------------------------------------

def _rows(tmp_path) -> list[dict]:
	from usage.ledger import events_path

	p = events_path()
	if not p.is_file():
		return []
	return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_record_writes_request_meta_when_provided(tmp_path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	record_from_openai_usage(
		provider="deepseek",
		model="deepseek-v4-flash",
		api_key="sk-abcdefghijklmnopqrstuv",
		usage={"prompt_tokens": 100, "prompt_cache_miss_tokens": 100, "completion_tokens": 10},
		ts=utc_ts(2026, 8, 17, 19, 0),
		session_id="sess-a",
		request_id="req-0000000000000001",
		attempt=2,
		kind="turn",
	)
	rows = _rows(tmp_path)
	assert len(rows) == 1
	r = rows[0]
	assert r["request_id"] == "req-0000000000000001"
	assert r["attempt"] == 2
	assert r["kind"] == "turn"
	# cache_write / reasoning_tokens 恒 0 / 缺省时不写（保持行最小）
	assert "cache_write" not in r
	assert "reasoning_tokens" not in r


def test_record_cache_write_and_reasoning_only_when_positive(tmp_path, monkeypatch) -> None:
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	record_from_openai_usage(
		provider="openai",
		model="gpt-4o",
		api_key="sk-abcdefghijklmnopqrstuv",
		usage={"prompt_tokens": 100, "prompt_cache_miss_tokens": 100, "completion_tokens": 10},
		ts=utc_ts(2026, 8, 17, 19, 0),
		request_id="req-x", kind="turn",
		cache_write=0, reasoning_tokens=0,
	)
	# 零值不落键：dsh S1 四桶兜底字段只在真有 write 时出现
	assert "cache_write" not in _rows(tmp_path)[0]
	assert "reasoning_tokens" not in _rows(tmp_path)[0]
	record_from_openai_usage(
		provider="openai",
		model="gpt-4o",
		api_key="sk-abcdefghijklmnopqrstuv",
		usage={"prompt_tokens": 100, "prompt_cache_miss_tokens": 100, "completion_tokens": 10},
		ts=utc_ts(2026, 8, 17, 19, 1),
		request_id="req-y", kind="turn",
		cache_write=55, reasoning_tokens=33,
	)
	r2 = _rows(tmp_path)[1]
	assert r2["cache_write"] == 55
	assert r2["reasoning_tokens"] == 33
	# reasoning 归 output 子分类：只作诊断字段，不参与 output 求和（dsh S1）
	assert r2["output"] == 10


def test_same_request_id_retry_attempts_both_recorded(tmp_path, monkeypatch) -> None:
	"""dsh S4 / 0.1.2-alpha.1 语义：重试的 attempt 各自入账（provider 对每个
	HTTP 请求独立计费），request_id 归并 family 供审计，不做撤销记账（YAGNI）。"""
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	rid = "req-retry-1"
	for att in (1, 2):
		record_from_openai_usage(
			provider="deepseek",
			model="deepseek-v4-flash",
			api_key="sk-abcdefghijklmnopqrstuv",
			usage={"prompt_tokens": 100, "prompt_cache_miss_tokens": 100, "completion_tokens": 10},
			ts=utc_ts(2026, 8, 17, 19, att),  # 两次尝试、不同秒
			session_id="sess-a",
			request_id=rid,
			attempt=att,
			kind="turn",
		)
	rows = _rows(tmp_path)
	assert len(rows) == 2
	assert {r["attempt"] for r in rows} == {1, 2}
	assert all(r["request_id"] == rid for r in rows)
	assert query_usage(days=30)["totals"]["requests"] == 2


def test_record_without_request_id_keeps_old_row_shape(tmp_path, monkeypatch) -> None:
	"""无 request_id 的调用点（CLI/评测/旧路径）保持原行结构，零扰动。"""
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	record_from_openai_usage(
		provider="deepseek",
		model="deepseek-v4-flash",
		api_key="sk-abcdefghijklmnopqrstuv",
		usage={"prompt_tokens": 100, "prompt_cache_miss_tokens": 100, "completion_tokens": 10},
		ts=utc_ts(2026, 8, 17, 19, 0),
	)
	r = _rows(tmp_path)[0]
	assert "request_id" not in r
	assert "attempt" not in r
	assert "kind" not in r
	assert "cost_cny" in r  # 原始日志字段仍在


def test_ledger_session_id_faithful_for_fork_isolation(tmp_path, monkeypatch) -> None:
	"""fork 隔离的结构免疫依据：账本行忠实记录 session_id，事件归属写方会话。

	fork（server/sessions.py）只复制 transcript、从不复制 events 账本；子会话用
	新 sid 记账 → 按 session 下钻时子会话天然不含父历史（对齐 dsh S5，结构免疫）。
	"""
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	for sid in ("sess-parent", "xeyo-newforkchild"):
		record_from_openai_usage(
			provider="deepseek",
			model="deepseek-v4-flash",
			api_key="sk-abcdefghijklmnopqrstuv",
			usage={"prompt_tokens": 100, "prompt_cache_miss_tokens": 100, "completion_tokens": 10},
			ts=utc_ts(2026, 8, 17, 19, 0),
			session_id=sid,
			request_id=f"req-{sid}",
		)
	by_sid = {r["session_id"]: r for r in _rows(tmp_path)}
	assert set(by_sid) == {"sess-parent", "xeyo-newforkchild"}
	assert by_sid["sess-parent"]["request_id"] != by_sid["xeyo-newforkchild"]["request_id"]
