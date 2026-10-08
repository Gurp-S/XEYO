import pytest

from evals.wsc_drift_budget import Budget


def test_request_size_rejected_before_any_call():
    budget = Budget()
    with pytest.raises(ValueError, match="budget_exceeded"):
        budget.admit({"messages": "x" * 260000}, 700)
    assert not budget.entries and budget.spent_upper == 0


def test_unknown_receipt_keeps_reserved_cost_and_stops_total():
    budget = Budget(total=0.025)
    entry = budget.admit({}, 700)
    reserved = budget.spent_upper
    budget.settle(entry, {})
    assert budget.spent_upper == reserved
    with pytest.raises(ValueError, match="budget_exceeded"):
        budget.admit({}, 700)


def test_observed_usage_includes_all_completion_tokens_once():
    budget = Budget()
    entry = budget.admit({}, 700)
    budget.settle(entry, {"prompt_tokens": 100, "completion_tokens": 40, "prompt_cache_hit_tokens": 20,
                          "completion_tokens_details": {"reasoning_tokens": 10}})
    assert budget.spent_upper == pytest.approx((80*2+20*0.04+40*8)/1000000)
    assert entry["off_peak_price_cny"] == pytest.approx(budget.spent_upper/2)
