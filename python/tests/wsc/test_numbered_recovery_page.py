"""Published cold-Read pages fit the actual numbered recovery receipt bound."""
import asyncio
import copy
from bisect import bisect_right
from dataclasses import replace

from engine.abort import AbortController
from memory.wsc_projection import _emit
from memory.wsc_recovery_emit import MAX_RECOVERY_CHARS
from synaptic.read_budget import MAX_READ_CHARS, numbered_chars
from synaptic.read_plan import first_page_end, line_prefix
from synaptic.project import project
from synaptic.types import WscParams
from tests.wsc._recovery_contract import parse_read_refs
from tools.file_read_tool.file_read_tool import FileReadTool
from tools.fileio.text import add_line_numbers


def _old_body_page(start, end, prefix):
    return min(end, bisect_right(prefix, prefix[start-1]+100004)-1)


def _emitted_read(path, args, content):
    messages = [dict(role='assistant', content=[dict(type='tool_use', id='read', name='Read', input=args)]),
                dict(role='user', content=[dict(type='tool_result', tool_use_id='read', is_error=False, content=content)])]
    original = copy.deepcopy(messages)
    result = _emit('frozen', messages, 0, 0, cwd=str(path.parent), view_path=path)
    assert messages == original
    return result[-1]['content'][0]['content']


def test_real_read_no_longer_loses_the_numbered_page(tmp_path, monkeypatch):
    monkeypatch.setenv('XEYO_TOOL_OFFLOAD', '0')
    text = '\n'.join('x'*60 for _ in range(3000))
    path = tmp_path/'cold.txt'
    path.write_text(text, encoding='utf-8')
    prefix = line_prefix(text)
    outcomes = []
    for plan in (_old_body_page, first_page_end):
        stop = plan(1, 3000, prefix)
        args = dict(file_path=str(path), offset=1, limit=stop)
        result = asyncio.run(FileReadTool(cwd=str(tmp_path)).execute(args, AbortController()))
        assert not result.is_error
        outcomes.append(_emitted_read(path, args, result.content) == result.content)
    assert outcomes == [False, True]


def test_exact_number_width_and_maximum_safe_end():
    for start in (1, 99999, 999999, 1000000):
        lines = ['a'*(i%80) for i in range(3000)]
        prefix = line_prefix('\n'.join(['']*(start-1)+lines))
        end = start+len(lines)-1
        stop = first_page_end(start, end, prefix)
        emitted = add_line_numbers('\n'.join(lines[:stop-start+1]), start_line=start)
        assert len(emitted) == numbered_chars(start, stop, prefix)
        assert len(emitted) <= MAX_RECOVERY_CHARS == MAX_READ_CHARS
        assert stop < end
        assert len(add_line_numbers('\n'.join(lines[:stop-start+2]), start_line=start)) > MAX_RECOVERY_CHARS


def test_short_page_and_unrepresentable_atomic_lines_keep_prior_contract():
    assert first_page_end(1, 3, line_prefix('a\nb\nc')) == 3
    assert first_page_end(1, 2, line_prefix('x'*100004+'\nshort')) == 2
    assert first_page_end(1, 2, line_prefix('short\n'+'x'*100004)) == 2
    assert first_page_end(1, 2, line_prefix('x'*99997+'\nshort')) == 2


def test_mixed_density_each_planned_page_is_retained(tmp_path, monkeypatch):
    monkeypatch.setenv('XEYO_TOOL_OFFLOAD', '0')
    lines = ['a']*500 + ['b'*4000]*40 + ['c']*500
    path = tmp_path/'cold.txt'
    path.write_text('\n'.join(lines), encoding='utf-8')
    prefix = line_prefix('\n'.join(lines))
    cursor = 1
    recovered = []
    while cursor <= len(lines):
        stop = first_page_end(cursor, len(lines), prefix)
        args = dict(file_path=str(path), offset=cursor, limit=stop-cursor+1)
        result = asyncio.run(FileReadTool(cwd=str(tmp_path)).execute(args, AbortController()))
        assert not result.is_error
        expected = add_line_numbers('\n'.join(lines[cursor-1:stop]), start_line=cursor)
        assert result.content == expected and len(expected) <= MAX_RECOVERY_CHARS
        assert _emitted_read(path, args, result.content) == expected
        recovered.extend(lines[cursor-1:stop])
        cursor = stop+1
    assert recovered == lines


def test_upgrade_keeps_old_frozen_reference_and_publishes_numbered_safe_page(tmp_path, monkeypatch):
    import synaptic.handles as handles
    body = '\n'.join('x'*60 for _ in range(3000))
    view = tmp_path/'cold.txt'
    params = replace(WscParams(), handle_style='read')
    messages = [dict(role='user', content=body)]
    with monkeypatch.context() as old:
        old.setattr(handles, 'first_page_end', _old_body_page)
        before = project(messages, region_end=1, params=params, view_path=view)
    old_ref = parse_read_refs(before.text)[0]
    old_result = asyncio.run(FileReadTool(cwd=str(tmp_path)).execute(dict(file_path=str(view), offset=old_ref.offset, limit=old_ref.limit), AbortController()))
    assert not old_result.is_error and len(old_result.content) > MAX_RECOVERY_CHARS
    ranges_before = before.cold.render_text_view()[1]
    messages += [dict(role='assistant', content='checking'), dict(role='user', content='Continue checking.')]
    after = project(messages, region_end=3, params=params, view_path=view, prev=before.state, cold=before.cold)
    assert after.text.startswith(before.text)
    ranges_after = after.cold.render_text_view()[1]
    assert all(ranges_after[key] == value for key, value in ranges_before.items())
    safe = next(ref for ref in parse_read_refs(after.text) if ref.offset == old_ref.offset and ref.limit < old_ref.limit)
    args = dict(file_path=str(view), offset=safe.offset, limit=safe.limit)
    result = asyncio.run(FileReadTool(cwd=str(tmp_path)).execute(args, AbortController()))
    assert not result.is_error and _emitted_read(view, args, result.content) == result.content
