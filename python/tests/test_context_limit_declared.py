"""用户登记的上下文窗口 = 后端唯一分母（面板与压缩上限同一口径）。

回归的三件事：
1. 厂商 usage 尾帧再回传别的窗口，也**不得**覆写用户登记值（否则压缩时机漂移）。
2. 用户没登记时，厂商元数据仍可兜底（不假阴、不把窗口变 None）。
3. 压缩上限的分母随登记窗口变：params.window_tokens 只是校准常量，填多少按多少压。
"""

from __future__ import annotations

from dataclasses import replace

from memory.runtime import params_for_window
from memory.simulator.params import load_params
from model.openai_compat import OpenAICompatClient
from server.session_pool import _apply_declared_context_limit


def _client(monkeypatch) -> OpenAICompatClient:
	monkeypatch.delenv("XEYO_CONTEXT_LIMIT_TOKENS", raising=False)
	return OpenAICompatClient(
		api_key="k", base_url="https://example.invalid", model="m"
	)


def test_declared_window_survives_vendor_metadata(monkeypatch) -> None:
	c = _client(monkeypatch)
	c.declare_context_limit(128_000)
	# 厂商尾帧说窗口是 1M：用户登记值不漂移。
	c._apply_usage_context_limit({"context_limit": 1_000_000})
	assert c.context_limit == 128_000
	assert c.context_limit_declared is True


def test_vendor_metadata_still_fills_when_undeclared(monkeypatch) -> None:
	c = _client(monkeypatch)
	assert c.context_limit is None and c.context_limit_declared is False
	c._apply_usage_context_limit({"context_window": 64_000})
	assert c.context_limit == 64_000
	# 兜底而来的值不算用户登记：下一帧厂商元数据仍可继续修正。
	assert c.context_limit_declared is False
	c._apply_usage_context_limit({"context_window": 0})
	assert c.context_limit == 64_000


def test_declare_ignores_non_positive(monkeypatch) -> None:
	c = _client(monkeypatch)
	c.declare_context_limit(0)
	c.declare_context_limit(-5)
	c.declare_context_limit(None)
	assert c.context_limit is None
	assert c.context_limit_declared is False


def test_env_window_counts_as_user_declared(monkeypatch) -> None:
	monkeypatch.setenv("XEYO_CONTEXT_LIMIT_TOKENS", "131072")
	c = OpenAICompatClient(api_key="k", base_url="https://example.invalid", model="m")
	assert c.context_limit == 131_072
	assert c.context_limit_declared is True
	c._apply_usage_context_limit({"context_limit": 8_000})
	assert c.context_limit == 131_072


class _Plain:
	context_limit: int | None = None


def test_session_pool_declares_or_noops(monkeypatch) -> None:
	c = _client(monkeypatch)
	_apply_declared_context_limit(c, 256_000)
	assert c.context_limit == 256_000 and c.context_limit_declared is True

	# 无 declare 接口的客户端（Fake 等）退回裸赋值。
	plain = _Plain()
	_apply_declared_context_limit(plain, 32_000)
	assert plain.context_limit == 32_000

	# 未登记 → 一律 no-op，绝不把已有窗口清空。
	for bad in (None, 0, -1):
		keep = _client(monkeypatch)
		keep.declare_context_limit(128_000)
		_apply_declared_context_limit(keep, bad)
		assert keep.context_limit == 128_000
		kept = _Plain()
		kept.context_limit = 99_000
		_apply_declared_context_limit(kept, bad)
		assert kept.context_limit == 99_000


def test_params_for_window_moves_the_denominator() -> None:
	base = load_params()
	assert params_for_window(base, None) is base
	assert params_for_window(base, 0) is base
	assert params_for_window(base, base.window_tokens) is base

	p = params_for_window(base, 64_000)
	assert p.window_tokens == 64_000
	assert p.l_hard_send == 64_000 - base.reserve_tokens
	assert p.l_max <= 64_000
	# 原对象不被改写（Params 冻结 + 逐轮各算各的）。
	assert base.window_tokens != 64_000
	assert isinstance(replace(base), type(base))


def test_pressure_ceiling_follows_the_user_window() -> None:
	"""同一 prompt 体量：登记窗口决定压不压（用户口径，非引擎常量）。"""
	from memory.runtime import should_force_compact_on_pressure

	assert should_force_compact_on_pressure(
		prompt_tokens=100_000, context_limit=120_000
	) is True
	assert should_force_compact_on_pressure(
		prompt_tokens=100_000, context_limit=1_000_000
	) is False
	# 窗口未知 → 不压（宁可不压，也不拿猜的窗口压）。
	assert should_force_compact_on_pressure(
		prompt_tokens=100_000, context_limit=None
	) is False
