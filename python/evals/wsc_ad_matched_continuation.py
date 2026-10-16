"""Reuse generated heads; compare all available arms with lossless replay carriers."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path

from engine.abort import AbortController
from tools.file_read_tool.file_read_tool import FileReadTool
import evals.wsc_ad_experiment as e


async def evaluate(calls,name,label):
    folder=e.ROOT/name;folder.mkdir(exist_ok=True)
    template=json.loads((e.OLD/name/'template.json').read_text(encoding='utf-8'))
    rows=[json.loads(x) for x in (e.OLD/name/'source.jsonl').read_text(encoding='utf-8').splitlines()]
    cut=template['cut'];tail,carriers=e.preserve_tail(rows[cut:])
    if label in {'A1','E'}:
        previous=json.loads((e.OLD/name/f'{label}-runtime-messages.json').read_text(encoding='utf-8'))
        hot=previous[1:len(previous)-len(rows[cut:])-2]
    elif label=='D':
        previous=json.loads((e.ORIGINAL/name/'D-runtime-messages.json').read_text(encoding='utf-8'));hot=[previous[1]]
    else:
        head_root=e.ROOT.parent/os.environ.get('WSC_AD_HEAD_ROOT','wsc-AD-215')
        hot=[{'role':'assistant','content':(head_root/name/(label+'-head.txt')).read_text(encoding='utf-8')}]
        if os.environ.get('WSC_D_CACHE_BOUNDARY')=='1':
            # Each existing JSON facts block gets an explicit input boundary;
            # the semantic text itself is unchanged and shared across variants.
            chunks=hot[0]['content'].splitlines()
            for chunk in chunks:json.loads(chunk)
            hot=[{'role':'user','content':chunk} for chunk in chunks]
    result={'case':name,'mode':label,'head_reused':True,'hot_tokens':e.tokens(hot),'historical_result_carriers':carriers,
        'reads':[],'grade':None,'answer':None};calls.report['arms'].append(result)
    messages=[template['system'],*hot,*tail,template['archive']]
    if label in {'AD1','D1'}:
        import re
        i=int(re.search(r'source_index=(\d+)',template['query']['content']).group(1));row=rows[i]
        messages.append({'role':'user','content':e.canonical({'recovered_evidence':{'source_index':i,
            'event_id':row.get('id'),'content_hash':e.digest(row),'decoded_text_start':e.source_text(row['content'])[:5000]}})})
    messages.append(template['query'])
    reader=FileReadTool(cwd=str(e.ORIGINAL/name));reader.set_vision_enabled(True)
    archive_root=e.ROOT.parent/os.environ.get('WSC_AD_ARCHIVE_ROOT','wsc-AD-214')/name
    ad_reader=FileReadTool(cwd=str(archive_root));ad_reader.set_vision_enabled(True)
    tools=[reader.schema()]
    if label in {'AD1','D1'}:tools.append({'name':'SearchEvidence','description':'Literal search of source events; exact excerpts and stable source IDs.',
        'input_schema':{'type':'object','properties':{'query':{'type':'string'}},'required':['query']}})
    if os.environ.get('WSC_AD_SEMANTIC_ONLY')=='1':
        tools=[];result['semantic_only_no_model_retrieval']=True
    result['full_request_tokens']=e.tokens(messages,tools)
    spec=importlib.util.spec_from_file_location('matched_grading',e.OLD/'evaluate-valid.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
    gold=json.loads((e.OLD/'gold.json').read_text(encoding='utf-8'))[name]
    for turn in range(4):
        body=e.CLIENT._build_body(messages,tools,stream=False);body.update(max_tokens=int(os.environ.get('WSC_AD_CONTINUATION_LIMIT','1536')),temperature=0)
        if os.environ.get('WSC_AD_DROP_PRIVATE_REASONING')=='1':
            for m in body['messages']:m.pop('reasoning_content',None)
        answer=await calls.call(body,f'{name}-{label}-matched-{turn}');reply=answer['choices'][0]['message'];uses=reply.get('tool_calls') or []
        if not uses:
            result['answer']=reply.get('content') or '';parsed,strict=g.parse(result['answer']);result['parsed']=parsed
            result['grade']=g.grade(parsed,gold,rows);result['strict_json']=strict;break
        if len(uses)>12:result['error']='tool_batch_capacity_exceeded';break
        blocks=[]
        for u in uses:
            try:args=json.loads(u['function']['arguments'])
            except ValueError:args={}
            blocks.append({'type':'tool_use','id':u['id'],'name':u['function']['name'],'input':args})
        messages.append({'role':'assistant','content':blocks})
        for b in blocks:
            content='Tool unavailable';err=True
            try:
                if b['name']=='Read':
                    path=Path(reader.get_path(reader.parse_input(b['input']))).resolve()
                    if path.is_relative_to(e.ORIGINAL/name) or path.is_relative_to(archive_root):
                        impl=reader if path.is_relative_to(e.ORIGINAL/name) else ad_reader
                        reply=await impl.execute(b['input'],AbortController());content=reply.content;err=reply.is_error
                    else:content='Permission denied: path outside experiment'
                elif b['name']=='SearchEvidence' and label in {'AD1','D1'}:
                    query=b['input']['query'];hits=[]
                    for i,row in enumerate(rows):
                        text=e.source_text(row['content']);index=text.casefold().find(query.casefold())
                        if index>=0:hits.append({'event_id':row.get('id'),'line':i+1,'excerpt':text[max(0,index-200):max(0,index-200)+2000]})
                        if len(hits)==5:break
                    content=e.canonical({'matches':hits});err=False
            except Exception as exc:content=e.canonical({'error':type(exc).__name__,'detail':str(exc)[:120]})
            result['reads'].append({'tool':b['name'],'args':b['input'],'is_error':err,'content':content})
            messages.append({'role':'tool','tool_call_id':b['id'],'content':[{'type':'tool_result','tool_use_id':b['id'],'content':content,'is_error':err}]})
        calls.save()
    calls.save();print(e.canonical({'case':name,'arm':label,'grade':result['grade']}),flush=True)


async def main():
    label=os.environ.get('WSC_AD_MATCHED_RUN','wsc-AD-216')
    assert label in {'wsc-AD-216','wsc-AD-217'}
    e.ROOT=e.ROOT.parent/label;e.ROOT.mkdir(exist_ok=True)
    assert not (e.ROOT/'run-report.json').exists(),'No paid rerun'
    calls=e.Calls();pairs=[(n,label) for n in e.CASES for label in ['D','A1','E']]
    pairs.append(('completed_waiting_authority','AD1'))
    outcomes=await asyncio.gather(*(evaluate(calls,n,label) for n,label in pairs),return_exceptions=True)
    for outcome in outcomes:
        if isinstance(outcome,Exception):calls.report['errors'].append(type(outcome).__name__+': '+str(outcome)[:160])
    calls.save();print(e.canonical({'calls':len(calls.report['calls']),'cost':sum(c['cost_estimate'] for c in calls.report['calls']),'errors':calls.report['errors']}))


if __name__=='__main__':asyncio.run(main())
