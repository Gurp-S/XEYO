"""Coverage follows published physical ranges and exact bound members."""
from types import SimpleNamespace

from synaptic.budget import rendered_request_nodes
from synaptic.handles import HandleRenderer
from synaptic.metrics import exposed_handles


def test_read_alias_cannot_hide_a_request_node():
    renderer = HandleRenderer(style='read', path='cold.txt', node_ranges={'node://7': (4, 6)},
                              handle_nodes={'node://7': (7,), 'branch://B1': (7,)})
    expression = renderer.expression('node://7')
    assert renderer.extract(expression) == ('branch://B1',)
    assert rendered_request_nodes([('req:7', expression)], handles=renderer) == {7}


def test_read_span_counts_all_complete_bodies_it_actually_returns():
    renderer = HandleRenderer(style='read', path='cold.txt',
        node_ranges={'node://7': (4, 6), 'node://8': (8, 9), 'node://9': (11, 13)},
        handle_nodes={'branch://B1': (7, 9), 'node://7,9': (7, 9)})
    assert renderer.extract_nodes(renderer.expression('node://7,9')) == {7, 8, 9}


def test_bound_sparse_expand_does_not_invent_intermediate_nodes():
    renderer = HandleRenderer(handle_nodes={'reqs://1-9': (1, 9)})
    assert renderer.extract_nodes('expand(reqs://1-9)') == {1, 9}


def test_branch_expand_uses_its_exact_binding():
    renderer = HandleRenderer(handle_nodes={'branch://B1': (3, 8)})
    assert renderer.extract_nodes('expand(branch://B1)') == {3, 8}


def test_foreign_read_and_partial_bodies_do_not_claim_coverage():
    renderer = HandleRenderer(style='read', path='cold.txt',
        node_ranges={'node://7': (4, 6), 'node://8': (5, 8)}, handle_nodes={'node://7': (7,)})
    assert renderer.extract_nodes(renderer.expression('node://7')) == {7}
    assert not renderer.extract_nodes("Read(file_path='other.txt', offset=4, limit=3)")


def test_hidden_cold_bindings_are_not_exposed_entrances():
    projection = SimpleNamespace(text='task facts only', cold=SimpleNamespace(handles={'node://7': (7,)}))
    assert exposed_handles(projection) == 0


def test_exposed_count_deduplicates_visible_parameters_and_expand_references():
    expression = "Read(file_path='cold.txt', offset=4, limit=3)"
    projection = SimpleNamespace(text=expression + '\n' + expression + '\nexpand(node://7)\nexpand(node://7)',
                                 cold=SimpleNamespace(handles={f'node://{i}': (i,) for i in range(10)}))
    assert exposed_handles(projection) == 2


def test_exposed_mentions_can_be_counted_without_private_cold_state():
    assert exposed_handles(SimpleNamespace(text='expand(node://7)')) == 1


def test_actual_read_span_and_coverage_agree_for_aliased_group(tmp_path):
    from synaptic.coldstore import ColdStore
    from tests.wsc._recovery_contract import parse_read_refs
    from tests.wsc.test_cold_read_view import FileReadTool, _read, _strip_line_numbers

    cold = ColdStore()
    bodies = {7: 'first request: preserve format', 8: 'middle request: release R2026-10',
              9: 'last request: validate before publishing'}
    cold.put_nodes([(idx, text, {}) for idx, text in bodies.items()])
    cold.bind('branch://B1', (7, 9))
    cold.bind('node://7,9', (7, 9))
    view = tmp_path / 'cold.txt'
    renderer = HandleRenderer(style='read', path=str(view), node_ranges=cold.write_text_view(view),
                              handle_nodes=cold.handles)
    expression = renderer.expression('node://7,9')
    entry = parse_read_refs(expression)[0]
    returned = _strip_line_numbers(_read(FileReadTool(cwd=str(tmp_path)), view,
                                         offset=entry.offset, limit=entry.limit))
    assert all(text in returned for text in bodies.values())
    assert renderer.extract_nodes(expression) == set(bodies)
