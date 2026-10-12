from copy import deepcopy

from evals.wsc_cache_audit import audit, compare, usage_sample


def test_append_is_not_raw_json_prefix_and_envelope_change_is_separate():
    original = {"model": "m", "tools": [{"name": "Read"}],
                "messages": [{"role": "user", "content": "secret source"}]}
    next_body = deepcopy(original)
    next_body["messages"].append({"role": "assistant", "content": "answer"})
    assert compare(original, next_body)["message_relation"] == "append"
    next_body["tools"] = [{"name": "HandoffSource"}]
    result = compare(original, next_body)
    assert result["common_exact_messages"] == 1
    assert result["changed_envelope_fields"] == ["tools"]
    assert "secret source" not in str(result)


def test_rewrite_and_removal_are_observed_without_claiming_cache_invalidation():
    before = {"messages": [{"content": "a"}, {"content": "b"}]}
    assert compare(before, {"messages": [{"content": "a"}]})["message_relation"] == "rewrite_or_remove"
    assert compare(before, {"messages": [{"content": "changed"}]})["common_exact_messages"] == 0


def test_missing_usage_and_invalid_counts_are_unknown():
    assert usage_sample({"prompt_tokens": 10}) is None
    assert usage_sample({"prompt_tokens": 10, "prompt_cache_hit_tokens": 11}) is None
    assert usage_sample({"prompt_tokens": 10, "prompt_tokens_details": {"cached_tokens": 0}})["hit_rate"] == 0


def test_weighted_usage_separates_handoff_continuation_and_does_not_mutate_captures():
    report = {"requests": []}
    for name, tokens, cached in [("HandoffSource", 1000, 900), ("HandoffSource", 100, 0), ("Read", 100, 10)]:
        report["requests"].append({"wire": {"request": {"tools": [{"name": name}], "messages": []},
            "response": {"usage": {"prompt_tokens": tokens, "prompt_cache_hit_tokens": cached}}}})
    report["requests"].append({"wire": {"request": {"tools": [{"name": "Read"}], "messages": []}, "response": {}}})
    before = deepcopy(report)
    result = audit(report)
    assert result["totals"]["all"]["observed_token_weighted_hit_rate"] == 910 / 1200
    assert result["totals"]["handoff"]["observed_token_weighted_hit_rate"] == 900 / 1100
    assert result["totals"]["continuation"]["usage_observed_calls"] == 1
    assert result["totals"]["continuation"]["calls"] == 2
    assert report == before
