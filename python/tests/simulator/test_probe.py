"""Live probe is skipped unless --live and DEEPSEEK_API_KEY."""

from __future__ import annotations

import os

import pytest

from memory.simulator.metrics import HitRecord, bias_flags, cache_errors
from memory.simulator.probe import have_api_key, messages_from_x


def test_messages_from_x():
	msgs = messages_from_x("hello")
	assert msgs[0]["role"] == "user"
	assert msgs[0]["content"] == "hello"


def test_cache_error_metrics():
	rows = [
		HitRecord(
			request_id="1",
			provider="deepseek",
			cache_age=0.0,
			action="keep",
			LCP=64,
			predicted_hit=100,
			observed_hit=90,
			prompt_tokens=200,
			output_tokens=1,
			predicted_cost=0.01,
			actual_cost=0.012,
			context_length=200,
		)
	]
	err = cache_errors(rows)
	assert err["n"] == 1
	assert abs(err["MAE"] - 10) < 1e-9
	assert err["Bias"] == 10
	assert bias_flags(rows) == []


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_keep_probe():
	# 需显式开启 XEYO_RUN_LIVE_PROBE=1，否则基线（含 smoke 环境，其有
	# XEYO_MODEL_API_KEY 会被 have_api_key() 误判）不会打到真实 API。
	if os.environ.get("XEYO_RUN_LIVE_PROBE") != "1":
		pytest.skip("live probe disabled; set XEYO_RUN_LIVE_PROBE=1")
	if not have_api_key():
		pytest.skip("no DEEPSEEK_API_KEY")
	from memory.simulator.probe import probe_state_actions
	from memory.simulator.scenarios import list_scenarios

	sc = next(s for s in list_scenarios(smoke=True) if s.id == "empty_m")
	rows = await probe_state_actions(sc.state(), sc.cache(), actions=("keep",))
	assert rows
	assert rows[0].prompt_tokens >= 0
