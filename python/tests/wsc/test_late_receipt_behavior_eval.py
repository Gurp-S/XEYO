import json


def test_eval_captures_vendor_usage_and_answer_before_acceptance(monkeypatch, tmp_path):
    from evals.wsc_late_receipt_behavior import run
    answer = json.dumps({'left': 137, 'right': 211, 'difference': 74,
                         'old_goal_status': 'closed', 'evidence_call_ids': ['left-call', 'right-call']})
    calls = []
    def chat(*args, **kwargs):
        assert kwargs['capture_wire'] is True and kwargs['retries'] == 0
        calls.append(kwargs)
        return {'request': {}, 'response': {'choices': [{'message': {'content': answer}}],
                                            'usage': {'prompt_tokens': 100, 'completion_tokens': 40,
                                                      'prompt_cache_hit_tokens': 80}}}
    monkeypatch.setattr('evals.client.chat', chat)
    key = tmp_path / 'fixture-key'
    key.write_text('sk-' + 'a' * 20)
    result = run(tmp_path / 'out', key, execute=True)
    assert len(calls) == 2 and all(arm['acceptance']['passed'] for arm in result['arms'])
    assert all(entry['usage_observed'] for entry in result['budget_entries'])
    assert (tmp_path / 'out' / 'late_candidate-response.json').exists()
