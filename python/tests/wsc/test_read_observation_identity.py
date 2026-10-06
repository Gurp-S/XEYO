"""读观测的身份 = 这次调用真正读的文件，不是正文/命令里提到的文件名。

现场（sess_musrbw08_n9tly2）：一条 ``Get-Content docs\\wsc2-handoff-2026-09-23.md``
的结果正文里提到 compact.py / runtime.py 等文件名，旧实现 fallback 到结果正文的
``refs``（提及路径），把 5 个"被提到"的裸名记成了 ``read: 未读`` 读观测；
而命令真正的目标文件反而没进表。
"""

from __future__ import annotations

from synaptic.filestate import build_file_states
from synaptic.graph import build_graph


def use(uid, tool, **inputs):
    return {'role': 'assistant', 'content': [
        {'type': 'tool_use', 'id': uid, 'name': tool, 'input': inputs}]}


def result(uid, text, flag=False):
    block = {'type': 'tool_result', 'tool_use_id': uid, 'content': text}
    if flag is not None:
        block['is_error'] = flag
    return {'role': 'user', 'content': [block]}


def test_command_read_records_target_not_mentioned_names():
    doc = 'handoff notes: see compact.py and runtime.py for details'
    messages = [use('b', 'Bash', command='Get-Content docs/handoff.md'), result('b', doc)]
    states = build_file_states(build_graph(messages), messages)
    assert 'docs/handoff.md' in states, '命令真正读的文件没进状态表'
    assert not any('compact.py' in key for key in states), '正文提及的文件被当成了读观测'
    assert not any('runtime.py' in key for key in states), '正文提及的文件被当成了读观测'


def test_multi_file_read_command_records_no_observation():
    messages = [use('b', 'Bash', command='Get-Content a.md b.md'), result('b', 'x')]
    states = build_file_states(build_graph(messages), messages)
    assert not states, '多文件读命令的目标不唯一，不应产生读观测'


def test_native_read_keeps_precise_observation():
    messages = [use('r', 'Read', file_path='src/app.py', offset=1, limit=40),
                result('r', 'line one\nline two')]
    states = build_file_states(build_graph(messages), messages)
    assert 'src/app.py' in states
    state = states['src/app.py']
    assert state.read_ranges == ((1, 2),)


def test_relative_key_merges_into_unique_full_key():
    """同一文件两条记录必须归并：相对短键并入唯一后缀匹配的完整键。

    现场：``docs/wsc2-handoff-2026-09-23.md``（Bash 相对形态）与
    ``/lea/XenYon code/docs/wsc2-handoff-2026-09-23.md``（Read 完整形态）并存。
    """
    messages = [
        use('r', 'Read', file_path='D:/ws/python/memory/l5.py', offset=1, limit=40),
        result('r', 'alpha\nbeta'),
        use('b', 'Bash', command='Get-Content python/memory/l5.py'),
        result('b', 'alpha'),
    ]
    states = build_file_states(build_graph(messages), messages)
    assert list(states) == ['/ws/python/memory/l5.py'], f'双条目未归并: {list(states)}'
    assert states['/ws/python/memory/l5.py'].read_ranges == ((1, 2),)


def test_ambiguous_suffix_keeps_both_keys():
    """两个完整键都以同一短键结尾（同名文件不同目录）⇒ 不许猜，保持原样。"""
    messages = [
        use('r1', 'Read', file_path='D:/x/a/conf.py', offset=1, limit=5), result('r1', 'p'),
        use('r2', 'Read', file_path='D:/y/b/conf.py', offset=1, limit=5), result('r2', 'q'),
        use('b', 'Bash', command='Get-Content conf.py'), result('b', 'p'),
    ]
    states = build_file_states(build_graph(messages), messages)
    assert len(states) == 3, f'歧义后缀被错误归并: {list(states)}'
    assert 'conf.py' in states
