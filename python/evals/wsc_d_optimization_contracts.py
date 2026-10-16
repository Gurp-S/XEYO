"""Zero-API contracts for D candidates; native generator replay and cold seals."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile

import evals.wsc_ad_experiment as e
from evals.wsc_d_handoff_shell_control import extract_d
from evals.wsc_elimination_faithful import MeteredNative
from memory.wsc_declaration_candidate import body_for_declaration,DeclarationCalls
from memory.wsc_cold_source_candidate import ColdSources
from memory.wsc_handoff_generation import generate
from tools.todo_write_tool.todo_write_tool import TodoWriteTool
from engine.abort import AbortController

ROOT=e.ROOT.parent/'wsc-D-optimization-contracts-236'


def response(name,args,number):
    return {'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':[{'id':'contract-call-'+str(number),
        'function':{'name':name,'arguments':args if isinstance(args,str) else json.dumps(args,ensure_ascii=False)}}]}}],
        'usage':{'prompt_tokens':1,'completion_tokens':1}}


class Replay:
    def __init__(self,responses):self.responses=iter(responses);self.bodies=[]
    async def call(self,body,label):self.bodies.append(deepcopy(body));return next(self.responses)


async def native_contracts():
    results=[]
    for name in e.CASES:
        native,decl,_,_,_=extract_d(e.ORIGINAL/name)
        rows=[json.loads(s) for s in (e.ORIGINAL/name/'source.jsonl').read_text(encoding='utf-8').splitlines()]+decl
        cases=[('direct',[response('TodoWrite',native,1)]),
               ('invalid_json_then_valid',[response('TodoWrite','{',1),response('TodoWrite',native,2)]),
               ('catalog_source_then_valid',[response('HandoffCatalog',{'start':0,'limit':1},1),
                    response('HandoffSource',{'message_id':rows[0]['id'],'offset':0,'limit':64},2),response('TodoWrite',native,3)]),
               ('plain_text_rejected',[{'choices':[{'finish_reason':'stop','message':{'content':'ordinary summary'}}]}])]
        for scenario,answers in cases:
            replay=Replay(answers);original=deepcopy(rows)
            try:
                value=await generate(MeteredNative(DeclarationCalls(replay),name+'-'+scenario),
                    [{'role':'assistant','content':json.dumps(native,ensure_ascii=False)}],rows,TodoWriteTool().schema(),
                    AbortController(),account=lambda usage:None,scope_protocol=True)
                assert scenario!='plain_text_rejected' and value.input==native
                outcome='accepted'
            except ValueError as exc:
                assert scenario=='plain_text_rejected' and str(exc)=='handoff_declaration_missing'
                outcome='rejected'
            assert rows==original
            assert all(b['tool_choice']=='required' for b in replay.bodies)
            assert len(replay.bodies)==len(answers)
            if scenario=='invalid_json_then_valid':
                assert 'handoff_invalid_json' in json.dumps(replay.bodies[1])
            results.append({'case':name,'scenario':scenario,'outcome':outcome,
                'native_generation_requests_simulated':len(replay.bodies),'source_history_unchanged':True,'real_http_calls':0})
    return results


def cold_contracts():
    results=[]
    with tempfile.TemporaryDirectory(prefix='wsc-cold-contract-') as temp:
        path=Path(temp)/'source.jsonl'
        rows=[{'id':'current','role':'user','content':'当前报告版本2，金额947。旧版本1仅作历史。'},
              {'id':'receipt','role':'tool','content':[{'type':'tool_result','tool_use_id':'r2','content':'核验成功：版本2，金额947。'}]}]
        raw=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows).encode('utf-8');path.write_bytes(raw)
        seal=hashlib.sha256(raw).hexdigest();cold=ColdSources(path,seal)
        assert cold.locator()['source_count']==2;results.append('bounded_locator')
        page=cold.catalog({'start':0,'limit':1,'query':'金额947'})
        assert page['records'][0]['message_id']=='current' and page['next_source']==1;results.append('literal_discovery_pagination')
        page['records'][0]['message_id']='tampered'
        assert cold.catalog({'start':0,'limit':1})['records'][0]['message_id']=='current';results.append('catalog_output_cannot_mutate_index')
        text=rows[0]['content'];parts=[];offset=0
        while offset<len(text):
            answer=cold.source({'message_id':'current','offset':offset,'limit':3});parts.append(answer['content']);offset+=len(answer['content'])
        assert ''.join(parts)==text;results.append('unicode_full_exact_pagination')
        matched=cold.source({'message_id':'receipt','query':'金额947','limit':20})
        assert matched['archive_sha256']==seal and '金额947' in json.dumps(matched,ensure_ascii=False);results.append('exact_tool_result_query')
        assert cold.reopen().source({'message_id':'current','offset':0,'limit':4096})['content']==text;results.append('restart_exact_source')
        for label,args in [('missing_id',{'message_id':'absent','offset':0,'limit':10}),('invalid_offset',{'message_id':'current','offset':True,'limit':10})]:
            try:cold.source(args)
            except ValueError:results.append(label)
            else:raise AssertionError(label)
        path.write_bytes(raw+b'\n')
        try:cold.reopen()
        except ValueError as exc:assert str(exc)=='cold_source_seal_mismatch';results.append('restart_seal_mismatch')
        else:raise AssertionError('Changed archive silently reused')
        assert cold.source({'message_id':'current','offset':0,'limit':4096})['content']==text;results.append('loaded_snapshot_does_not_drift')
        duplicate=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in [rows[0],rows[0]]).encode()
        path.write_bytes(duplicate);cold=ColdSources(path,hashlib.sha256(duplicate).hexdigest())
        try:cold.source({'message_id':'current','offset':0,'limit':10})
        except ValueError as exc:assert str(exc)=='handoff_source_not_unique';results.append('ambiguous_identity_rejected')
        else:raise AssertionError('Ambiguous evidence accepted')
    return results


async def main():
    ROOT.mkdir(exist_ok=True);assert not (ROOT/'contracts.json').exists()
    base=e.CLIENT._build_body([{'role':'user','content':'task'}],[TodoWriteTool().schema()],stream=False)
    original=deepcopy(base);candidate=body_for_declaration(base)
    assert base==original and candidate=={**base,'tool_choice':'required'}
    transport=['only_output_channel_changed']
    for label,body in [('task_tool',{'tools':[{'function':{'name':'Shell'}},{'function':{'name':'TodoWrite'}}],'thinking':{'type':'disabled'}}),
                       ('thinking',{'tools':base['tools'],'thinking':{'type':'enabled'}}),('no_tools',{'thinking':{'type':'disabled'}})]:
        try:body_for_declaration(body)
        except ValueError:transport.append(label+'_rejected')
        else:raise AssertionError('Non-declaration request admitted')
    native=await native_contracts();cold=cold_contracts()
    result={'transport':transport,'native_generator_replays':native,'cold':cold,'real_http_calls':0,
        'nonclaim':'Contract replay proves boundaries and source fidelity, not API semantic quality or autonomous recall.'}
    e.write(ROOT/'contracts.json',result)
    print(json.dumps({'transport_contracts':len(transport),'native_generator_replays':len(native),'cold_contracts':len(cold),'real_http_calls':0}))


if __name__=='__main__':asyncio.run(main())
