"""Uncompressed binding calibration, separate from old compaction grades.

The report artifact version and execution revision are independent axes. Source
records, not an engine assumption about matching numbers, bind a result to the
active artifact. The unlinked case has no uniquely justified selection.
"""
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import evals.wsc_ad_experiment as e
import evals.wsc_elimination_faithful as f
from evals.wsc_answer_parse import parse

ROOT=e.ROOT.parent/'wsc-report-binding-calibration-264'
QUERY=('核对这些来源记录，输出JSON：current_report_version、selected_execution_id、selected_value、'
    'late_execution_id、publish_authorized、git_authorized、phase。selected字段是支撑当前采用的报告的已到账执行及值；'
    '来源不能唯一确定时为null。late字段是标记late=true的到账执行。版本与执行修订号分别按原记录解释。')


def prepare():
    assert not ROOT.exists();ROOT.mkdir()
    samples=[]
    # Same world, differing only the presence/content of explicit result/artifact
    # links. Current artifact7 is supported by execution revision103, not7.
    for kind in ('unlinked','linked','crossed'):
        user={'id':'u-current','role':'user','content':'正在核对素材审计报告，当前采用报告版本7（artifact audit-new），处于 verification。发布和git操作未授权。'}
        early={'id':'r-early','role':'tool','content':[{'type':'tool_result','tool_use_id':'audit-alpha',
            'content':json.dumps({'revision':103,'value':286},separators=(',',':')),
            'execution':{'id':'execution-alpha','revision':103,'late':False,'status':'ok','complete':True}}]}
        late={'id':'r-late','role':'tool','content':[{'type':'tool_result','tool_use_id':'audit-beta',
            'content':json.dumps({'revision':7,'value':419},separators=(',',':')),
            'execution':{'id':'execution-beta','revision':7,'late':True,'status':'ok','complete':True}}]}
        if kind!='unlinked':
            active=early if kind=='linked' else late
            stale=late if kind=='linked' else early
            for record,artifact,version in ((active,'audit-new',7),(stale,'audit-old',6)):
                value=json.loads(record['content'][0]['content'])
                value.update(artifact_id=artifact,report_version=version)
                record['content'][0]['content']=json.dumps(value,separators=(',',':'))
        rows=[user,{'id':'a','role':'assistant','content':[{'type':'tool_use','id':'audit-alpha','name':'AuditProbe','input':{'revision':103}},
            {'type':'tool_use','id':'audit-beta','name':'AuditProbe','input':{'revision':7}}]},early,late]
        expected={'current_report_version':7,'selected_execution_id':None if kind=='unlinked' else 'execution-alpha' if kind=='linked' else 'execution-beta',
            'selected_value':None if kind=='unlinked' else 286 if kind=='linked' else 419,
            'late_execution_id':'execution-beta','publish_authorized':False,'git_authorized':False,'phase':'verification'}
        source=ROOT/(kind+'-sources.json');e.write(source,rows)
        body=e.CLIENT._build_body([{'role':'user','content':f.c.canonical({'source_records':rows})},{'role':'user','content':QUERY}],[],stream=False)
        body.update(max_tokens=2048,temperature=0,thinking={'type':'disabled'})
        path=ROOT/(kind+'-input.json');e.write(path,body)
        samples.append({'name':kind,'input':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'source':str(source),'expected':expected})
    plan={'samples':samples,'paid_run_allowed':True,'http_retries':0,'max_requests_per_sample':1,
        'proposed_new_run_cost_ceiling_cny':None,'purpose':'Check gold identifiability before more compaction/continuation calls.',
        'nonclaim':'Uncompressed synthetic calibration only, not holdout compaction/task success or a change to old235 grades.',
        'code_sha256':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [__file__,
            'python/evals/wsc_ad_experiment.py','python/evals/wsc_elimination_faithful.py']}}
    e.write(ROOT/'preflight-manifest.json',plan);return plan


async def execute(plan):
    assert plan['paid_run_allowed'] and not (ROOT/'run-report.json').exists()
    for p,sha in plan['code_sha256'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha
    e.ROOT=ROOT;os.environ['WSC_AD_TRANSPORT']='httpx-direct'
    calls=f.StopAwareCalls();calls.semaphore=asyncio.Semaphore(2);calls.report.update(protocol=plan,observations=[])
    async def one(sample):
        path=Path(sample['input']);assert hashlib.sha256(path.read_bytes()).hexdigest()==sample['sha256']
        answer=await calls.call(f.c.load(path),sample['name']+'-calibration')
        choice=answer['choices'][0];parsed,strict=parse(choice['message'].get('content') or '')
        if not isinstance(parsed,dict):parsed={}
        grade={k:type(parsed.get(k)) is type(v) and parsed.get(k)==v for k,v in sample['expected'].items()}
        record={'name':sample['name'],'parsed':parsed,'strict_json':strict,'grade':grade,
            'success':all(grade.values()) and choice['finish_reason']=='stop','finish_reason':choice['finish_reason']}
        calls.report['observations'].append(record);calls.save();print(f.c.canonical(record),flush=True)
    results=await asyncio.gather(*(one(s) for s in plan['samples']),return_exceptions=True)
    for result in results:
        if isinstance(result,BaseException):raise result
    calls.report['completed']=True;calls.save()


if __name__=='__main__':
    if os.environ.get('WSC_BINDING_CALIBRATION_EXECUTE')=='1':
        try:asyncio.run(execute(f.c.load(ROOT/'preflight-manifest.json')))
        except f.EvaluationStop as exc:print(f.c.canonical({'evaluation_stopped':str(exc)}),flush=True)
    else:print(f.c.canonical({'prepared':len(prepare()['samples']),'api_calls':0}))
