"""Search/Read share a complete mixed-content view without changing source data."""
from copy import deepcopy
import json

import pytest

from memory.wsc_handoff_catalog import Catalog
from memory.wsc_handoff_recall import read
from memory.wsc_handoff_source_content import render
from synaptic.task_fact_sources import source_text


def mixed():
    return {'id': 'source-Ω', 'role': 'assistant', 'content': [
        {'type': 'text', 'text': '读取选定资料，尚未完成核对。'},
        {'type': 'tool_use', 'id': 'inspection-κ', 'name': 'Read',
         'input': {'file_path': '历史/资料.txt', 'offset': 37, 'limit': 11}},
        {'type': 'tool_use', 'id': 'inspection-λ', 'name': 'Read',
         'input': {'file_path': '历史/第二份.txt', 'offset': 9, 'limit': 4}}]}


def test_mixed_source_can_be_found_and_reconstructed_without_losing_calls():
    row = mixed()
    before = deepcopy(row)
    catalog = Catalog([row])
    for query in ('inspection-κ', 'inspection-λ', '资料.txt'):
        records = catalog.read({'start': 0, 'limit': 1, 'query': query})['records']
        assert len(records) == 1 and records[0]['message_id'] == row['id']
        assert records[0]['text_characters'] == len(render(row))
    result = read({'message_id':row['id'], 'offset':0, 'limit':4096}, [row])
    assert result['text_complete'] and json.loads(result['content']) == row['content']
    assert row == before


@pytest.mark.parametrize('kind', ['calls', 'function', 'image', 'annotation', 'non_dict'])
def test_structured_parts_and_top_level_invocations_are_complete(kind):
    row = {'id':'r', 'role':'assistant', 'content':'检查资料。'}
    if kind == 'calls':
        row['tool_calls'] = [{'id':'call-r', 'type':'function',
                             'function':{'name':'Read','arguments':'{"offset":7}'}}]
    elif kind == 'function':
        row['function_call'] = {'name':'Read','arguments':'{"offset":7}'}
    else:
        row['content'] = [{'type':'text','text':'检查资料。'}]
        if kind == 'image':row['content'].append({'type':'image','source':{'type':'url','url':'asset://owned/image-7'}})
        if kind == 'annotation':row['content'][0]['annotations'] = [{'source_id':'anchor-9'}]
        if kind == 'non_dict':row['content'].append('opaque-original-part')
    expected = row if kind in {'calls','function'} else row['content']
    result = read({'message_id':'r','offset':0,'limit':4096},[row])
    assert result['text_complete'] and json.loads(result['content']) == expected


@pytest.mark.parametrize('role,content', [
    ('user','Ω=731; 不发布'),
    ('assistant',[{'type':'text','text':'第一段'},{'type':'text','text':'第二段'}]),
    ('tool',[{'type':'tool_result','tool_use_id':'q','content':'精确结果'}]),
    ('tool','原始工具正文'),
])
def test_existing_plain_views_remain_byte_identical(role, content):
    row = {'id':'r','role':role,'content':content}
    previous = source_text(row)
    if previous is None:previous = json.dumps(content, ensure_ascii=False, separators=(',',':'))
    assert render(row) == previous
    assert read({'message_id':'r','offset':0,'limit':4096},[row])['content'] == previous


def test_unicode_pagination_query_offsets_and_filtered_cursor_share_one_view():
    row = mixed()
    rows = [{'id':'noise','role':'user','content':'inspection-κ'}, row]
    original = deepcopy(rows)
    catalog = Catalog(rows)
    page = catalog.read({'start':0,'limit':1,'query':'inspection-κ','role':'assistant'})
    assert page['records'][0]['source'] == 1 and page['next_source'] is None
    text, offset, pieces = render(row), 0, []
    while True:
        part = read({'message_id':row['id'],'offset':offset,'limit':19},rows)
        pieces.append(part['content'])
        assert part['total_characters'] == len(text) and part['content'] == text[offset:offset+19]
        if part['next_offset'] is None:break
        assert part['next_offset'] > offset
        offset = part['next_offset']
    assert ''.join(pieces) == text and json.loads(text) == row['content']
    found = read({'message_id':row['id'],'query':'inspection-λ','limit':150},rows)
    assert found['matches_total'] == 1
    assert all(p['content'] == text[p['offset']:p['end_offset']] for p in found['passages'])
    assert rows == original
    with pytest.raises(ValueError, match='not_unique'):
        read({'message_id':row['id'],'offset':0,'limit':100},[row,deepcopy(row)])


@pytest.mark.asyncio
async def test_native_semantic_loop_receives_original_invocation_then_generates():
    from engine.abort import AbortController
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from memory.wsc_semantic_generation import generate
    row = mixed()
    visible = [{'role':'assistant','content':'当前核对inspection-κ的原始参数，尚未完成。'}]
    original = deepcopy((visible,row))
    class Model:
        context_limit = 100000
        last_usage = None
        requests = 0
        def for_handoff(self, max_tokens):return self
        async def stream(self, messages, tools, abort):
            self.requests += 1
            self.last_usage = {'prompt_tokens':10,'completion_tokens':2}
            assert messages[:len(visible)] == visible
            if self.requests == 1:
                use = ToolUse('find','HandoffCatalog',{'start':0,'limit':1,'query':'inspection-κ'})
            elif self.requests == 2:
                found = json.loads(messages[-1]['content'][0]['content'])
                assert found['records'][0]['message_id'] == row['id']
                use = ToolUse('recover','HandoffSource',{'message_id':row['id'],'offset':0,'limit':4096})
            else:
                found = json.loads(messages[-1]['content'][0]['content'])
                assert json.loads(found['content']) == row['content']
                yield ModelChunk(kind='text_delta',text='原始读取范围offset=37, limit=11；核对未完成。')
                return
            yield ModelChunk(kind='tool_use',tool_use=use)
    model, accounted = Model(), []
    result = await generate(model,visible,AbortController(),sources=[row],account=accounted.append)
    assert 'offset=37' in result and len(accounted) == model.requests == 3
    assert (visible,row) == original
