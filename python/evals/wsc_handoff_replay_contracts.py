"""Native recall/rejection replay A/B and failure contracts, zero API."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from engine.abort import AbortController
from memory.wsc_handoff_generation import generate
from memory.wsc_handoff_replay_candidate import ReplayModel
from model.deepseek import _normalize_messages_for_openai
from model.chunks import ModelChunk
from msgtypes.message import ToolUse
from tests.wsc.test_handoff_fact_disposition import prepared
from tools.todo_write_tool.todo_write_tool import TodoWriteTool

ROOT=Path('D:/lea/XenYon code/_wsc_out/wsc-D-handoff-replay-contracts-267')
THOUGHT='test-only provider thought 中文\nunchanged '
TEXT='test-only assistant content '


class Fake:
    context_limit=100000
    last_usage=None
    def __init__(self,rejection=False,signed=False):
        self.requests=[];self.limits=[];self.rejection=rejection;self.signed=signed
    def for_handoff(self,*,max_tokens):self.limits.append(max_tokens);return self
    async def stream(self,messages,tools,abort):
        self.requests.append(deepcopy(messages));self.last_usage={'request':len(self.requests)}
        if len(self.requests)==1:
            yield ModelChunk(kind='text_delta',text=TEXT)
            yield ModelChunk(kind='reasoning_delta',text=THOUGHT)
            if self.signed:yield ModelChunk(kind='reasoning_block',block={'type':'thinking','text':THOUGHT,'signature':'test-native-signature'})
            yield ModelChunk(kind='tool_use',tool_use=ToolUse('first-frame','TodoWrite' if self.rejection else 'HandoffSource',
                {'_raw':'{malformed'} if self.rejection else {'message_id':'permit','offset':0,'limit':128}))
        else:
            _,raw=prepared()
            yield ModelChunk(kind='tool_use',tool_use=ToolUse('valid-frame','TodoWrite',raw))


async def run(model):
    rows,_=prepared();before=deepcopy(rows);account=[]
    result=await generate(model,[{'role':'user','content':'fixture'}],rows,TodoWriteTool().schema(),
        AbortController(),account=lambda usage:account.append(deepcopy(usage)))
    assert result.id=='valid-frame' and rows==before
    return account


async def main():
    assert not ROOT.exists();ROOT.mkdir();checks=[];proof=[]
    for rejection in (False,True):
        baseline=Fake(rejection);await run(baseline)
        previous=next(m for m in baseline.requests[1] if m['role']=='assistant')
        wire=_normalize_messages_for_openai([previous])[0]
        assert 'reasoning_content' not in wire and wire['content']==''
        proof.append({'path':'rejection' if rejection else 'recall','baseline_drops_reasoning_and_text':True})
        fixed=Fake(rejection);wrapper=ReplayModel(fixed);account=await run(wrapper)
        previous=next(m for m in fixed.requests[1] if m['role']=='assistant')
        wire=_normalize_messages_for_openai([previous])[0]
        assert wire['reasoning_content']==THOUGHT and wire['content']==TEXT
        assert wire['tool_calls'][0]['id']=='first-frame'
        assert json.loads(wire['tool_calls'][0]['function']['arguments'])==({'_raw':'{malformed'} if rejection else {'message_id':'permit','offset':0,'limit':128})
        assert account==[{'request':1},{'request':2}]
        proof[-1].update(candidate_preserves_frame=True,usage_accounting_preserved=True)
    checks.extend(['native_recall_A_B_exact_thought_and_text','native_rejection_A_B_exact_thought_and_text',
        'usage_reset_and_accounting_delegates_to_actual_client'])
    signed=Fake(signed=True);wrapper=ReplayModel(signed);await run(wrapper)
    frame=next(m for m in signed.requests[1] if m['role']=='assistant')
    thought=[b for b in frame['content'] if b['type']=='thinking'];plain=[b for b in frame['content'] if b['type']=='reasoning']
    assert thought==[{'type':'thinking','text':THOUGHT,'signature':'test-native-signature'}] and plain==[]
    checks.append('native_signed_identity_preserved_without_duplicate_display_text')
    parent=ReplayModel(Fake());child=parent.for_handoff(max_tokens=777)
    assert child.frames is parent.frames and child.model.limits[-1]==777
    checks.append('reservation_child_shares_only_completed_frame_registry')
    class Interrupted(Fake):
        async def stream(self,messages,tools,abort):
            yield ModelChunk(kind='reasoning_delta',text='partial')
            yield ModelChunk(kind='tool_use',tool_use=ToolUse('partial','HandoffSource',{}))
            raise ValueError('interrupted')
    interrupted=ReplayModel(Interrupted())
    try:
        async for _ in interrupted.stream([],[],AbortController()):pass
    except ValueError as exc:assert str(exc)=='interrupted'
    else:raise AssertionError('missing failure')
    assert not interrupted.frames
    checks.append('incomplete_stream_not_published_as_complete_replay')
    mismatch=deepcopy(frame)
    tool=next(b for b in mismatch['content'] if b['type']=='tool_use');tool['input']['limit']=99
    try:
        async for _ in wrapper.stream([mismatch],[],AbortController()):pass
    except ValueError as exc:assert str(exc)=='handoff_replay_frame_mismatch'
    else:raise AssertionError('mismatching call args accepted')
    checks.append('same_call_id_different_arguments_fail_closed')
    result={'checks':checks,'native_loop_AB':proof,'api_calls':0,
        'nonclaim':'Replay correctness only, not native thinking semantic quality/production admission.',
        'code_sha256':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [__file__,
            'python/memory/wsc_handoff_replay_candidate.py','python/memory/wsc_handoff_generation.py']}}
    (ROOT/'contracts.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':len(checks),'native_paths':len(proof),'api_calls':0}))


if __name__=='__main__':asyncio.run(main())
