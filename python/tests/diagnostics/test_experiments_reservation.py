"""预留账本的铁律：一个共享上限、未知不释放为零、写不进去就不许再发付费请求。"""

from __future__ import annotations

import pytest

from diagnostics import store
from diagnostics.experiments.reservation import (
	Ledger,
	clear_ledger_errors,
	priced_cny,
	read_rows,
	state_of,
	summarize_rows,
	usage_is_reported,
	worst_case_cny,
)

PRICE = {"status": "ok", "currency": "CNY", "rates": {"hit": 0.02, "miss": 1.0, "out": 4.0}, "price_version": "v1"}


@pytest.fixture(autouse=True)
def _clean_ledger_state():
	clear_ledger_errors()
	yield
	clear_ledger_errors()


def _ledger(experiment_id: str = "exp_ledger", cap: float | None = 5.0) -> Ledger:
	ledger = Ledger(experiment_id, cap_cny=cap, price=PRICE, provider="deepseek", model="deepseek-v4-flash")
	assert ledger.open()["allowed"] is True
	return ledger


def test_worst_case_uses_the_pricier_input_class_when_class_is_unknown() -> None:
	row = worst_case_cny(PRICE, max_input_tokens=1_000_000, max_output_tokens=0, billing_class="unknown")
	assert row["amount_cny"] == pytest.approx(1.0)
	hit_only = worst_case_cny(PRICE, max_input_tokens=1_000_000, max_output_tokens=0, billing_class="hit")
	assert hit_only["amount_cny"] == pytest.approx(0.02)


def test_unknown_price_and_missing_bound_are_refused() -> None:
	assert worst_case_cny({"status": "unknown"}, max_input_tokens=10, max_output_tokens=1)["amount_cny"] is None
	assert worst_case_cny(PRICE, max_input_tokens=None, max_output_tokens=1)["reason"] == "missing_input_bound"
	assert worst_case_cny(PRICE, max_input_tokens=0, max_output_tokens=1)["reason"] == "missing_input_bound"


def test_cap_is_shared_by_arms_retries_and_repeats() -> None:
	"""每臂最坏情况 0.9 元（50 万输入按未命中档 + 10 万输出），上限 1.0 ⇒ 只容得下第一次。"""
	ledger = _ledger("exp_shared", cap=1.0)
	keys = ["t#A#r0", "t#B#r0", "t#A#r1", "t#B#r1"]
	gates = [
		ledger.reserve(key, max_input_tokens=500_000, max_output_tokens=100_000)
		for key in keys
	]
	assert gates[0]["allowed"] is True
	assert gates[0]["reserved_cny"] == pytest.approx(0.9)
	assert gates[1]["allowed"] is False
	assert gates[1]["reason"] == "budget_exhausted"
	assert gates[2]["allowed"] is False
	state = ledger.state()
	assert state["cap_cny"] == 1.0
	assert state["committed_cny"] == pytest.approx(0.9)
	assert state["remaining_cny"] == pytest.approx(0.1)


def test_reserve_requires_open_cap_and_known_price() -> None:
	no_cap = Ledger("exp_nocap", cap_cny=None, price=PRICE)
	no_cap.open()
	row = no_cap.reserve("k1", max_input_tokens=1000, max_output_tokens=10)
	assert row["allowed"] is False and row["reason"] == "cap_missing"

	bad_price = Ledger("exp_badprice", cap_cny=1.0, price={"status": "unknown"})
	bad_price.open()
	row = bad_price.reserve("k1", max_input_tokens=1000, max_output_tokens=10)
	assert row["allowed"] is False and row["reason"] == "unknown_price"


def test_write_failure_fails_closed_and_sticks() -> None:
	"""账本写不进去 ⇒ 停发新付费请求；这不是警告，是执行层闸门。"""
	store.ensure_dirs()
	path = store.reservations_path()
	path.parent.mkdir(parents=True, exist_ok=True)
	path.mkdir()  # 用目录占住账本路径：任何 append 都会失败
	ledger = Ledger("exp_broken", cap_cny=1.0, price=PRICE)
	opened = ledger.open()
	assert opened["allowed"] is False
	assert opened["reason"] == "ledger_unwritable"
	row = ledger.reserve("k1", max_input_tokens=1000, max_output_tokens=10)
	assert row["allowed"] is False and row["reason"] == "ledger_unwritable"
	assert state_of("exp_broken")["ledger_unwritable"] is True
	path.rmdir()


def test_usage_write_failure_after_reserve_still_blocks_further_requests(tmp_path, monkeypatch) -> None:
	"""已 open 后账本变不可写：预留必须被拒，钱不能被"悄悄花掉"。"""
	ledger = _ledger("exp_midfail", cap=5.0)
	assert ledger.reserve("k1", max_input_tokens=1000, max_output_tokens=10)["allowed"] is True
	monkeypatch.setattr(store, "append_jsonl", _boom)
	row = ledger.reserve("k2", max_input_tokens=1000, max_output_tokens=10)
	assert row["allowed"] is False
	assert row["reason"] == "ledger_unwritable"


def _boom(*_args, **_kwargs):
	raise OSError(28, "No space left on device")


def test_missing_usage_keeps_the_whole_reservation() -> None:
	ledger = _ledger("exp_unknown_usage", cap=5.0)
	reserved = ledger.reserve("r#A#1", max_input_tokens=200_000, max_output_tokens=20_000)
	assert reserved["allowed"] is True
	amount = reserved["reserved_cny"]
	settled = ledger.reconcile("r#A#1", None)
	assert settled["spent_cny"] == pytest.approx(amount)
	assert settled["released_cny"] == 0.0
	assert settled["usage_seen"] is False
	state = ledger.state()
	assert state["settled_cny"] == pytest.approx(amount)
	assert state["held_cny"] == 0.0
	assert state["unknown_usage_keys"] == ["r#A#1"]


def test_empty_dict_and_unrecognised_usage_are_not_zero_cost() -> None:
	assert usage_is_reported(None) is False
	assert usage_is_reported({}) is False
	assert usage_is_reported({"nonsense": 1}) is False
	assert usage_is_reported({"prompt_tokens": 0, "completion_tokens": 0}) is True


def test_reported_usage_releases_only_the_surplus() -> None:
	ledger = _ledger("exp_real_usage", cap=5.0)
	reserved = ledger.reserve("r#A#1", max_input_tokens=1_000_000, max_output_tokens=100_000)
	settled = ledger.reconcile(
		"r#A#1",
		{"prompt_cache_hit_tokens": 900_000, "prompt_cache_miss_tokens": 100_000, "completion_tokens": 10},
	)
	assert settled["usage_seen"] is True
	assert settled["spent_cny"] < reserved["reserved_cny"]
	assert settled["released_cny"] == pytest.approx(reserved["reserved_cny"] - settled["spent_cny"])
	state = ledger.state()
	assert state["remaining_cny"] > 3.0
	assert state["unknown_usage_keys"] == []


def test_cancel_or_timeout_keeps_max_reservation() -> None:
	"""取消/超时可能仍在计费：即使拿到了部分 usage 也按最大预留入账。"""
	ledger = _ledger("exp_cancel", cap=5.0)
	reserved = ledger.reserve("r#A#1", max_input_tokens=200_000, max_output_tokens=20_000)
	got = ledger.reconcile(
		"r#A#1",
		{"prompt_cache_hit_tokens": 10, "prompt_cache_miss_tokens": 10, "completion_tokens": 1},
		outcome="cancelled",
	)
	assert got["spent_cny"] == pytest.approx(reserved["reserved_cny"])
	assert got["released_cny"] == 0.0
	assert got["usage_reported"] is True
	assert got["usage_seen"] is False
	abandoned = ledger.abandon("r#B#1", reason="timeout")  # 从没预留过的键：只记实际未知花销
	assert abandoned["spent_cny"] == 0.0
	assert abandoned["reason"] == "settled_without_reservation"


def test_restart_does_not_blindly_resent_unknown_requests() -> None:
	first = _ledger("exp_restart", cap=5.0)
	assert first.reserve("r#A#1", max_input_tokens=1000, max_output_tokens=10)["allowed"] is True
	# 进程重启：新句柄读的是同一份落盘账本
	restarted = Ledger("exp_restart", cap_cny=5.0, price=PRICE)
	gate = restarted.may_send("r#A#1")
	assert gate["allowed"] is False
	assert gate["reason"] == "outcome_unknown"
	row = restarted.reserve("r#A#1", max_input_tokens=1000, max_output_tokens=10)
	assert row["allowed"] is False
	state = restarted.state()
	assert state["unknown_outcome"] == ["r#A#1"]
	assert state["committed_cny"] > 0
	# 结算之后同一键可以重发（这是"已知的重试"，不是未知结局）
	restarted.reconcile("r#A#1", {"prompt_tokens": 10, "completion_tokens": 1})
	assert restarted.may_send("r#A#1")["allowed"] is True


def test_settling_over_reservation_marks_must_stop() -> None:
	ledger = _ledger("exp_over", cap=0.01)
	reserved = ledger.reserve("r#A#1", max_input_tokens=1_000, max_output_tokens=10)
	assert reserved["allowed"] is True
	ledger.reconcile(
		"r#A#1",
		{"prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 1_000_000, "completion_tokens": 100_000},
	)
	state = ledger.state()
	assert state["committed_cny"] > state["cap_cny"]
	assert state["must_stop"] is True
	again = ledger.reserve("r#A#2", max_input_tokens=1000, max_output_tokens=10)
	assert again["allowed"] is False and again["reason"] == "budget_exhausted"


def test_max_requests_gate_is_experiment_wide() -> None:
	ledger = Ledger("exp_reqcap", cap_cny=100.0, price=PRICE, max_requests=2)
	ledger.open()
	assert ledger.reserve("a#1", max_input_tokens=100, max_output_tokens=1)["allowed"] is True
	assert ledger.reserve("b#1", max_input_tokens=100, max_output_tokens=1)["allowed"] is True
	row = ledger.reserve("a#2", max_input_tokens=100, max_output_tokens=1)
	assert row["allowed"] is False and row["reason"] == "max_requests_reached"


def test_cap_is_immutable_once_recorded() -> None:
	ledger = _ledger("exp_capfix", cap=2.0)
	other = Ledger("exp_capfix", cap_cny=99.0, price=PRICE)
	row = other.open()
	assert row["allowed"] is False and row["reason"] == "cap_immutable"
	assert Ledger("exp_capfix", cap_cny=2.0, price=PRICE).open()["allowed"] is True


def test_priced_cny_prefers_provider_reported_amount() -> None:
	direct = priced_cny({"prompt_tokens": 100, "completion_tokens": 10, "cost_cny": 3.5}, provider="deepseek", model="m")
	assert direct["cny"] == pytest.approx(3.5)
	assert direct["source"] == "api"
	estimated = priced_cny({"prompt_tokens": 100, "completion_tokens": 10}, provider="deepseek", model="deepseek-v4-flash")
	assert estimated["cny"] > 0
	assert estimated["source"] == "estimate"


def test_rows_are_scoped_per_experiment_and_tolerant_of_garbage() -> None:
	ledger = _ledger("exp_scope_a", cap=5.0)
	ledger.reserve("a#1", max_input_tokens=1000, max_output_tokens=10)
	_b = _ledger("exp_scope_b", cap=5.0)
	assert len(read_rows("exp_scope_a")) < len(read_rows())
	assert state_of("exp_scope_b")["committed_cny"] == 0.0
	store.reservations_path().write_text(
		store.reservations_path().read_text(encoding="utf-8") + "not-json\n[1,2]\n",
		encoding="utf-8",
	)
	assert summarize_rows(read_rows())["requests_settled"] == 0


def test_reconcile_without_reservation_is_still_booked() -> None:
	"""没预留就发生的调用（例如崩溃后重连）必须入账，不得静默丢失。"""
	ledger = _ledger("exp_unbooked", cap=5.0)
	row = ledger.reconcile(
		"never#reserved#1",
		{"prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 100_000, "completion_tokens": 1_000},
	)
	assert row["reason"] == "settled_without_reservation"
	state = ledger.state()
	assert state["settled_cny"] > 0
	assert state["committed_cny"] > 0
