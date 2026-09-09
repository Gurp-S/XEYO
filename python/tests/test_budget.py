"""L1.2 预算：USD 记账 / 实时价 / 本地兜底 / 超限急停。"""

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from typing import AsyncIterator
from uuid import uuid4

import pytest

from engine.abort import AbortController
from engine.budget import BudgetTracker, max_budget_usd_from_env
from engine.query_engine import QueryEngine
from model.chunks import ModelChunk
from msgtypes.events import ResultEvent, StoppedEvent, UsageEvent
from msgtypes.message import ToolUse
from tools.echo import EchoTool
from tools.tool_registry import ToolRegistry
from usage import pricing

# 固定价格表（USD/1M），测试里禁用实时价，保证断言确定。
PIN = {"input_miss": 2.0, "input_hit": 0.2, "output": 8.0}


@pytest.fixture
def pin_pricing(monkeypatch):
	monkeypatch.setattr(
		pricing, "get_model_pricing", lambda provider, model, timeout=3.0: PIN
	)
	# 集成测试断言固定金额：把时刻钉在低峰，DeepSeek 高峰倍率（×2）不生效
	monkeypatch.setattr(pricing.time, "time", lambda: _OFFPEAK_TS)



@pytest.fixture(autouse=True)
def _reset_pricing_cache():
	# 每次测试前后清掉价格模块的内存/磁盘缓存状态，避免相互污染
	pricing._pricing_cache = None
	pricing._pricing_disk_loaded = False
	yield
	pricing._pricing_cache = None
	pricing._pricing_disk_loaded = False


def _usage(prompt=500, completion=600, hit=0, miss=None, usd=None) -> dict:
	if miss is None:
		miss = max(0, prompt - hit)
	return {
		"prompt_tokens": prompt,
		"completion_tokens": completion,
		"total_tokens": prompt + completion,
		"prompt_cache_hit_tokens": hit,
		"prompt_cache_miss_tokens": miss,
		**({"cost_usd": usd} if usd is not None else {}),
	}


def _datetime_ts(y: int, m: int, d: int, hour_utc: int, minute: int = 0) -> float:
	from datetime import datetime, timezone

	return datetime(y, m, d, hour_utc, minute, tzinfo=timezone.utc).timestamp()


# DeepSeek 分时段测试用：UTC 02:00 = 北京 10:00（高峰）；UTC 19:00 = 北京 03:00（低峰）
_PEAK_TS = _datetime_ts(2026, 8, 17, 2, 0)
_OFFPEAK_TS = _datetime_ts(2026, 8, 16, 19, 0)


class UsageToolModel:

	"""每轮返回 tool_use 并携带 usage，用于耗尽预算。"""

	def __init__(self, usage: dict) -> None:
		self._usage = usage
		self.last_usage: dict | None = None

	async def stream(
		self,
		messages: list[dict],
		tools: list[dict],
		abort: AbortController,
	) -> AsyncIterator[ModelChunk]:
		abort.raise_if_aborted()
		self.last_usage = dict(self._usage)
		yield ModelChunk(
			kind="tool_use",
			tool_use=ToolUse(
				id=f"call_{uuid4().hex[:8]}",
				name="echo",
				input={"text": "loop"},
			),
		)


def _engine(model: object, *, max_budget_usd: float | None = None) -> QueryEngine:
	reg = ToolRegistry()
	reg.register(EchoTool())
	cfg: dict = {
		"cwd": ".",
		"tools": reg,
		"model_client": model,
		"provider": "deepseek",
		"model": "deepseek-v4-flash",
	}
	if max_budget_usd is not None:
		cfg["max_budget_usd"] = max_budget_usd
	return QueryEngine(cfg)  # type: ignore[arg-type]


# ---------- 单元：实时价 / 本地兜底 ----------


def test_get_model_pricing_uses_vendor_table(monkeypatch):
	# 当前 aipricing.guru 真实结构：{"models":[{id,provider,pricing}]}
	monkeypatch.setattr(
		pricing,
		"_load_pricing_json",
		lambda timeout: {
			"models": [
				{
					"id": "deepseek-v4-flash",
					"name": "DeepSeek V4 Flash",
					"provider": "deepseek",
					"pricing": {
						"inputPerM": 0.22,
						"cachedInputPerM": 0.007,
						"outputPerM": 0.66,
					},
				},
				{
					"id": "gpt-4o",
					"name": "GPT-4o",
					"provider": "openai",
					"pricing": {
						"inputPerM": 2.5,
						"cachedInputPerM": 1.25,
						"outputPerM": 10.0,
					},
				},
			]
		},
	)
	assert pricing.get_model_pricing("deepseek", "deepseek-v4-flash") == {
		"input_miss": 0.22,
		"input_hit": 0.007,
		"output": 0.66,
	}
	assert pricing.get_model_pricing("openai", "gpt-4o") == {
		"input_miss": 2.5,
		"input_hit": 1.25,
		"output": 10.0,
	}
	# 忽略大小写 / 包含匹配（id 与 name 均可）
	assert pricing.get_model_pricing("DeepSeek", "DEEPSEEK-V4-FLASH") == {
		"input_miss": 0.22,
		"input_hit": 0.007,
		"output": 0.66,
	}
	assert pricing.get_model_pricing("deepseek", "v4-flash") == {
		"input_miss": 0.22,
		"input_hit": 0.007,
		"output": 0.66,
	}


def test_get_model_pricing_legacy_table_shape(monkeypatch):
	# 参考代码里的历史结构 {provider: {model: {prompt, cache_prompt, completion}}}
	monkeypatch.setattr(
		pricing,
		"_load_pricing_json",
		lambda timeout: {
			"deepseek": {
				"deepseek-v4-flash": {
					"prompt": 0.5,
					"cache_prompt": 0.05,
					"completion": 1.5,
				}
			}
		},
	)
	assert pricing.get_model_pricing("deepseek", "deepseek-v4-flash") == {
		"input_miss": 0.5,
		"input_hit": 0.05,
		"output": 1.5,
	}


def test_pricing_ttl_default_and_env(monkeypatch):
	assert pricing._pricing_ttl_seconds() == pytest.approx(24 * 3600)
	monkeypatch.setenv("XEYO_PRICING_TTL_HOURS", "2")
	assert pricing._pricing_ttl_seconds() == pytest.approx(2 * 3600)
	monkeypatch.setenv("XEYO_PRICING_TTL_HOURS", "oops")
	assert pricing._pricing_ttl_seconds() == pytest.approx(24 * 3600)
	monkeypatch.setenv("XEYO_PRICING_TTL_HOURS", "0.5")
	assert pricing._pricing_ttl_seconds() == pytest.approx(3600)  # 下限 1h


def test_disk_cache_avoids_network(monkeypatch, tmp_path):
	path = tmp_path / "pricing_cache.json"
	monkeypatch.setattr(pricing, "_cache_path", lambda: path)
	payload = {
		"models": [
			{
				"id": "deepseek-v4-flash",
				"provider": "deepseek",
				"pricing": {"inputPerM": 0.22, "outputPerM": 0.66},
			}
		]
	}
	path.write_text(
		json.dumps({"fetched_at": time.time(), "data": payload}), encoding="utf-8"
	)

	def boom(*_a, **_k):
		raise AssertionError("network should not run with fresh disk cache")

	monkeypatch.setattr(urllib.request, "urlopen", boom)
	assert pricing._load_pricing_json(2.0) == payload


def test_stale_disk_fallback_when_offline(monkeypatch, tmp_path):
	path = tmp_path / "pricing_cache.json"
	monkeypatch.setattr(pricing, "_cache_path", lambda: path)
	payload = {
		"models": [
			{
				"id": "gpt-4o",
				"provider": "openai",
				"pricing": {"inputPerM": 2.5, "outputPerM": 10.0},
			}
		]
	}
	path.write_text(
		json.dumps({"fetched_at": time.time() - 100 * 3600, "data": payload}),
		encoding="utf-8",
	)

	def boom(*_a, **_k):
		raise OSError("offline")

	monkeypatch.setattr(urllib.request, "urlopen", boom)
	assert pricing._load_pricing_json(2.0) == payload


def test_fetch_refreshes_disk_cache(monkeypatch, tmp_path):
	path = tmp_path / "pricing_cache.json"
	monkeypatch.setattr(pricing, "_cache_path", lambda: path)

	class FakeResp:
		def __enter__(self):
			return self

		def __exit__(self, *_a):
			return False

		def read(self):
			return (
				b'{"models":[{"id":"deepseek-v4-flash","provider":"deepseek",'
				b'"pricing":{"inputPerM":0.22,"outputPerM":0.66}}]}'
			)

	monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: FakeResp())
	with pricing._pricing_lock:
		pricing._pricing_cache = None
		pricing._refresh_inflight = False
	data = pricing.refresh_pricing_blocking(2.0)
	assert data and data["models"][0]["id"] == "deepseek-v4-flash"
	assert path.is_file()
	obj = json.loads(path.read_text(encoding="utf-8"))
	assert obj["data"]["models"][0]["pricing"]["inputPerM"] == 0.22


def test_get_model_pricing_local_fallback(monkeypatch):
	monkeypatch.setattr(pricing, "_load_pricing_json", lambda timeout: None)
	assert pricing.get_model_pricing("deepseek", "deepseek-v4-flash") == {
		"input_miss": 0.2083,
		"input_hit": 0.00694,
		"output": 0.625,
	}
	assert pricing.get_model_pricing("deepseek", "deepseek-v4-pro") == {
		"input_miss": 0.625,
		"input_hit": 0.02083,
		"output": 1.875,
	}
	assert pricing.get_model_pricing("openai", "gpt-4o") == {
		"input_miss": 2.5,
		"input_hit": 1.25,
		"output": 10.0,
	}
	# 未知模型 → 该厂商最低档兜底
	assert pricing.get_model_pricing("openai", "gpt-99")["input_miss"] == 0.15


def test_estimate_usd_uses_user_model(monkeypatch):
	calls: list[tuple[str, str]] = []
	monkeypatch.setattr(
		pricing,
		"get_model_pricing",
		lambda provider, model, timeout=3.0: (
			calls.append((provider, model)) or PIN
		),
	)
	usage = _usage(prompt=1000, completion=500, hit=800, miss=200)
	usd = pricing.estimate_usd(provider="openai", model="gpt-4o", usage=usage)
	assert calls == [("openai", "gpt-4o")]
	# (800*0.2 + 200*2 + 500*8) / 1M
	assert usd == pytest.approx(0.00456)


def test_budget_tracker_uses_selected_model(monkeypatch):
	monkeypatch.setattr(
		pricing,
		"get_model_pricing",
		lambda provider, model, timeout=3.0: PIN,
	)
	# 设了 usd_limit → 走实时价路径（这里 PIN 顶替实时价）
	b = BudgetTracker(provider="openai", model="gpt-4o", usd_limit=0.1)
	b.add_usage(_usage(prompt=1000, completion=500))
	assert b.used_usd == pytest.approx(0.006)
	assert b.provider == "openai"
	assert b.model == "gpt-4o"


def test_no_usd_limit_uses_local_pricing_only(monkeypatch):
	# 未设上限 → 绝不触发网络拉价，只用本地兜底价
	def boom(*_a, **_k):
		raise AssertionError("network fetch should not run without usd_limit")

	monkeypatch.setattr(pricing, "_load_pricing_json", boom)
	b = BudgetTracker(provider="deepseek", model="deepseek-v4-flash")
	b.add_usage(_usage(prompt=1000, completion=500), ts=_OFFPEAK_TS)
	# 本地 flash 价：(1000*0.2083 + 500*0.625) / 1M
	assert b.used_usd == pytest.approx((1000 * 0.2083 + 500 * 0.625) / 1_000_000)


def test_price_fetch_disabled_via_env(monkeypatch):
	def boom(*_a, **_k):
		raise AssertionError("network fetch should be disabled by env")

	monkeypatch.setattr(pricing, "_load_pricing_json", boom)
	monkeypatch.setenv("XEYO_PRICE_FETCH", "0")
	assert pricing.get_model_pricing("deepseek", "deepseek-v4-flash") == {
		"input_miss": 0.2083,
		"input_hit": 0.00694,
		"output": 0.625,
	}
	assert pricing.get_model_pricing("openai", "gpt-4o") == {
		"input_miss": 2.5,
		"input_hit": 1.25,
		"output": 10.0,
	}


# ---------- 单元：BudgetTracker ----------


def test_add_usage_accumulates_tokens_and_usd():
	b = BudgetTracker(prices=PIN)
	b.add_usage(_usage(prompt=1000, completion=500))
	# (1000 * 2 + 500 * 8) / 1M = 0.006
	assert b.used_tokens == 1500
	assert b.used_usd == pytest.approx(0.006)
	assert b.last_usage_tokens == 1500
	assert b.last_usage_usd == pytest.approx(0.006)
	b.add_usage(_usage(prompt=1000, completion=500))
	assert b.used_tokens == 3000
	assert b.used_usd == pytest.approx(0.012)


def test_add_usage_prefers_vendor_usd():
	b = BudgetTracker(prices=PIN)
	b.add_usage(_usage(prompt=1000, completion=500, usd=0.0042))
	assert b.used_usd == pytest.approx(0.0042)


def test_cache_hit_cheaper():
	b = BudgetTracker(prices=PIN)
	b.add_usage(_usage(prompt=1000, completion=500, hit=800, miss=200))
	# (800 * 0.2 + 200 * 2 + 500 * 8) / 1M = 0.00456
	assert b.used_usd == pytest.approx(0.00456)
	assert b.last_usage_tokens == 1500


def test_add_usage_none_is_noop():
	b = BudgetTracker()
	b.add_usage(None)
	b.add_usage({})
	assert b.used_tokens == 0
	assert b.used_usd == 0.0


def test_over_budget_property():
	b = BudgetTracker(usd_limit=0.01, prices=PIN)
	assert not b.over_budget
	b.add_usage(_usage(prompt=500, completion=600))  # 0.0058
	assert not b.over_budget
	b.add_usage(_usage(prompt=500, completion=600))  # 0.0116
	assert b.over_budget
	# 无上限恒 False
	assert not BudgetTracker().over_budget


def test_reset_for_new_submit():
	b = BudgetTracker(usd_limit=0.02, max_turns=7, prices=PIN)
	b.add_usage(_usage(prompt=1000, completion=500))
	assert b.used_usd > 0 and b.used_tokens > 0
	b.reset_for_new_submit(usd_limit=0.05)
	assert b.used_usd == 0.0
	assert b.used_tokens == 0
	assert b.last_usage is None
	assert b.usd_limit == pytest.approx(0.05)
	assert b.max_turns == 7  # 未传 max_turns 时保持
	b.reset_for_new_submit(max_turns=3, usd_limit=None, model="gpt-4o")
	assert b.max_turns == 3
	assert b.usd_limit is None
	assert b.model == "gpt-4o"


def test_max_budget_usd_from_env(monkeypatch):
	assert max_budget_usd_from_env() is None
	monkeypatch.setenv("XEYO_MAX_BUDGET_USD", "0.01")
	assert max_budget_usd_from_env() == pytest.approx(0.01)
	monkeypatch.setenv("XEYO_MAX_BUDGET_USD", "oops")
	assert max_budget_usd_from_env() is None


# ---------- 集成：超 USD 上限急停 ----------


@pytest.mark.asyncio
async def test_submit_stops_on_budget_usd(pin_pricing):
	# 每轮 0.0058 USD；上限 0.01 → 第二轮超限
	eng = _engine(UsageToolModel(_usage()), max_budget_usd=0.01)
	events = []
	async for ev in eng.submit("go"):
		events.append(ev)

	usages = [e for e in events if isinstance(e, UsageEvent)]
	assert len(usages) == 2
	assert usages[0].usd == pytest.approx(0.0058)
	assert usages[1].used_usd == pytest.approx(0.0116)
	assert usages[1].usd_limit == pytest.approx(0.01)

	stopped = [e for e in events if isinstance(e, StoppedEvent)]
	assert stopped and stopped[-1].reason == "budget_usd"
	assert stopped[-1].budget_used_usd == pytest.approx(0.0116)
	assert stopped[-1].budget_limit_usd == pytest.approx(0.01)

	results = [e for e in events if isinstance(e, ResultEvent)]
	assert results and results[-1].subtype == "budget_usd"
	assert results[-1].stop_reason == "budget_usd"
	assert eng._session.budget.used_usd == pytest.approx(0.0116)
	assert eng._session.budget.provider == "deepseek"
	assert eng._session.budget.model == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_submit_without_limit_is_unchanged(pin_pricing):
	eng = _engine(UsageToolModel(_usage()))
	events = []
	async for ev in eng.submit("go"):
		events.append(ev)
	stopped = [e for e in events if isinstance(e, StoppedEvent)]
	# max_turns 默认 50 且模型永远调工具 → 以 max_turns 收尾，而非 budget_usd
	assert stopped and stopped[-1].reason == "max_turns"
	assert not any(e.reason == "budget_usd" for e in stopped)
	results = [e for e in events if isinstance(e, ResultEvent)]
	assert results and results[-1].stop_reason in ("end_turn", "max_turns")
	assert any(isinstance(e, UsageEvent) for e in events)


@pytest.mark.asyncio
async def test_env_budget_usd_is_picked_up(pin_pricing, monkeypatch):
	monkeypatch.setenv("XEYO_MAX_BUDGET_USD", "0.005")
	eng = _engine(UsageToolModel(_usage()))
	events = []
	async for ev in eng.submit("go"):
		events.append(ev)
	stopped = [e for e in events if isinstance(e, StoppedEvent)]
	assert stopped and stopped[-1].reason == "budget_usd"


@pytest.mark.asyncio
async def test_budget_resets_between_submits(pin_pricing):
	eng = _engine(UsageToolModel(_usage()), max_budget_usd=0.01)
	async for _ in eng.submit("go"):
		pass
	assert eng._session.budget.used_usd == pytest.approx(0.0116)
	# 下一轮 submit 重新计数，从 0 开始再超限
	events = []
	async for ev in eng.submit("go"):
		events.append(ev)
	stopped = [e for e in events if isinstance(e, StoppedEvent)]
	assert stopped and stopped[-1].reason == "budget_usd"
	assert eng._session.budget.used_usd == pytest.approx(0.0116)


# ---------- 分时段（高峰 / 低峰） ----------


def test_time_tier_peak_and_offpeak():
	assert pricing.time_tier("deepseek", _PEAK_TS) == "peak"
	assert pricing.time_tier("deepseek", _OFFPEAK_TS) == "offpeak"
	# 未知厂商不分时，恒 offpeak
	assert pricing.time_tier("openai", _PEAK_TS) == "offpeak"
	base = {"input_miss": 1.0, "input_hit": 0.1, "output": 2.0}
	assert pricing.effective_prices(
		"deepseek", "deepseek-v4-flash", _OFFPEAK_TS, base
	) == base
	assert pricing.effective_prices(
		"deepseek", "deepseek-v4-flash", _PEAK_TS, base
	) == {"input_miss": 2.0, "input_hit": 0.2, "output": 4.0}
	assert pricing.effective_prices("openai", "gpt-4o", _PEAK_TS, base) == base
	assert pricing.effective_prices("deepseek", "x", _PEAK_TS, None) is None


def test_estimate_usd_peak_is_double(monkeypatch):
	# 同一 usage：高峰 = 低峰 × 2（本地表对齐低峰档）
	monkeypatch.setattr(pricing, "_load_pricing_json", lambda timeout: None)
	usage = _usage(prompt=1000, completion=500)
	lo = pricing.estimate_usd(
		provider="deepseek",
		model="deepseek-v4-flash",
		usage=usage,
		local_only=True,
		ts=_OFFPEAK_TS,
	)
	hi = pricing.estimate_usd(
		provider="deepseek",
		model="deepseek-v4-flash",
		usage=usage,
		local_only=True,
		ts=_PEAK_TS,
	)
	assert lo == pytest.approx((1000 * 0.2083 + 500 * 0.625) / 1_000_000)
	assert hi == pytest.approx(lo * 2)


def test_time_tiers_env_override(monkeypatch):
	monkeypatch.setenv(
		"XEYO_TIME_TIERS_JSON",
		json.dumps(
			{
				"deepseek": {
					"windows": {"night": (("00:00", "08:00"),)},
					"multipliers": {"night": 3.0, "offpeak": 1.0},
				}
			}
		),
	)
	night = _datetime_ts(2026, 8, 16, 23, 0)  # UTC 23:00 = 北京 07:00，落在 00-08 窗口
	assert pricing.time_tier("deepseek", night) == "night"
	base = {"input_miss": 1.0, "input_hit": 0.1, "output": 2.0}
	assert pricing.effective_prices("deepseek", "x", night, base)["input_miss"] == pytest.approx(3.0)


def test_time_tier_disabled_models(monkeypatch):
	monkeypatch.setenv(
		"XEYO_TIME_TIERS_JSON",
		json.dumps(
			{
				"deepseek": {
					"windows": {"peak": (("09:00", "12:00"),)},
					"multipliers": {"peak": 2.0, "offpeak": 1.0},
					"disabled_models": ["deepseek-v4-pro"],
				}
			}
		),
	)
	assert pricing.time_tier("deepseek", _PEAK_TS, "deepseek-v4-pro") == "offpeak"
	assert pricing.time_tier("deepseek", _PEAK_TS, "deepseek-v4-flash") == "peak"


def test_budget_add_usage_time_aware(monkeypatch):
	monkeypatch.setattr(pricing, "_load_pricing_json", lambda timeout: None)
	b = BudgetTracker(provider="deepseek", model="deepseek-v4-flash", usd_limit=0.1)
	b.add_usage(_usage(prompt=1000, completion=500), ts=_PEAK_TS)
	peak_usd = b.used_usd
	b.reset_for_new_submit(usd_limit=0.1)
	b.add_usage(_usage(prompt=1000, completion=500), ts=_OFFPEAK_TS)
	assert peak_usd == pytest.approx(b.used_usd * 2)

if __name__ == "__main__":
	import pytest

	raise SystemExit(pytest.main([__file__, "-q"]))


# ---------- Turn / Tool Call 状态机 ----------


def test_budget_defaults_and_env(monkeypatch):
    from engine.budget import (
        DEFAULT_MAX_TOOL_CALLING,
        DEFAULT_MAX_TURNS,
        max_tool_calling_from_env,
        max_turns_from_env,
    )

    b = BudgetTracker()
    assert b.max_turns == DEFAULT_MAX_TURNS
    assert b.max_tool_calling == DEFAULT_MAX_TOOL_CALLING
    monkeypatch.setenv("XEYO_MAX_TURNS", "7")
    monkeypatch.setenv("XEYO_MAX_TOOL_CALLING", "9")
    assert max_turns_from_env() == 7
    assert max_tool_calling_from_env() == 9
    monkeypatch.setenv("XEYO_MAX_TURNS", "invalid")
    monkeypatch.setenv("XEYO_MAX_TOOL_CALLING", "0")
    assert max_turns_from_env() == DEFAULT_MAX_TURNS
    assert max_tool_calling_from_env() == DEFAULT_MAX_TOOL_CALLING


def test_budget_tool_call_boundary_does_not_create_turn():
    b = BudgetTracker(max_turns=10, max_tool_calling=16)
    assert b.prepare_next_turn() is True
    b.begin_turn()
    assert b.turn_count == 1
    assert all(b.begin_tool_call() for _ in range(16))
    assert b.current_turn_tool_calls == 16
    # 单轮顶满配额只排队一次性提醒，**不**开启共享收尾窗口（grace-cliff 修复）。
    assert b.grace_started is False
    assert b.tool_cap_streak == 0
    assert b.prepare_next_turn() is True
    assert b.turn_count == 1
    assert b.consume_runtime_notice() == "工具调用数已接近上限。"
    assert b.consume_runtime_notice() is None


def test_budget_tool_cap_streak_starts_grace_after_consecutive_turns():
    # 只有连续 MAX_TOOL_CAP_STREAK 轮顶满配额才进入工具收尾窗口。
    b = BudgetTracker(max_turns=10, max_tool_calling=16)
    b.begin_turn()
    for _ in range(16):
        assert b.begin_tool_call()
    assert b.grace_started is False
    assert b.tool_cap_streak == 0
    b.begin_turn()  # 第 2 轮也顶满 -> streak=1
    for _ in range(16):
        assert b.begin_tool_call()
    assert b.grace_started is False
    assert b.tool_cap_streak == 1
    b.begin_turn()  # 第 3 轮开始时 streak=2 -> 触发工具 grace
    assert b.grace_started is True
    assert b.grace_reason == "max_tool_calling"
    assert b.tool_cap_streak == 2


def test_budget_shared_grace_merges_notices_and_allows_three_turns():
    b = BudgetTracker(max_turns=1, max_tool_calling=16)
    b.begin_turn()
    for _ in range(16):
        assert b.begin_tool_call()
    assert b.prepare_next_turn() is True
    b.begin_turn()
    assert b.prepare_next_turn() is True
    b.begin_turn()
    assert b.prepare_next_turn() is True
    b.begin_turn()
    assert b.grace_turns_used == 3
    assert b.prepare_next_turn() is False
    # max_turns=1 时由 max_turns 先触发共享 grace，因此 reason 是 max_turns。
    assert b.hard_stop_reason == "max_turns"
    assert b.consume_runtime_notice() == (
        "回合数已接近上限。\n"
        "工具调用数已接近上限。"
    )


def test_budget_turn_notice_is_one_shot_and_reset_clears_state():
    b = BudgetTracker(max_turns=1, max_tool_calling=16)
    b.begin_turn()
    assert b.prepare_next_turn() is True
    assert b.consume_runtime_notice() == "回合数已接近上限。"
    b.begin_turn()
    assert b.prepare_next_turn() is True
    assert b.consume_runtime_notice() is None
    b.reset_for_new_submit()
    assert b.turn_count == 0
    assert b.grace_turns_used == 0
    assert b.grace_started is False
    assert b.hard_stop_reason is None
    assert b.consume_runtime_notice() is None


# ====== 旁路默认预算档（XEYO_BUDGET_DEFAULT_USD，2026-09-09 Phase 1）======


def test_budget_default_tier_resolution(monkeypatch):
    """旁路档解析:默认关=零变化;显式限额优先于默认档;非法值回落 None。"""
    from engine.budget import default_budget_usd_from_env, max_budget_usd_from_env

    # 1) 什么都不设 → None(历史行为逐字节一致)
    monkeypatch.delenv("XEYO_MAX_BUDGET_USD", raising=False)
    monkeypatch.delenv("XEYO_BUDGET_DEFAULT_USD", raising=False)
    assert max_budget_usd_from_env() is None
    assert default_budget_usd_from_env() is None

    # 2) 只开旁路档 → 生效
    monkeypatch.setenv("XEYO_BUDGET_DEFAULT_USD", "5")
    assert max_budget_usd_from_env() == 5.0

    # 3) 显式限额优先(0 也是合法显式值)
    monkeypatch.setenv("XEYO_MAX_BUDGET_USD", "2")
    assert max_budget_usd_from_env() == 2.0
    monkeypatch.setenv("XEYO_MAX_BUDGET_USD", "0")
    assert max_budget_usd_from_env() == 0.0

    # 4) 显式值非法 → 回落默认档
    monkeypatch.setenv("XEYO_MAX_BUDGET_USD", "invalid")
    assert max_budget_usd_from_env() == 5.0

    # 5) 旁路档非法/零/负 → None(fail-safe 不限额,与"默认关"同语义)
    monkeypatch.delenv("XEYO_MAX_BUDGET_USD", raising=False)
    monkeypatch.setenv("XEYO_BUDGET_DEFAULT_USD", "invalid")
    assert max_budget_usd_from_env() is None
    monkeypatch.setenv("XEYO_BUDGET_DEFAULT_USD", "0")
    assert max_budget_usd_from_env() is None
    monkeypatch.setenv("XEYO_BUDGET_DEFAULT_USD", "-3")
    assert max_budget_usd_from_env() is None


def test_budget_default_tier_enforces_over_budget(monkeypatch):
    """集成:旁路档生效 → used_usd 达档 → over_budget=True(既有停止链入口)。"""
    tracker = BudgetTracker()
    tracker.reset_for_new_submit(usd_limit=1.0, provider="test", prices=PIN)
    assert not tracker.over_budget
    # PIN: miss 2.0 USD/1M → 600k tokens = 1.2 USD > 1.0
    tracker.add_usage({"prompt_tokens": 600_000, "completion_tokens": 0})
    assert tracker.over_budget
    assert tracker.used_usd >= 1.0


# ====== Phase 2 验证（2026-09-09）：旁路档引擎级测试 + 水位事实播报 ======


class EndTurnModel:
	"""一轮文本后结束——正常短会话形态。"""

	async def stream(self, messages, tools, abort):
		abort.raise_if_aborted()
		yield ModelChunk(kind="text_delta", text="done")


@pytest.mark.asyncio
async def test_phase2_tier_cuts_runaway_loop(pin_pricing, monkeypatch):
	"""失控循环 + 仅旁路档(env,无显式限额)→ budget_usd 截停。

	无档位时同形态以 max_turns 收尾(test_submit_without_limit_is_unchanged);
	档位把终局从 256 turns 提前到费用上限。
	"""
	monkeypatch.setenv("XEYO_BUDGET_DEFAULT_USD", "0.008")
	eng = _engine(UsageToolModel(_usage()))
	events = []
	async for ev in eng.submit("go"):
		events.append(ev)
	stopped = [e for e in events if isinstance(e, StoppedEvent)]
	assert stopped and stopped[-1].reason == "budget_usd"
	assert stopped[-1].budget_limit_usd == pytest.approx(0.008)
	results = [e for e in events if isinstance(e, ResultEvent)]
	assert results and results[-1].stop_reason == "budget_usd"


@pytest.mark.asyncio
async def test_phase2_normal_session_not_killed_by_tier(pin_pricing, monkeypatch):
	"""正常短会话(一轮文本即止)在档位下完整跑完,无误伤。"""
	monkeypatch.setenv("XEYO_BUDGET_DEFAULT_USD", "0.0001")
	eng = _engine(EndTurnModel())
	events = []
	async for ev in eng.submit("go"):
		events.append(ev)
	stopped = [e for e in events if isinstance(e, StoppedEvent)]
	assert not any(e.reason == "budget_usd" for e in stopped)
	results = [e for e in events if isinstance(e, ResultEvent)]
	assert results and results[-1].stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_phase2_explicit_limit_beats_tier(pin_pricing, monkeypatch):
	"""显式限额(含 config)优先于旁路档——解析链优先级引擎级验证。"""
	monkeypatch.setenv("XEYO_BUDGET_DEFAULT_USD", "0.008")
	eng = _engine(UsageToolModel(_usage()), max_budget_usd=0.004)
	events = []
	async for ev in eng.submit("go"):
		events.append(ev)
	usage_events = [e for e in events if isinstance(e, UsageEvent)]
	assert usage_events and usage_events[0].usd_limit == pytest.approx(0.004)
	stopped = [e for e in events if isinstance(e, StoppedEvent)]
	assert stopped and stopped[-1].reason == "budget_usd"
	assert stopped[-1].budget_limit_usd == pytest.approx(0.004)


def test_phase2_usd_waterline_factual_notice():
	"""硬停前水位事实:80%/90% 各播一次,纯数字;未限额零播报。"""
	tracker = BudgetTracker()
	tracker.reset_for_new_submit(usd_limit=1.0, provider="test", prices=PIN)
	# <80%: 无
	tracker.add_usage({"prompt_tokens": 300_000, "completion_tokens": 0})  # 0.6 USD
	assert tracker.prepare_next_turn() is True
	assert tracker.consume_runtime_notice() is None
	# ≥80% <90%: 播 80% 一次
	tracker.add_usage({"prompt_tokens": 150_000, "completion_tokens": 0})  # +0.3 = 0.9
	tracker.prepare_next_turn()
	notice = tracker.consume_runtime_notice()
	assert notice is not None and "80%" in notice and "90%" not in notice
	assert tracker.consume_runtime_notice() is None  # 一次性
	# ≥90%: 播 90%
	tracker.add_usage({"prompt_tokens": 50_000, "completion_tokens": 0})  # +0.1 = 1.0
	tracker.prepare_next_turn()
	notice = tracker.consume_runtime_notice()
	assert notice is not None and "90%" in notice
	# 未限额: 零播报
	none_tracker = BudgetTracker()
	none_tracker.reset_for_new_submit(provider="test", prices=PIN)
	none_tracker.add_usage({"prompt_tokens": 900_000, "completion_tokens": 0})
	none_tracker.prepare_next_turn()
	assert none_tracker.consume_runtime_notice() is None
