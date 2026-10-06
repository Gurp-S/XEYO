"""Offline cache estimates must distinguish generated output from new input."""
import copy

from evals.wsc_extension_economics_ab import canonical_projection
from evals.wsc_prefix_accounting import estimate, leading_assistant_outputs


def test_response_prefix_can_reuse_reasoning_and_tool_arguments_without_tool_result():
    prior = [{'role': 'user', 'content': 'inspect a.py'}]
    response = {'role': 'assistant', 'content': [
        {'type': 'reasoning', 'text': 'inspect current implementation'},
        {'type': 'tool_use', 'id': 'r1', 'name': 'Read', 'input': {'file_path': 'a.py'}},
    ]}
    result = {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'r1', 'content': 'x' * 400}]}
    history = prior + [response, result]
    before = copy.deepcopy(history)
    generated = leading_assistant_outputs(history, len(prior))
    assert generated == [response]
    canon = lambda value: canonical_projection(value, 'openai')
    measured = estimate(canon(history), previous=canon(prior), response_prefix=canon(prior + generated))
    assert 0 < measured.input_hit < measured.response_hit < measured.tokens
    assert measured.response_miss > 0
    assert history == before


def test_changed_earlier_fact_invalidates_both_prefix_scenarios():
    previous = 'old constraint ' + 'a' * 200
    current = 'new constraint ' + 'a' * 200
    measured = estimate(current, previous=previous, response_prefix=previous + 'generated answer')
    assert measured.input_hit == measured.response_hit == 0


def test_first_request_cannot_claim_a_cached_response():
    measured = estimate('a' * 100, previous=None, response_prefix='a' * 100)
    assert measured.input_hit == measured.response_hit == 0
    assert measured.input_miss == measured.response_miss == measured.tokens


def test_external_input_stops_generated_prefix_and_unknown_output_keeps_baseline():
    messages = [{'role': 'assistant', 'content': 'answer'}, {'role': 'system', 'content': 'state'},
                {'role': 'assistant', 'content': 'later answer'}]
    assert leading_assistant_outputs(messages, 0) == messages[:1]
    assert leading_assistant_outputs(messages, -1) == []
    assert leading_assistant_outputs(messages, 4) == []
    measured = estimate('prefix extra', previous='prefix')
    assert measured.input_hit == measured.response_hit
    assert measured.input_hit + measured.input_miss == measured.tokens
