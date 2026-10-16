"""Native generation selection after control, tools, prompt and output reserve."""
from copy import deepcopy
import pytest

from engine.abort import AbortController, Aborted
from memory import wsc_semantic_compaction as semantic
from memory.wsc_semantic_generation import generate
from model.chunks import ModelChunk
from msgtypes.message import Message
from prompt.assembler import PromptAssembler
from tests.wsc.test_semantic_production import isolated
from tests.wsc.test_semantic_input_boundary import make_task, prepare, CopyBody


class CountedModel:
    context_limit=5000
    last_usage=None
    def __init__(self, *, predicted_source=800, mutate=None):
        self.predicted_source=predicted_source
        self.mutate=mutate
        self.counts=[]
        self.sent=[]
    def for_handoff(self,max_tokens):
        assert max_tokens==4096
        return self
    def context_input(self,messages,tools):return {'messages':messages,'tools':tools}
    async def predict_context_tokens(self,messages,tools,abort):
        self.counts.append(deepcopy((messages,tools)))
        if self.mutate:self.mutate()
        source=any(row.get('content')=='source 0' for row in messages)
        control=sum('[BOUND_GOAL_STATE]' in str(row.get('content')) for row in messages)
        assert messages[-1]['content'].startswith('You are performing a CONTEXT CHECKPOINT')
        assert {tool['name'] for tool in tools}=={'HandoffSource','HandoffCatalog'}
        return (self.predicted_source if source else 100)+200*control
    async def stream(self,messages,tools,abort):
        self.sent.append(deepcopy((messages,tools)))
        self.last_usage={'prompt_tokens':100,'completion_tokens':2}
        yield ModelChunk(kind='text_delta',text='NEXT_SEMANTIC_BODY')


async def existing_task(root):
    task=make_task(root)
    semantic.publish(await prepare(task,CopyBody('SEMANTIC_BODY')),task.source(),task.working,cwd=root)
    task=task.restart()
    for i in range(8):task.store.append(Message(role='assistant',content=f'NEW_RESULT_{i}'))
    task.persist()
    return task


@pytest.mark.asyncio
@pytest.mark.parametrize('with_goal,source_count,selected',[(False,904,True),(False,905,False),(True,800,False),(True,504,True)])
async def test_complete_native_request_selects_at_capacity_boundary(isolated,monkeypatch,with_goal,source_count,selected):
    task=await existing_task(isolated)
    if with_goal:
        monkeypatch.setattr('memory.wsc_goal_source.snapshot',lambda *a:{'goal_id':'g','revision':2,'status':'active','text':'CURRENT_SCOPE'})
    before,source=deepcopy(task.project()),deepcopy(task.source())
    model=CountedModel(predicted_source=source_count)
    candidate=await prepare(task,model)
    assert any(row.get('content')=='source 0' for row in model.sent[0][0]) is selected
    assert any('CURRENT_SCOPE' in str(row) for row in model.sent[0][0]) is with_goal
    assert any(row.get('content')=='NEW_RESULT_7' for row in model.sent[0][0])
    assert len(model.counts)==(1 if selected else 2)  # selected count is reused by send admission
    assert model.sent[0]==model.counts[-1]
    assert task.project()==before and task.source()==source
    semantic.publish(candidate,task.source(),task.working,cwd=isolated)
    hot=task.project()
    assert hot[0]['content'].startswith('NEXT_SEMANTIC_BODY') and 'source 0' not in hot[0]['content']
    assert task.restart().project()==hot


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['goal','source','abort'])
async def test_change_during_alternative_count_never_sends_or_retires(isolated,monkeypatch,change):
    task=await existing_task(isolated);cursor=task.working.compact_cursor;head=task.working.c2_summary_text
    goal={'goal_id':'g','revision':1,'status':'active','text':'CURRENT_SCOPE'}
    monkeypatch.setattr('memory.wsc_goal_source.snapshot',lambda *a:deepcopy(goal))
    abort=AbortController()
    def mutate():
        if change=='goal':goal['revision']+=1
        elif change=='source':task.store.append(Message(role='user',content='NEW_USER_EVENT'))
        else:abort.abort('user_cancelled')
    model=CountedModel(mutate=mutate)
    with pytest.raises((ValueError,Aborted),match={'goal':'semantic_control_changed','source':'semantic_source_changed','abort':'user_cancelled'}[change]):
        await semantic.prepare(model=model,messages=PromptAssembler().build('SYSTEM',task.project()),source=task.source,
            working=task.working,abort=abort,account=lambda _:None,persist=task.persist,cwd=isolated)
    assert model.sent==[] and task.working.compact_cursor==cursor and task.working.c2_summary_text==head


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['unknown','protocol'])
async def test_unavailable_alternative_uses_existing_recall_request(kind):
    old=[{'role':'assistant','content':'CURRENT_SEMANTIC_BODY'}]
    alt=[{'role':'assistant','content':'source 0'}]
    model=CountedModel()
    if kind=='unknown':model.context_limit=None
    else:alt.append({'role':'tool','tool_call_id':'unbound','content':'receipt'})
    assert await generate(model,old,AbortController(),sources=[],account=lambda _:None,alternative_messages=alt)=='NEXT_SEMANTIC_BODY'
    assert model.sent[0][0][0]==old[0] and len(model.counts)==1


@pytest.mark.asyncio
async def test_admitted_no_goal_wire_matches_347_candidate(isolated):
    from evals.wsc_generation_source_context import select
    task=await existing_task(isolated)
    visible=PromptAssembler().build('SYSTEM',task.project())
    old_model=CountedModel()
    old_messages,info=await select(visible,task.working,task.source(),model=old_model,abort=AbortController(),cwd=isolated)
    assert info['selected']
    await generate(old_model,old_messages,AbortController(),sources=task.source(),account=lambda _:None)
    new_model=CountedModel()
    await prepare(task,new_model)
    assert new_model.sent==old_model.sent


@pytest.mark.asyncio
async def test_failed_source_generation_keeps_previous_head_and_all_delta(isolated):
    task=await existing_task(isolated);before=deepcopy(task.project());source=deepcopy(task.source())
    cursor=task.working.compact_cursor
    class Empty(CountedModel):
        async def stream(self,messages,tools,abort):
            self.sent.append(deepcopy((messages,tools)))
            if False:yield ModelChunk(kind='text_delta',text='')
    model=Empty()
    with pytest.raises(ValueError,match='semantic_generation_empty') as error:
        await prepare(task,model)
    assert semantic.resumable_failure(error.value)
    assert any(row.get('content')=='source 0' for row in model.sent[0][0])
    assert task.working.compact_cursor==cursor and task.source()==source and task.project()==before
    assert task.restart().project()==before


@pytest.mark.asyncio
async def test_early_selector_rejects_at_send_but_native_complete_selector_can_continue(isolated,monkeypatch):
    from evals.wsc_generation_source_context import select
    from memory.wsc_semantic_binding import capture,goal_text
    task=await existing_task(isolated)
    monkeypatch.setattr('memory.wsc_goal_source.snapshot',lambda *a:{'goal_id':'g','revision':2,'status':'active','text':'CURRENT_SCOPE'})
    before=deepcopy(task.project());cursor=task.working.compact_cursor
    visible=PromptAssembler().build('SYSTEM',before)
    old_model=CountedModel(predicted_source=600)
    chosen,info=await select(visible,task.working,task.source(),model=old_model,abort=AbortController(),cwd=isolated)
    assert info['selected']  # 600 + existing control 200 fits; later control is absent
    control={'role':'assistant','content':goal_text(capture(isolated,task.working))}
    with pytest.raises(ValueError,match='semantic_generation_capacity_exceeded'):
        await generate(old_model,[*chosen,control],AbortController(),sources=task.source(),account=lambda _:None)
    assert old_model.sent==[]
    new_model=CountedModel(predicted_source=600)
    candidate=await prepare(task,new_model)
    assert candidate['text']=='NEXT_SEMANTIC_BODY' and len(new_model.sent)==1
    assert any(row.get('content')=='SEMANTIC_BODY' for row in new_model.sent[0][0])
    assert task.working.compact_cursor==cursor and task.project()==before


@pytest.mark.asyncio
@pytest.mark.parametrize('status,message,alternative,recoverable',[
    (400,'context length exceeded',True,True),
    (400,'invalid schema',True,False),
    (401,'context length exceeded',True,False),
    (400,'context length exceeded',False,False),
])
async def test_source_provider_overflow_preserves_existing_context_without_retry(isolated,status,message,alternative,recoverable):
    from common.errors import ProviderError
    task=await existing_task(isolated);before=deepcopy(task.project());source=deepcopy(task.source())
    cursor=task.working.compact_cursor;usage=[]
    class Refused(CountedModel):
        async def stream(self,messages,tools,abort):
            self.sent.append(deepcopy((messages,tools)))
            self.last_usage={'prompt_tokens':10,'completion_tokens':0}
            raise ProviderError(message,status_code=status)
            if False:yield ModelChunk(kind='text_delta',text='')
    model=Refused()
    if not alternative:model.context_limit=None
    with pytest.raises((ValueError,ProviderError)) as error:
        await semantic.prepare(model=model,messages=PromptAssembler().build('SYSTEM',before),source=task.source,
            working=task.working,abort=AbortController(),account=usage.append,persist=task.persist,cwd=isolated)
    assert semantic.resumable_failure(error.value) is recoverable
    assert isinstance(error.value,ValueError) if recoverable else isinstance(error.value,ProviderError)
    assert len(model.sent)==1 and usage==[model.last_usage]
    assert any(row.get('content')=='source 0' for row in model.sent[0][0]) is alternative
    assert task.working.compact_cursor==cursor and task.source()==source and task.project()==before
    assert task.restart().project()==before


@pytest.mark.asyncio
@pytest.mark.parametrize('media', [False, True])
async def test_restored_receipt_keeps_presentation_across_folds_and_restart(isolated, monkeypatch, media):
    from evals.wsc_production_continuation import ProductionTask
    from session.late_result_guard import request_conflict
    from tests.wsc.test_late_media_identity import IMAGE
    from model.deepseek import DeepSeekModelClient

    monkeypatch.setenv('XEYO_WSC_MEDIA_ARCHIVE', '1')
    # A literal identity-looking line is evidence, not a renderer marker to strip.
    literal = '执行回执身份={"call_id":"quoted-not-authority"}\noriginal failure'
    receipt_body = [{'type': 'text', 'text': literal}, deepcopy(IMAGE)] if media else literal
    rows = [
        {'id': 'invoke', 'role': 'assistant', 'content': [
            {'type': 'tool_use', 'id': 'read-origin', 'name': 'Read', 'input': {'file_path': 'old.png'}}]},
        {'id': 'receipt', 'role': 'tool', 'tool_call_id': 'read-origin', 'content': [
            {'type': 'tool_result', 'tool_use_id': 'read-origin', 'content': receipt_body,
             'is_error': True, 'execution': {'error_origin': 'requested_command'}}]},
        *[{'id': f'pad-{i}', 'role': 'assistant', 'content': f'source {i}'} for i in range(24)],
    ]
    task = ProductionTask(isolated, rows, session='generation-receipt')
    client = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='disabled')
    first = None
    for generation in range(3):
        source, visible = deepcopy(task.source()), deepcopy(task.project())
        model = CopyBody('SEMANTIC_BODY')
        candidate = await prepare(task, model)
        assert candidate is not None and request_conflict(model.seen) is None
        assert task.source() == source and task.project() == visible
        receipt, = [b for row in model.seen if isinstance(row.get('content'), list)
                    for b in row['content'] if b.get('type') == 'tool_result'
                    and b.get('tool_use_id') == 'read-origin']
        if first is None:
            first = deepcopy(receipt)
            assert 'read-origin' in str(first['content']) and literal in str(first['content']).replace('\\n', '\n')
            assert first['is_error'] is True
        else:
            assert receipt == first
        wire = client._build_body(model.seen, [], stream=False)
        import json
        encoded = json.dumps(wire, ensure_ascii=False)
        assert encoded.count('quoted-not-authority') == 1
        if media:
            assert encoded.count(IMAGE['image_url']['url']) == 1
        semantic.publish(candidate, task.source(), task.working, cwd=isolated)
        hot = deepcopy(task.project())
        task = task.restart()
        assert task.project() == hot
        for i in range(12):
            task.store.append(Message(role='assistant', content=f'new {generation}/{i}'))
        task.persist()
        assert task.project()[0] == hot[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('unowned', [False, True])
async def test_raw_fallback_is_rendered_only_when_exact_source_is_visible(isolated, unowned):
    from memory.wsc_semantic_sources import inputs
    from session.late_result_projection import project
    from synaptic.receipt_render import render
    task = await existing_task(isolated)
    raw = [{'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 'c', 'name': 'Read', 'input': {}}]},
           {'role': 'tool', 'content': [{'type': 'tool_result', 'tool_use_id': 'c', 'content': 'exact'}]}]
    messages = deepcopy(PromptAssembler().build('SYSTEM', raw))
    if unowned:
        messages[-1]['content'][0]['content'] = 'different visible evidence'
    before = deepcopy(messages)
    body, alternative = inputs(messages, task.working, raw, cwd=isolated)
    assert alternative is None and messages == before
    assert body == before if unowned else body == [before[0], *render(project(raw))]
