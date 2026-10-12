from copy import deepcopy

from evals.wsc_live_smoke_audit import usage_summary


def test_real_usage_is_token_weighted_deduplicates_attempts_and_does_not_mutate_source():
    rows = [{"request_id": "a", "attempt": 1, "ts": 1, "provider": "p", "model": "m", "key_id": "k",
             "prompt_tokens": 1000, "cache_hit": 900},
            {"request_id": "b", "attempt": 1, "ts": 100, "provider": "p", "model": "m", "key_id": "k",
             "prompt_tokens": 100, "cache_hit": 0}]
    rows.append(deepcopy(rows[-1]))
    before = deepcopy(rows)
    result = usage_summary(rows)
    assert result["logged_calls"] == 2 and result["duplicate_request_attempt_rows"] == 1
    assert result["token_weighted_cache_hit_rate"] == 900 / 1100
    assert result["active_same_model_key_calls"] == 1
    assert result["active_same_model_key_hit_rate"] == 0
    assert rows == before


def test_missing_usage_and_idle_or_model_changes_are_not_active_cache_samples():
    rows = [{"ts": 1, "model": "m", "prompt_tokens": 100, "cache_hit": 50},
            {"ts": 100, "model": "changed", "prompt_tokens": 100, "cache_hit": 90},
            {"ts": 5000, "model": "changed", "prompt_tokens": 100, "cache_hit": 99},
            {"ts": 5100, "model": "changed", "prompt_tokens": 100}]
    result = usage_summary(rows)
    assert result["valid_cache_usage_calls"] == 3
    assert result["active_same_model_key_calls"] == 0
