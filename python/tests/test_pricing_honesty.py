"""计价诚实性：没有权威价目的厂商，账本与面板都不得出现金额。

结构性根因（2026-09-27 修复）：``estimate_cny`` 的返回类型过去是 ``float`` —— 类型上
就不允许「未知」存在，于是无价目厂商被借 DeepSeek flash 空闲档算出一个数，
``cost_cny`` 恒有值、``cost_source`` 恒为 ``estimate``。这里把「无价目」钉成
一等状态并逐层回归：

1. 未登记厂商 ⇒ ``cost_cny`` 为 ``null`` 且来源可判为「无价目」；
2. 已登记厂商（deepseek / openai）金额逐分不变；
3. 聚合（A3 生成器）遇 ``null`` 不当 0 累加（诊断面在
   ``tests/diagnostics/test_report_honesty.py``）；
4. 预算闸在无价目模型上既不静默放行也不误拦，且原因可读。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from engine.budget import BudgetTracker
from usage import pricing
from usage.ledger import events_path, record_from_openai_usage
from usage.pricing import (
	estimate_cny,
	estimate_usd,
	price_authority,
)

#: 空闲档时刻（UTC 19:00 = 北京 03:00）——DeepSeek 倍率 ×1，断言不随跑测时间漂移。
_OFFPEAK_TS = datetime(2026, 8, 16, 19, 0, tzinfo=timezone.utc).timestamp()


def _usage(prompt: int = 1000, hit: int = 800, completion: int = 500) -> dict:
	return {
		"prompt_tokens": prompt,
		"prompt_cache_hit_tokens": hit,
		"prompt_cache_miss_tokens": max(0, prompt - hit),
		"completion_tokens": completion,
	}


@pytest.fixture
def no_registered_price(monkeypatch):
	"""清掉用户登记价（env 覆盖）：本机环境里的覆盖会让「无价目」测不出来。"""
	for key in pricing._PRICE_ENV_KEYS:
		monkeypatch.delenv(key, raising=False)
	# 不联网：实时价目链路在本测试里恒不命中（确定性 + 离线）。
	monkeypatch.setattr(pricing, "_load_pricing_json", lambda timeout: None)
	yield


# ---------- 1. 未登记厂商：账本落 null + 来源可判 ----------


def test_unpriced_vendor_records_null_cost(tmp_path, monkeypatch, no_registered_price) -> None:
	"""没有权威价目 ⇒ ``cost_cny`` 是 null、``cost_source`` 是 unpriced（不是 0 / estimate）。"""
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	record_from_openai_usage(
		provider="zhipu",
		model="glm-4.6v",
		api_key="sk-test1234",
		usage=_usage(),
		ts=_OFFPEAK_TS,
	)
	rows = [
		json.loads(line)
		for line in events_path().read_text(encoding="utf-8").splitlines()
		if line.strip()
	]
	assert len(rows) == 1
	row = rows[0]
	assert row["vendor"] == "zhipu"
	assert row["cost_cny"] is None
	assert row["cost_source"] == "unpriced"
	assert row["price_authority"] == "none"
	# 用量本身照记：无价目只影响钱，不影响 token 账。
	assert row["cache_miss"] == 200
	assert row["output"] == 500


def test_price_authority_three_states(no_registered_price, monkeypatch) -> None:
	"""判据三态机器可判，且与既有 ``_has_explicit_price`` 同源（不新造第二套口径）。"""
	assert price_authority("zhipu") == "none"
	assert price_authority("deepseek") == "vendor"
	assert price_authority("openai") == "vendor"
	assert pricing._has_explicit_price("zhipu") is False
	assert pricing._has_explicit_price("deepseek") is True
	# 用户显式登记（env 覆盖）→ user：登记过就照用，不再是无价目。
	monkeypatch.setenv("XEYO_BUDGET_PRICE_INPUT_USD", "1.0")
	assert price_authority("zhipu") == "user"
	assert pricing._has_explicit_price("zhipu") is True


def test_estimate_cny_returns_none_without_price(no_registered_price) -> None:
	"""计价函数的契约就是「无价目 → None」：不再借别家价目顶替出一个数。"""
	assert estimate_cny(
		provider="zhipu", model="glm-4.6v", usage=_usage(), ts=_OFFPEAK_TS
	) is None
	assert estimate_usd(
		provider="zhipu", model="glm-4.6v", usage=_usage(), local_only=True, ts=_OFFPEAK_TS
	) is None
	# 实时价目链路同样不回落通用默认价（否则预算闸会拿 2.0/8.0 美元算「还剩多少」）。
	assert pricing.get_model_pricing("zhipu", "glm-4.6v") is None


# ---------- 2. 已登记厂商：金额逐分不变 ----------


def test_registered_vendor_amounts_unchanged(no_registered_price) -> None:
	"""主路径（deepseek / openai）分毫不动 —— 防修未知把已知改坏。"""
	usage = _usage(prompt=1000, hit=800, completion=500)
	# DeepSeek flash 空闲档：(800×0.05 + 200×1.5 + 500×4.5) / 1M
	assert estimate_cny(
		provider="deepseek", model="deepseek-v4-flash", usage=usage, ts=_OFFPEAK_TS
	) == pytest.approx(0.00259, abs=1e-12)
	# OpenAI gpt-4o：(200×2.5 + 800×1.25 + 500×10) / 1M × 7.2
	assert estimate_cny(
		provider="openai", model="gpt-4o", usage=usage, ts=_OFFPEAK_TS
	) == pytest.approx(0.0468, abs=1e-12)


def test_registered_vendor_ledger_row_keeps_estimate_semantics(
	tmp_path, monkeypatch, no_registered_price
) -> None:
	"""``estimate`` 语义未变窄：内置厂商价目仍记 ``estimate``，细分看 price_authority。"""
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	record_from_openai_usage(
		provider="deepseek",
		model="deepseek-v4-flash",
		api_key="sk-test1234",
		usage=_usage(),
		ts=_OFFPEAK_TS,
	)
	row = json.loads(events_path().read_text(encoding="utf-8").splitlines()[0])
	assert row["cost_source"] == "estimate"
	assert row["price_authority"] == "vendor"
	assert row["cost_cny"] == pytest.approx(0.00259, abs=1e-12)


def test_user_registered_price_is_labelled_user_not_none(
	tmp_path, monkeypatch, no_registered_price
) -> None:
	"""用户登记价：能算钱（estimate）且来源可判为 user —— 三态里「登记价」那一档。"""
	monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path))
	monkeypatch.setenv("XEYO_BUDGET_PRICE_INPUT_USD", "2.0")
	monkeypatch.setenv("XEYO_BUDGET_PRICE_CACHED_INPUT_USD", "0.2")
	monkeypatch.setenv("XEYO_BUDGET_PRICE_OUTPUT_USD", "8.0")
	record_from_openai_usage(
		provider="zhipu",
		model="glm-4.6v",
		api_key="sk-test1234",
		usage=_usage(prompt=1000, hit=800, completion=500),
		ts=_OFFPEAK_TS,
	)
	row = json.loads(events_path().read_text(encoding="utf-8").splitlines()[0])
	assert row["cost_source"] == "estimate"
	assert row["price_authority"] == "user"
	# (200×2 + 800×0.2 + 500×8) / 1M × 7.2 = 4560e-6 × 7.2
	assert row["cost_cny"] == pytest.approx(0.032832, abs=1e-9)


# ---------- 3. 聚合：null 不许当 0 ----------


def test_a3_aggregation_never_adds_null_as_zero() -> None:
	"""A3 生成器的日/模型聚合：无价目行只计「未知条数」，绝不加 0 进合计。"""
	from scripts.memory_stack_eval import _cost_accumulate, _cost_fields

	bucket: dict = {}
	_cost_accumulate(bucket, {"cost_cny": None})
	_cost_accumulate(bucket, {"cost_cny": 0.5})
	_cost_accumulate(bucket, {"cost_cny": ""})  # 坏值同样算未知，不算 0
	fields = _cost_fields(bucket)
	assert fields["cost_cny"] == pytest.approx(0.5)
	assert fields["cost_unknown_requests"] == 2


def test_a3_aggregation_all_unpriced_is_null_not_zero() -> None:
	from scripts.memory_stack_eval import _cost_accumulate, _cost_fields

	bucket: dict = {}
	for _ in range(3):
		_cost_accumulate(bucket, {"cost_cny": None})
	fields = _cost_fields(bucket)
	assert fields["cost_cny"] is None  # 无价目 ⇒ 无数据，不是 ¥0.00
	assert fields["cost_unknown_requests"] == 3


# ---------- 4. 预算闸：既不静默放行也不误拦 ----------


def test_usd_gate_inactive_for_unpriced_model(no_registered_price) -> None:
	"""无价目 ⇒ 该闸对这些模型不生效：不误拦，但也不静默（原因可读、可断言）。"""
	tracker = BudgetTracker(provider="zhipu", model="glm-4.6v", usd_limit=0.0001)
	tracker.add_usage({"prompt_tokens": 600_000, "completion_tokens": 0})
	assert tracker.last_usage_usd is None
	assert tracker.last_cost_source == "unpriced"
	assert tracker.last_price_authority == "none"
	# 不误拦：拿不到价目就不许假装算出「已超限」。
	assert tracker.over_budget is False
	assert tracker.used_usd == 0.0
	# 不静默放行：原因必须说得出（界面 / 日志读同一句）。
	assert tracker.usd_gate_note
	assert "zhipu" in tracker.usd_gate_note
	assert "费用未知" in tracker.usd_gate_note


def test_usd_gate_enforces_when_user_registered_price() -> None:
	"""用户显式登记过价 ⇒ 闸照用（既有急停链零变化）。"""
	tracker = BudgetTracker(
		provider="zhipu",
		model="glm-4.6v",
		usd_limit=1.0,
		prices={"input_miss": 2.0, "input_hit": 0.2, "output": 8.0},
	)
	tracker.add_usage({"prompt_tokens": 600_000, "completion_tokens": 0})
	assert tracker.last_price_authority == "user"
	assert tracker.used_usd == pytest.approx(1.2)
	assert tracker.over_budget is True
	assert tracker.usd_gate_note == ""


def test_usd_waterline_silent_when_part_of_spend_unknown(no_registered_price) -> None:
	"""已花费金额不可判定时，水位播报整体关闭 —— 报出来的百分比会是假的。"""
	tracker = BudgetTracker(provider="zhipu", model="glm-4.6v", usd_limit=1.0)
	tracker.prices = {"input_miss": 2.0, "input_hit": 0.2, "output": 8.0}
	tracker.add_usage({"prompt_tokens": 300_000, "completion_tokens": 0})  # 0.6 USD
	tracker.prices = None  # 用户没登记价 → 下一轮无从计价
	tracker.add_usage({"prompt_tokens": 300_000, "completion_tokens": 0})
	assert tracker.usd_unpriced_turns == 1
	assert tracker.used_usd == pytest.approx(0.6)
	tracker.check_usd_waterline()
	assert tracker.consume_runtime_notice() is None


def test_usage_event_carries_null_and_gate_note(no_registered_price) -> None:
	"""SSE 用量事件：金额未知必须原样传 None（落 0 就是把未知读成免费）。"""
	from engine.query_loop import _round8

	assert _round8(None) is None
	assert _round8(0.001) == 0.001
