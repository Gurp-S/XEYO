"""Public entrances, not hidden storage, prove PIN evidence restoration."""
from memory.wsc_projection import production_params
from synaptic.project import project
from tests.wsc._fixtures import msg_user, msg_asst_use, msg_tool
from tests.wsc.test_cold_read_view import FileReadTool, _read, _strip_line_numbers
from tests.wsc._recovery_contract import parse_read_refs


def project_case(history, view, **kwargs):
    return project(history, region_end=len(history), params=production_params(), view_path=view, **kwargs)


def read_origins(projected, view, cwd):
    return [_strip_line_numbers(_read(FileReadTool(cwd=str(cwd)), view, offset=ref.offset, limit=ref.limit))
            for ref in parse_read_refs(projected.text)]


def test_long_todo_input_has_published_full_origin(tmp_path):
    history = [msg_user('Build and verify'), msg_asst_use('t', 'TodoWrite', {'todos': [
        {'content': 'Build', 'status': 'pending', 'activeForm': 'Building ' + 'detail ' * 100, 'output': 'artifact/check.json'}]})]
    view = tmp_path / '.xeyo_offload' / 'wsc' / 'cold.txt'
    after = project_case(history, view)
    assert after.graph.node(1).tokens > 48
    assert any(after.graph.node(1).text in text for text in read_origins(after, view, tmp_path))


def test_long_error_has_published_full_origin(tmp_path):
    raw = 'PermissionError: denied\n' + 'trace detail\n' * 120 + 'request_id=long-17'
    history = [msg_user('Investigate'), msg_asst_use('a', 'Read', {'path': 'src/a.py'}),
               msg_tool('a', 'Read', raw, is_error=True)]
    view = tmp_path / '.xeyo_offload' / 'wsc' / 'cold.txt'
    after = project_case(history, view)
    assert any(raw in text for text in read_origins(after, view, tmp_path))


def test_grouped_error_origin_recovers_all_instances(tmp_path):
    history = [msg_user('Investigate failures')]
    for n in range(3):
        history += [msg_asst_use(f'r{n}', 'Read', {'path': f'src/a{n}.py'}),
            msg_tool(f'r{n}', 'Read', f'PermissionError: denied\nrequest_id=case-{n}', is_error=True)]
    view = tmp_path / '.xeyo_offload' / 'wsc' / 'cold.txt'
    after = project_case(history, view)
    assert len(after.seeds.unresolved_errors) == 1
    texts = read_origins(after, view, tmp_path)
    assert all(any(f'request_id=case-{n}' in text for text in texts) for n in range(3))
    # The same published origin must work when interpreted as expand, too.
    group = (2, 4)
    from synaptic.coldstore import node_group_handle
    assert len(after.cold.expand(node_group_handle(group))) == 2
    assert 'request_id=case-2' in texts[0]


def test_new_group_keeps_old_reads_and_head_bytes(tmp_path):
    history = [msg_user('Investigate failures')]
    for n in range(2):
        history += [msg_asst_use(f'r{n}', 'Read', {'path': f'src/a{n}.py'}),
            msg_tool(f'r{n}', 'Read', f'PermissionError: denied\nrequest_id=case-{n}', is_error=True)]
    view = tmp_path / '.xeyo_offload' / 'wsc' / 'cold.txt'
    before = project_case(history, view)
    initial_refs = parse_read_refs(before.text)
    original_results = read_origins(before, view, tmp_path)
    history += [msg_asst_use('r2', 'Read', {'path': 'src/a2.py'}),
        msg_tool('r2', 'Read', 'PermissionError: denied\nrequest_id=case-2', is_error=True)]
    after = project_case(history, view, prev=before.state, cold=before.cold)
    assert after.text.startswith(before.text)
    recovered = [_strip_line_numbers(_read(FileReadTool(cwd=str(tmp_path)), view, offset=ref.offset, limit=ref.limit)) for ref in initial_refs]
    assert recovered == original_results
    assert 'request_id=case-0' in '\n'.join(read_origins(after, view, tmp_path))
