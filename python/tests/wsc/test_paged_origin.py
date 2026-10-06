"""Production first-page declarations preserve explicit recovery extents."""
import re
from dataclasses import replace
from synaptic.project import project
from synaptic.types import WscParams
from synaptic.handles import HandleRenderer
from tests.wsc._recovery_contract import parse_read_refs
from tests.wsc.test_cold_read_view import FileReadTool, _read, _strip_line_numbers


def _projection(tmp_path):
    body = '\n'.join(f'field_{i} = "' + 'x' * 40 + '"' for i in range(3000))
    view = tmp_path / '.xeyo_offload/wsc/cold.txt'
    projected = project([{'role': 'user', 'content': body}], region_end=1,
        params=replace(WscParams(), handle_style='read'), view_path=view)
    return body, view, projected


def test_first_published_read_executes_and_extent_recovers_code(tmp_path):
    body, view, projected = _projection(tmp_path)
    refs = parse_read_refs(projected.text)
    assert len(refs) == 1
    first, last = map(int, re.search(r'span=(\d+)-(\d+)', projected.text).groups())
    tool = FileReadTool(cwd=str(tmp_path))
    first_page = _strip_line_numbers(_read(tool, view, offset=refs[0].offset, limit=refs[0].limit))
    assert first_page != body
    pages = [first_page]
    cursor = first + refs[0].limit
    while cursor <= last:
        take = min(refs[0].limit, last-cursor+1)
        pages.append(_strip_line_numbers(_read(tool, view, offset=cursor, limit=take)))
        cursor += take
    recovered = '\n'.join(pages)
    assert recovered == body
    compile(recovered, '<recovered>', 'exec')
    assert len(pages) == 2


def test_immediate_body_and_recoverable_extent_are_separate(tmp_path):
    _, view, projected = _projection(tmp_path)
    _, ranges = projected.cold.render_text_view()
    renderer = HandleRenderer(style='read', path=str(view), node_ranges=ranges, handle_nodes=projected.cold.handles)
    assert not renderer.extract_nodes(projected.text)
    assert renderer.recoverable_nodes(projected.text) == {0}
    match = re.search(r'span=(\d+)-(\d+)', projected.text)
    malformed = projected.text.replace(match.group(0), f'span={match.group(1)}-{int(match.group(2))+100}')
    assert not renderer.recoverable_nodes(malformed)
    assert not renderer.recoverable_nodes(projected.text.replace(str(view), 'foreign.txt'))


def test_production_builds_read_view_once(tmp_path, monkeypatch):
    from synaptic.coldstore import ColdStore
    original = ColdStore.render_text_view
    calls = []
    def counted(self):
        calls.append(self)
        return original(self)
    monkeypatch.setattr(ColdStore, 'render_text_view', counted)
    _projection(tmp_path)
    assert len(calls) == 1


def test_cold_append_keeps_published_page_and_extent(tmp_path):
    from synaptic.coldstore import ColdStore
    from synaptic.read_plan import line_prefix
    cold = ColdStore()
    cold.put_nodes([(7, '\n'.join('x'*60 for _ in range(3000)), {})])
    cold.bind('node://7', (7,))
    def render():
        text, ranges = cold.render_text_view()
        return HandleRenderer(style='read', path='cold.txt', node_ranges=ranges,
            handle_nodes=dict(cold.handles), line_lengths=line_prefix(text)).expression('node://7')
    first = render()
    assert ' span=' in first
    cold.put_nodes([(2, 'later archived earlier node', {})])
    assert render() == first


def test_atomic_oversized_line_is_not_claimed_safely_pageable():
    from synaptic.read_plan import first_page_end, line_prefix
    assert first_page_end(1, 1, line_prefix('x'*100004)) == 1


def test_real_paired_recovery_saves_initial_failed_call(tmp_path):
    import asyncio
    from tests.wsc.test_cold_read_view import _abort
    body, view, projected = _projection(tmp_path)
    first_read = parse_read_refs(projected.text)[0]
    first, last = map(int, re.search(r'span=(\d+)-(\d+)', projected.text).groups())
    counts = []
    for initial_limit in (last-first+1, first_read.limit):
        tool = FileReadTool(cwd=str(tmp_path))
        cursor, step = first, initial_limit
        fragments, calls, failures = [], 0, 0
        while cursor <= last:
            take = min(step, last-cursor+1)
            while True:
                result = asyncio.run(tool.execute({'file_path': str(view), 'offset': cursor, 'limit': take}, _abort()))
                calls += 1
                if not result.is_error:
                    break
                failures += 1
                assert take > 1
                take = max(1, take//2)
            fragments.append(_strip_line_numbers(result.content))
            cursor += take
            step = take
        assert '\n'.join(fragments) == body
        counts.append((calls, failures))
    assert counts == [(3, 1), (2, 0)]


def test_upgrade_keeps_frozen_legacy_refs_and_adds_safe_origin(tmp_path, monkeypatch):
    import importlib
    module = importlib.import_module('synaptic.project')
    renderer_class = HandleRenderer
    def legacy_renderer(*args, **kwargs):
        kwargs.pop('line_lengths', None)
        return renderer_class(*args, **kwargs)
    body = '\n'.join(f'field_{i} = "' + 'x' * 40 + '"' for i in range(3000))
    messages = [{'role': 'user', 'content': body}]
    view = tmp_path / '.xeyo_offload/wsc/cold.txt'
    params = replace(WscParams(), handle_style='read')
    with monkeypatch.context() as scoped:
        scoped.setattr(module, 'HandleRenderer', legacy_renderer)
        before = project(messages, region_end=1, params=params, view_path=view)
    assert ' span=' not in before.text
    old_refs = parse_read_refs(before.text)
    assert len(old_refs) == 1 and old_refs[0].limit == 3000
    messages += [{'role': 'assistant', 'content': 'checking'}, {'role': 'user', 'content': 'Continue checking.'}]
    after = project(messages, region_end=3, params=params, view_path=view, prev=before.state, cold=before.cold)
    assert after.text.startswith(before.text)
    assert ' span=' in after.text
    safe = next(ref for ref in parse_read_refs(after.text) if ' span=' in ref.line)
    assert safe.offset == old_refs[0].offset and safe.limit < old_refs[0].limit
    _read(FileReadTool(cwd=str(tmp_path)), view, offset=safe.offset, limit=safe.limit)
