"""General tool receipt boundaries: intent, mutation and verification differ."""
from synaptic.graph import build_graph
from synaptic.freshness import analyze
from synaptic.filestate import build_file_states


def use(uid, tool, **inputs):
    return {'role': 'assistant', 'content': [
        {'type': 'tool_use', 'id': uid, 'name': tool, 'input': inputs}]}


def result(uid, text='success', error=False):
    return {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': uid, 'content': text, 'is_error': error}]}


def test_a_write_or_different_test_does_not_resolve_failed_test():
    failed = [use('a', 'Bash', command='pytest app.py -k regression'),
              result('a', 'AssertionError: wrong value', True)]
    for later in (
        [use('b', 'Write', file_path='app.py', content='x=2'), result('b')],
        [use('b', 'Bash', command='pytest app.py -k another_test'), result('b', '1 passed')],
    ):
        state = analyze(build_graph(failed + later))
        assert 1 in state.unresolved_idx
        assert 1 not in state.resolved_idx
    state = analyze(build_graph(failed + [
        use('b', 'Bash', command='pytest app.py -k regression'), result('b', '1 passed')]))
    assert 1 in state.resolved_idx


def test_failed_reads_and_writes_do_not_commit_file_observations():
    rows = [use('r', 'Read', file_path='app.py'), result('r', 'x=1'),
            use('w', 'Write', file_path='app.py', content='x=2'),
            result('w', 'Permission denied: app.py', True)]
    state = build_file_states(build_graph(rows), rows)['app.py']
    assert not state.stale and not state.diff_summary
    rows = [use('r', 'Read', file_path='app.py'), result('r', 'Permission denied', True)]
    assert not build_file_states(build_graph(rows), rows)


def test_parallel_call_identities_and_receipts_are_independent():
    uses = use('a', 'Read', file_path='a.py')['content'] + use('b', 'Read', file_path='b.py')['content']
    rows = [{'role': 'assistant', 'content': uses}, result('a', 'a=1'), result('b', 'b=2')]
    graph = build_graph(rows, include_soft_edges=False)
    assert graph.by_use_id == {'a': 0, 'b': 0}
    assert graph.incoming(1, 'use') == graph.incoming(2, 'use') == (0,)
    assert graph.nodes[1].refs == ('a.py',)
    assert graph.nodes[2].refs == ('b.py',)
    states = build_file_states(graph, rows)
    assert set(states) == {'a.py', 'b.py'}
    assert states['a.py'].observed_hash != states['b.py'].observed_hash


def test_batched_results_keep_successful_observation_and_failed_error():
    rows = [use('a', 'Read', file_path='a.py'), use('b', 'Read', file_path='b.py'),
            {'role': 'user', 'content': result('a', 'a=1')['content'] +
             result('b', 'Permission denied: b.py', True)['content']}]
    graph = build_graph(rows, include_soft_edges=False)
    assert graph.nodes[2].is_error and graph.nodes[2].tool_use_id == 'b'
    assert graph.incoming(2, 'use') == (0, 1)
    assert set(build_file_states(graph, rows)) == {'a.py'}


def test_one_retry_cannot_resolve_a_message_with_two_failures():
    rows = [use('a', 'Bash', command='pytest a.py'),
            use('b', 'Bash', command='pytest b.py'),
            {'role': 'user', 'content': result('a', 'AssertionError: a', True)['content'] +
             result('b', 'AssertionError: b', True)['content']},
            use('retry', 'Bash', command='pytest a.py'), result('retry', '1 passed')]
    graph = build_graph(rows, include_soft_edges=False)
    assert graph.nodes[2].tool_use_id == ''
    assert set(graph.nodes[2].refs) == {'a.py', 'b.py'}
    assert graph.incoming(2, 'use') == (0, 1)
    assert 2 in analyze(graph).unresolved_idx


def test_error_card_reports_result_without_inventing_a_decision():
    from synaptic.assemble import render_decisions
    from synaptic.types import PruneCard
    row = render_decisions((PruneCard('failed', 'test failed', error_sig='AssertionError', nodes=(1,)),))[0][1]
    assert row.startswith('错误结果: test failed')
    assert '已排除' not in row
    assert 'node://1' in row


def test_nonjournal_append_does_not_repeat_an_earlier_increment():
    from synaptic.assemble import assemble, build_pins
    from synaptic.seeds import Seeds
    from synaptic.types import WscParams
    graph = build_graph([])
    params = WscParams(journal_layout=False, mode='append_only', append_budget_tokens=10000)
    previous = None
    heads = []
    for label in ('goal 1', 'goal 2', 'goal 3'):
        seeds = Seeds(goal=label, original_task=label)
        head, _, previous, _ = assemble(graph, seeds, build_pins(seeds), (), (), (), params, prev=previous)
        heads.append(head)
    assert heads[2].startswith(heads[1])
    assert heads[2].count('goal 2') == 1
