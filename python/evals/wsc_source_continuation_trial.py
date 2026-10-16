"""363b: new controlled continuation, old interpretation and late identity.

Same fixed handoff for file/source arms, plus an uncompressed diagnostic.
SQL artifacts are executed on two in-memory datasets, not string-compared.
"""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch

from evals import wsc_minimal_recovery_trial as base
from evals.wsc_source_recovery_trial import SourceTools,archive
from evals.wsc_native_task_files import NativeTaskFiles

ROOT=Path('D:/lea/XenYon code/_wsc_out/wsc-source-continuation-363')
e=base.e


def cases():
    noise=[{'id':f'noise-{i}','role':'assistant','content':f'Archived note {i}: unrelated work completed.'} for i in range(20)]
    sql=[{'id':'original-limit','role':'user','content':'修复订单统计查询：只合计已付款且未取消的订单金额。不要修改数据库表结构，不授权发布。查询代码可以修改。'},
         {'id':'wrong-interpretation','role':'assistant','content':'记录约束：不允许修改任何数据库相关代码。'},*noise]
    sql.append({'id':'sql-file','role':'user','content':'当前文件query.sql内容：SELECT SUM(amount) FROM orders WHERE paid = 1; 表orders现有列id、amount、paid、cancelled。修复尚未交付。'})
    late=[{'id':'scope','role':'user','content':'本轮只验收修订2的bundle-B，验证调用verify-B。禁止发布。修订1是bundle-A，调用verify-A，其回执不能代替本轮验收。'},
          {'id':'calls','role':'assistant','content':[
              {'type':'tool_use','id':'verify-A','name':'Bash','input':{'command':'verify bundle-A --revision 1'}},
              {'type':'tool_use','id':'verify-B','name':'Bash','input':{'command':'verify bundle-B --revision 2'}}]},
          {'id':'current-receipt','role':'tool','content':[{'type':'tool_result','tool_use_id':'verify-B','content':'artifact=bundle-B\nrevision=2\nverified=false\nreason=SCHEMA_MISMATCH','is_error':False}]},
          {'id':'late-old-receipt','role':'tool','content':[{'type':'tool_result','tool_use_id':'verify-A','content':'artifact=bundle-A\nrevision=1\nverified=true\nreason=NONE','is_error':False}]},*noise,
          {'id':'ready','role':'user','content':'两个验证回执均已到达，完成本轮验收决定；不执行发布。'}]
    return [
        {'name':'interpretation','rows':sql,'summary':'当前任务：修复订单统计查询。前代交接把用户约束记为“不允许修改任何数据库相关代码”。目标是统计已付款订单金额；尚未交付修复，未授权发布。',
         'query':'继续完成query.sql的修复，保持原始用户要求。结果保存JSON，字段sql（修复后完整SQL）、schema_changes（结构变更数组）、publish_authorized（布尔值）。',
         'cold':True,'expected':{'grader':'sql'},'markers':['不要修改数据库表结构','未取消']},
        {'name':'late_identity','rows':late,'summary':'当前任务：验收修订2的bundle-B，验证调用verify-B。此前验证仍在运行。实际发布未获授权。',
         'query':'根据已返回的验证结果完成本轮验收决定。保存JSON字段artifact、revision、verification_call_id、accepted、reason、publish_authorized。reason填写对应回执中reason字段的原文值。',
         'cold':True,'expected':{'artifact':'bundle-B','revision':2,'verification_call_id':'verify-B','accepted':False,'reason':'SCHEMA_MISMATCH','publish_authorized':False},
         'markers':['verify-B','SCHEMA_MISMATCH']},
    ]


def grade(actual,expected):
    if expected != {'grader':'sql'}:
        return base.equal_original(actual,expected)
    if not isinstance(actual,dict) or set(actual)!={'sql','schema_changes','publish_authorized'}:
        return False
    if actual['schema_changes']!=[] or actual['publish_authorized'] is not False or not isinstance(actual['sql'],str):
        return False
    sql=actual['sql'].strip()
    if len(sql)>4096 or not sql.lower().startswith(('select ','with ')):
        return False
    for rows,want in [([(1,70,1,0),(2,30,1,0),(3,50,1,1),(4,900,0,0)],100),
                      ([(1,85,1,0),(2,5,1,1),(3,40,0,0)],85)]:
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE orders(id INTEGER, amount INTEGER, paid INTEGER, cancelled INTEGER)')
            db.executemany('INSERT INTO orders VALUES(?,?,?,?)',rows)
            db.execute('PRAGMA query_only=ON')
            try: value=db.execute(sql).fetchall()
            except sqlite3.Error:return False
            if value!=[(want,)]:return False
    return True


async def prepare():
    assert not ROOT.exists(),'Fresh evidence required'
    (ROOT/'work').mkdir(parents=True)
    data=[]
    system=await base.PromptAssembler().build_system(cwd=str(ROOT/'work'),workspace_root=str(ROOT/'work'),
        model='deepseek-flash',tool_names=['Read','Grep','Write'],date_iso='2026-10-16')
    for spec in cases():
        with base.environment(ROOT/spec['name']):
            os.environ.update(XEYO_WSC='1',XEYO_WSC_HEAD_STORE='1',XEYO_WSC_SEMANTIC_HANDOFF='1')
            task=base.ProductionTask(ROOT/spec['name']/'native',spec['rows'],session='boundary-'+spec['name'])
            task.persist()
            candidate=await base.semantic.prepare(model=base.Fixed(spec['summary']),messages=task.source(),source=task.source,
                working=task.working,abort=base.AbortController(),account=lambda _:None,persist=task.persist,cwd=task.root,
                original_source=lambda:base.from_store(task.store))
            hot=base.semantic.publish(candidate,task.source(),task.working,cwd=task.root)
            assert task.restart().project()==hot
            head=base.load(base.heads.path_for(task.working.session_id));paths=list(head['publication']['objects'])
            objects={p:base.sha(Path(p).read_bytes()) for p in paths}
            objects[str(base.heads.path_for(task.working.session_id))]=base.sha(base.heads.path_for(task.working.session_id).read_bytes())
            prepared=dict(system=system,hot={'files':hot,'sources':deepcopy(hot),'full':task.source(),'direct':hot},
                source=task.source(),paths=paths,public_root=str(task.root/'.xeyo_offload/wsc'),objects=objects)
            archive(prepared)
            data.append({'task':{k:v for k,v in spec.items() if k not in ('rows','summary')},'prepared':prepared,'cursor':task.working.compact_cursor})
    good={'sql':'SELECT SUM(amount) FROM orders WHERE paid=1 AND cancelled=0','schema_changes':[],'publish_authorized':False}
    assert grade(good,{'grader':'sql'})
    assert not grade({**good,'sql':'SELECT SUM(amount) FROM orders WHERE paid=1'},{'grader':'sql'})
    assert not grade({**good,'sql':'SELECT 100'},{'grader':'sql'})
    paths=[__file__,base.__file__,'python/evals/wsc_source_recovery_trial.py']
    plan=dict(scope=__doc__,arms=['files','sources','full'],trajectories=6,consumer_request_cap=6,
        output_tokens=2048,http_retries=0,per_call_cny_max=2.5,proposed_new_run_cost_ceiling_cny=1,
        source_control='New synthetic sources, fixed counterexample summaries; no generation-quality claim.',
        reviews='docs/wsc-source-recovery-plan-2026-10-16.md',code_sha256={str(p):base.sha(Path(p).read_bytes()) for p in paths})
    e.write(ROOT/'prepared-private.json',data);e.write(ROOT/'preflight-manifest.json',plan)
    (ROOT/'runner.py').write_bytes(Path(__file__).read_bytes())
    print(e.canonical({'cases':len(data),'sql_good_and_two_bad_grades_checked':True,'cursors':[d['cursor'] for d in data]}),flush=True)


async def run():
    data,plan=base.load(ROOT/'prepared-private.json'),base.load(ROOT/'preflight-manifest.json')
    assert not (ROOT/'run-report.json').exists(),'No paid rerun'
    for path,digest in plan['code_sha256'].items():assert base.sha(Path(path).read_bytes())==digest
    base.ROOT=e.ROOT=ROOT
    base.equal_original=base.equal
    e.CLIENT=base.d.CountedClient(api_key='not-sent',model='deepseek-flash',thinking='disabled')
    calls=base.d.DiagnosticCalls();calls.semaphore=asyncio.Semaphore(1)
    calls.report.update(scope=__doc__,protocol=plan,branches=[]);calls.save()
    try:
        for number,case in enumerate(data):
            SourceTools.archive=archive(case['prepared'])
            for arm in (('files','sources','full') if number==0 else ('full','sources','files')):
                with patch.object(base,'NativeTaskFiles',SourceTools if arm=='sources' else NativeTaskFiles),patch.object(base,'equal',grade):
                    await base.branch(calls,case['prepared'],case['task'],arm,0)
                # Source-tool exposure grading uses the same markers as Read/Grep.
                from evals import wsc_source_recovery_trial as exposure
                with patch.object(exposure,'ROOT',ROOT):exposure.include_source_reads(calls,case['task'],arm)
                if arm=='full':
                    calls.report['branches'][-1].update(cold_required=False,effective_recovery=None)
                    calls.save()
        calls.report['completed']=True
    except Exception as exc:
        calls.report['error']=type(exc).__name__+': '+str(exc)[:400]
        raise
    finally:
        calls.report['cost_estimate_cny']=sum(c['cost_estimate'] for c in calls.report['calls']);calls.save()


async def main():
    with base.environment(ROOT):
        os.environ.update(XEYO_WSC='1',XEYO_WSC_HEAD_STORE='1',XEYO_WSC_SEMANTIC_HANDOFF='1',WSC_AD_TRANSPORT='httpx-direct')
        await (prepare() if sys.argv[1]=='prepare' else run())


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');asyncio.run(main())
