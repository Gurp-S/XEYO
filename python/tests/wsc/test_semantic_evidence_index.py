"""Identity lookup targets actual readable lines, including chunked sources."""
import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tests.wsc.test_semantic_production import isolated


@pytest.mark.asyncio
async def test_index_locates_exact_sources_and_is_bound_to_publication(isolated):
    from engine.abort import AbortController
    from evals.wsc_production_continuation import ProductionTask, PublishedRead
    from memory import wsc_semantic_compaction as semantic, wsc_head_store as hs
    from memory.wsc_semantic_originals import from_store
    from memory.wsc_publication import _READ
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse

    rows = [{'id': 'spec', 'role': 'user', 'content': 'EXACT\nΩ中\\"\u2028' * 4000},
            {'id': 'invocation', 'role': 'assistant', 'content': [
                {'type': 'tool_use', 'id': 'same-call', 'name': 'Read', 'input': {'file_path': 'old.txt'}}]},
            {'id': 'receipt-old', 'role': 'tool', 'content': [
                {'type': 'tool_result', 'tool_use_id': 'same-call', 'content': 'OLD_RECEIPT'}]},
            {'id': 'receipt-late', 'role': 'tool', 'content': [
                {'type': 'tool_result', 'tool_use_id': 'same-call', 'content': 'LATE_RECEIPT'}]}]
    rows += [{'id': f'm{i}', 'role': 'assistant', 'content': str(i)} for i in range(20)]
    task = ProductionTask(isolated, rows, session='index')
    class Summary:
        context_limit = 1000000
        last_usage = None
        def for_handoff(self, max_tokens): return self
        async def stream(self, messages, tools, abort):
            yield ModelChunk(kind='text_delta', text='Task remains pending.')
    source, originals = deepcopy(task.source()), from_store(task.store)
    # Duplicate archived receipts remain searchable, but are not a legal live
    # provider tool sequence. The generator sees the existing historical view.
    candidate = await semantic.prepare(model=Summary(), messages=[{'role': 'assistant', 'content': 'Two archived receipts.'}], source=task.source,
        working=task.working, abort=AbortController(), account=lambda _: None,
        persist=task.persist, cwd=isolated, original_source=lambda: from_store(task.store))
    hot = semantic.publish(candidate, task.source(), task.working, cwd=isolated)
    index_line = next((line for line in hot[0]['content'].split('\n') if line.startswith('证据定位目录:')), None)
    assert index_line is not None, 'no published message/execution identity index'
    path = Path(ast.literal_eval(_READ.search(index_line).group(1)))
    entries = [json.loads(line) for line in path.read_text(encoding='utf-8').split('\n') if line]
    header, entries = entries[0], entries[1:]
    assert header['format'] == 'wsc_evidence_index_v1'
    rec = json.loads(hs.path_for('index').read_text(encoding='utf-8'))
    assert str(path) in rec['publication']['objects']
    reader = PublishedRead(task, rec)
    indexed = await reader.execute(ToolUse('directory', 'Read', {'file_path': str(path), 'offset': 1, 'limit': 2}), AbortController())
    assert not indexed.is_error and 'wsc_evidence_index_v1' in str(indexed.content)
    from tools.grep_tool.grep_tool import GrepTool
    found = await GrepTool(cwd=str(isolated)).execute({
        'path': str(path), 'pattern': 'receipt-late', 'output_mode': 'content'}, AbortController())
    assert not found.is_error
    assert 'file_path' in str(found.content) and 'offset' in str(found.content)
    for view, expected in [('compression', source), ('original', originals)]:
        actual = [entry for entry in entries if entry['view'] == view]
        assert len(actual) == len(expected)
        target = Path(header['views'][view])
        lines = target.read_text(encoding='utf-8').split('\n')
        for entry, row in zip(actual, expected):
            assert entry['file_path'] == str(target.as_posix())
            block = [json.loads(line) for line in lines[entry['offset']-1:entry['offset']-1+entry['limit']]]
            decoded = json.loads(''.join(part['text'] for part in block[1:])) if block[0].get('format') == 'json_chunks' else block[0]
            assert decoded == row
        receipt = next(entry for entry in actual if entry['message_id'] == 'receipt-late')
        assert receipt['tool_result_call_ids'] == ['same-call']
        assert len([entry for entry in actual if entry.get('tool_result_call_ids') == ['same-call']]) == 2
        result = await reader.execute(ToolUse('exact-'+view, 'Read', {
            key: receipt[key] for key in ('file_path', 'offset', 'limit')}), AbortController())
        assert not result.is_error and 'LATE_RECEIPT' in str(result.content) and 'OLD_RECEIPT' not in str(result.content)
    assert task.source() == source
    assert task.restart().project() == hot
    old_head = hs.path_for('index').read_bytes()
    assert task.project() == hot and hs.path_for('index').read_bytes() == old_head
    # Index corruption is publication corruption, not silently trusted metadata.
    path.write_bytes(path.read_bytes() + b'corrupt')
    assert hs.load('index', cwd=str(isolated), cursor=task.working.compact_cursor,
                   messages=task.source(), source_layout=task.working.compression_source_layout) is None


@pytest.mark.asyncio
async def test_same_identity_different_versions_stay_exact_readable(isolated):
    from memory.wsc_semantic_evidence import publish
    from memory.working import WorkingSnapshot
    from tools.file_read_tool.file_read_tool import FileReadTool
    from engine.abort import AbortController
    from memory.wsc_publication import _READ
    state = WorkingSnapshot(session_id='versions')
    locators, sealed = [], {}
    for value in ('OLD_EXACT', 'CURRENT_EXACT'):
        rows = [dict(id='same-message', role='tool', content=[
            dict(type='tool_result', tool_use_id='same-call', content=value)])]
        _, entrance = publish(rows, 1, state, isolated)
        index = Path(ast.literal_eval(_READ.search(entrance).group(1)))
        entry = json.loads(index.read_text(encoding='utf-8').splitlines()[1])
        locators.append({key: entry[key] for key in ('file_path', 'offset', 'limit')})
        sealed[index] = index.read_bytes()
    assert locators[0]['file_path'] != locators[1]['file_path']
    for args, expected, absent in zip(locators, ('OLD_EXACT', 'CURRENT_EXACT'), ('CURRENT_EXACT', 'OLD_EXACT')):
        result = await FileReadTool(cwd=str(isolated)).execute(args, AbortController())
        assert not result.is_error and expected in str(result.content) and absent not in str(result.content)
    assert all(path.read_bytes() == content for path, content in sealed.items())
