from evals.wsc_marginal_economics import compare


def test_common_new_tool_result_is_not_charged_as_fold_transition():
    previous = 'stable prefix old history'
    novel_result = 'new tool result' * 1000
    keep = previous + novel_result
    fold = 'stable prefix summary' + novel_result
    baseline = compare(keep, fold, previous=previous, response_prefix=None)
    longer = compare(keep + novel_result, fold + novel_result, previous=previous, response_prefix=None)
    assert baseline.saved_tokens == longer.saved_tokens
    assert abs(baseline.transition_tokens - longer.transition_tokens) <= 1
    assert baseline.transition_tokens < 20


def test_each_cache_scenario_is_paired_before_taking_worst_incremental_miss():
    previous = 'input'
    response = previous + 'generated output' * 100
    keep = response + 'new external result'
    fold = 'summary'
    pair = compare(keep, fold, previous=previous, response_prefix=response)
    assert pair.input_extra_miss < 0
    assert pair.transition_tokens == max(0, pair.input_extra_miss, pair.response_extra_miss)
    assert pair.saved_tokens > 0


def test_identical_candidates_have_no_incremental_transition_and_no_savings():
    pair = compare('same request', 'same request', previous='same', response_prefix='same response')
    assert pair.transition_tokens == pair.saved_tokens == 0
    assert pair.account()['incremental_miss_input'] == 0
