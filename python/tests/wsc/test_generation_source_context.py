"""Contract checks for the isolated 347 generation-input candidate."""
from copy import deepcopy
import pytest

from engine.abort import AbortController
from evals.wsc_generation_source_context import select
from memory import wsc_semantic_compaction as semantic
from prompt.assembler import PromptAssembler
from tests.wsc.test_semantic_production import isolated
from tests.wsc.test_semantic_input_boundary import make_task, prepare, CopyBody


class Count:
    context_limit = 5000
    predicted = 500
    def context_input(self, messages, tools): return {'messages': messages, 'tools': tools}
    def context_token_measure(self, source):
        self.measured = deepcopy(source)
        return self.predicted, 'controlled_prediction'


async def fixture(root):
    task = make_task(root)
    semantic.publish(await prepare(task, CopyBody('SEMANTIC_BODY')), task.source(), task.working, cwd=root)
    return task.restart()


@pytest.mark.asyncio
@pytest.mark.parametrize('capacity,predicted,selected', [(5000,904,True),(5000,905,False),(0,1,False)])
async def test_full_request_capacity_and_unchanged_consumer(isolated, capacity, predicted, selected):
    task = await fixture(isolated)
    messages = PromptAssembler().build('SYSTEM', task.project())
    messages.append({'role':'assistant','content':'CURRENT_CONTROL_FACT'})
    before, source = deepcopy(messages), deepcopy(task.source())
    model = Count(); model.context_limit=capacity; model.predicted=predicted
    output, info = await select(messages,task.working,source,model=model,abort=AbortController(),cwd=isolated)
    assert info['selected'] is selected
    assert messages==before and source==task.source()
    assert output[0]==messages[0] and output[-1]==messages[-1]
    assert output[-len(messages[2:]):]==messages[2:]
    assert model.measured['messages'][-1]['content'].startswith('You are performing a CONTEXT CHECKPOINT')
    assert {s['name'] for s in model.measured['tools']}=={'HandoffSource','HandoffCatalog'}
    assert not any(r.get('name')=='session_summary' for r in output) if selected else output[1]['content']=='SEMANTIC_BODY'
    assert task.restart().project()==messages[1:-1]


@pytest.mark.asyncio
async def test_unverified_head_is_not_expanded(isolated):
    task=await fixture(isolated)
    messages=PromptAssembler().build('SYSTEM',task.project());messages[1]['content']+='unowned'
    model=Count()
    output,info=await select(messages,task.working,task.source(),model=model,abort=AbortController(),cwd=isolated)
    assert output is messages and not info['selected'] and not hasattr(model,'measured')


@pytest.mark.asyncio
async def test_media_control_and_tail_identity_preserved(isolated):
    task=await fixture(isolated)
    tail=[{'role':'user','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,fixture'}}]},
          {'role':'assistant','content':[{'type':'tool_use','id':'tail-read','name':'Read','input':{}}]},
          {'role':'tool','tool_call_id':'tail-read','content':'FRESH_RESULT'},
          {'role':'assistant','content':'CURRENT_GOAL_REVISION'}]
    messages=[*PromptAssembler().build('SYSTEM',task.project()),*tail]
    output,info=await select(messages,task.working,task.source(),model=Count(),abort=AbortController(),cwd=isolated)
    assert info['selected'] and output[-4:]==tail


@pytest.mark.asyncio
async def test_count_failure_propagates_without_retirement(isolated):
    task=await fixture(isolated);before=deepcopy(task.project());cursor=task.working.compact_cursor
    class Failure(Count):
        async def predict_context_tokens(self,*args): raise TimeoutError('count_failed')
    with pytest.raises(TimeoutError,match='count_failed'):
        await select(PromptAssembler().build('SYSTEM',before),task.working,task.source(),model=Failure(),abort=AbortController(),cwd=isolated)
    assert task.working.compact_cursor==cursor and task.project()==before


@pytest.mark.asyncio
async def test_restored_late_receipt_keeps_call_and_media_binding(isolated, monkeypatch):
    from evals.wsc_production_continuation import ProductionTask
    from session.late_result_guard import request_conflict
    from tests.wsc.test_late_media_identity import IMAGE
    monkeypatch.setenv('XEYO_WSC_MEDIA_ARCHIVE','1')
    rows=[{'id':'invoke','role':'assistant','content':[{'type':'tool_use','id':'late-origin','name':'Read','input':{'file_path':'old.png'}}]},
          {'id':'intervening','role':'user','content':'A later request, unchanged.'},
          {'id':'receipt','role':'tool','tool_call_id':'late-origin','content':[{'type':'tool_result','tool_use_id':'late-origin',
              'content':[{'type':'text','text':'EXACT_LATE_TEXT'},deepcopy(IMAGE)]}]}]
    rows.extend({'id':f'padding-{i}','role':'assistant','content':'old observation'} for i in range(24))
    task=ProductionTask(isolated,rows,session='late-source-context')
    semantic.publish(await prepare(task,CopyBody('SEMANTIC_BODY')),task.source(),task.working,cwd=isolated)
    before=deepcopy(task.source())
    output,info=await select(PromptAssembler().build('SYSTEM',task.project()),task.working,before,
        model=Count(),abort=AbortController(),cwd=isolated)
    assert info['selected'] and request_conflict(output) is None
    assert 'EXACT_LATE_TEXT' in str(output) and 'late-origin' in str(output)
    assert IMAGE['image_url']['url'] in str(output) and 'source_message_id' in str(output)
    assert task.source()==before
