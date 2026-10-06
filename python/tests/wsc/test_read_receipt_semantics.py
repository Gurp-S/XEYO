"""Diagnostic file contents cannot override a successful native Read receipt."""
import pytest

from synaptic.graph import build_graph, result_is_error
from synaptic.filestate import build_file_states
from synaptic.textutil import content_hash


def use(uid, tool, **inputs):
    return {'role': 'assistant', 'content': [
        {'type': 'tool_use', 'id': uid, 'name': tool, 'input': inputs}]}


def result(uid, text, flag=False):
    block = {'type': 'tool_result', 'tool_use_id': uid, 'content': text}
    if flag is not None:
        block['is_error'] = flag
    return {'role': 'user', 'content': [block]}


@pytest.mark.parametrize('tool', ['Read', 'NotebookRead'])
def test_diagnostic_read_preserves_valid_file_observation(tool):
    text = '1\u2192Traceback (most recent call last):\n2\u2192Permission denied: historical diagnostic'
    messages = [use('r', tool, file_path='error.log'), result('r', text)]
    graph = build_graph(messages)
    assert not graph.nodes[1].is_error and not graph.nodes[1].error_sig
    state = build_file_states(graph, messages)['error.log']
    assert state.observed_hash == content_hash(text)
    assert state.read_ranges == ((1, 2),)
    assert not state.related_errors


@pytest.mark.parametrize('flag', [True, None])
def test_failed_or_ambiguous_read_stays_failed(flag):
    messages = [use('r', 'Read', file_path='error.log'), result('r', 'Permission denied', flag)]
    graph = build_graph(messages)
    assert graph.nodes[1].is_error
    assert not build_file_states(graph, messages)


def test_command_failure_still_promotes_false_transport_verdict():
    messages = [use('b', 'Bash', command='python broken.py'),
                result('b', 'Traceback (most recent call last):\nRuntimeError: broken')]
    assert build_graph(messages).nodes[1].is_error


def test_batched_read_and_failed_command_are_independent():
    messages = [use('r', 'Read', file_path='error.log'), use('b', 'Bash', command='python broken.py'),
                {'role': 'user', 'content': result('r', '1\u2192Permission denied: old')['content'] +
                 result('b', 'Traceback (most recent call last):\nRuntimeError: current')['content']}]
    graph = build_graph(messages)
    assert graph.nodes[2].is_error and graph.nodes[2].tool_use_id == 'b'
    assert graph.nodes[2].tool_name == 'Bash'
    assert 'current' in graph.nodes[2].error_sig
    assert set(build_file_states(graph, messages)) == {'error.log'}


def test_default_and_nonboolean_receipts_remain_conservative():
    for flag in (0, 'false', None):
        block = {'content': 'Permission denied', 'is_error': flag}
        assert result_is_error(block, tool_name='Read')
    assert result_is_error({'content': 'Permission denied', 'is_error': False})


@pytest.mark.parametrize('tool,command,text', [
    ('Bash', 'Get-Content python/scripts/v61_evidence_gate.py -TotalCount 80',
     'STACK = (\n    "Traceback (most recent call last):\\n"\n    \'KeyError: theta\\n"\'\n)'),
    ('Bash', 'cat src/app.py', 'raise RuntimeError("assertion failed: permission denied")'),
    ('Grep', '', '71:\t工具输出经常引用含 Permission denied 的源码\n80:# 显式 is_error: false'),
])
def test_read_semantic_receipts_do_not_promote_false_verdict(tool, command, text):
    """读/搜索命令的输出是文件内容或命中行，不是本次调用的运行结果。

    实测现场（sess_musrbw08_n9tly2）：Get-Content 读 v61_evidence_gate.py
    （正文含夹具串 Traceback）、Grep 搜到含 Permission denied 的源码注释，
    两者的显式 is_error=False 都被正文标记升格成了失败。
    """
    inputs = {'command': command} if command else {'pattern': 'permission'}
    messages = [use('r', tool, **inputs), result('r', text)]
    graph = build_graph(messages)
    assert not graph.nodes[1].is_error
    assert not graph.nodes[1].error_sig


def test_piped_or_written_command_keeps_text_promotion():
    """管道/重定向不是纯内容读：退出码可被洗掉时文本标记是唯一失败证据。"""
    messages = [use('b', 'Bash', command='cat src/app.py | head -5'),
                result('b', 'Permission denied')]
    assert build_graph(messages).nodes[1].is_error
