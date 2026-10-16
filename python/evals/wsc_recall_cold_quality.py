"""335 cold Need/Locate/Read/Use, and isolated recall-scope fact diagnostic."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

from evals.wsc_recall_quality import CountedClient, configure
from evals.wsc_recall_projection import ROOT
import evals.wsc_semantic_production_trial as trial


async def consumer(calls, arm):
    from evals.wsc_production_continuation import ProductionTask
    from engine.abort import AbortController
    from memory import wsc_semantic_compaction as s, wsc_head_store as hs
    from memory.wsc_semantic_originals import from_store
    from memory.wsc_semantic_binding import capture
    from memory.wsc_handoff_transaction import fingerprint
    from tools.grep_tool.grep_tool import GrepTool
    from tools.base_tool import ToolResult
    p = trial.t.p
    root = p.e.ROOT/arm
    rows = [{'id': f'archive-{i}', 'role': 'assistant', 'content': f'Archived event {i}; unrelated completed work.'} for i in range(60)]
    rows[37] = {'id': 'config-larch', 'role': 'user', 'content': '原始审计配置：账户=acct-larch-64；校验数=92461；不得发布。'}
    rows.append({'id': 'current', 'role': 'user', 'content': '继续审计报告，账户及校验数采用原始审计配置。'})
    task = ProductionTask(root, rows, session='cold335-'+arm); task.persist()
    source = task.source()
    text = '当前任务：生成审计报告，尚未交付；不得发布。账户及校验数在原始审计配置中，当前交接未记录其具体值。'
    candidate = dict(text=text, rows=source, cut=s.boundary(source, task.working),
        previous_cursor=0, binding=capture(root, task.working), source_fingerprint=fingerprint(source),
        original_rows=from_store(task.store))
    hot = s.publish(candidate, source, task.working, cwd=root)
    rec = p.load(hs.path_for(task.working.session_id))
    paths = {Path(x).resolve() for x in rec['publication']['objects']}
    task.registry.register(GrepTool(cwd=str(root)))
    class Reader:
        def schemas(self): return [task.registry.get(name).schema() for name in ('Read', 'Grep')]
        async def execute(self, use, abort):
            key = {'Read': 'file_path', 'Grep': 'path'}.get(use.name)
            path = use.input.get(key) if key and isinstance(use.input, dict) else None
            if not isinstance(path, str) or Path(path).resolve() not in paths:
                return ToolResult('Permission denied: outside published evidence', is_error=True)
            return await task.registry.run(use, abort)
    reader = Reader(); sink = trial.t.ExactArtifactSink(root/'artifacts')
    from prompt.assembler import PromptAssembler
    assembler = PromptAssembler()
    system = await assembler.build_system(cwd=str(root), workspace_root=str(root),
        model='deepseek-flash', tool_names=['Read', 'Grep'])
    messages = assembler.build(system, [*deepcopy(hot),
        {'role':'user','content':'根据原始审计配置，回复JSON对象，字段为account、check_number、publish_authorized。不执行发布。'}])
    state = trial.t.new_state(messages)
    model = p.ProviderFrameModel(calls, p.e.CLIENT, arm+'-cold-consumer', 1024)
    await trial.t.actor_run(model, state, reader.schemas(), sink, reader, additional_requests=6,
        checkpoint=lambda value: p.e.write(root/'actor.json', value))
    answer, _ = p.parse(state.get('answer') or '')
    expected = {'account':'acct-larch-64','check_number':92461,'publish_authorized':False}
    success = answer == expected
    record = {'arm':arm,'answer':answer,'correct':success,'requests':state['requests_attempted'],
        'activity':state['activity'],'actual_read':any(x['tool']=='Read' and not x['is_error'] for x in state['activity']),
        'actual_grep':any(x['tool']=='Grep' and not x['is_error'] for x in state['activity'])}
    calls.report.setdefault('cold_consumer', []).append(record); calls.save()
    print(json.dumps({k:record[k] for k in ('arm','correct','requests','actual_read','actual_grep')}),flush=True)


async def scope_diagnostic(calls):
    from memory import wsc_semantic_generation as g
    from engine.abort import AbortController
    p = trial.t.p
    # Same failed specimen; separate named hypothesis, not a replacement score.
    rows = [{'id': f'noise-{i}', 'role':'assistant','content':f'Archive event {i}; completed unrelated task.'} for i in range(40)]
    rows.insert(17, {'id':'report-config','role':'user','content':'审计报告的账户标识为acct-cedar-29，校验数=85317；报告不得发布。'})
    rows.append({'id':'current-request','role':'user','content':'继续生成审计报告，账户标识和校验数以原始配置为准。'})
    visible = [{'role':'assistant','content':'当前任务是生成审计报告；账户标识和校验数在原始配置中，当前交接没有记录具体值。不得发布。'},
        {'role':'assistant','content':'Source availability: the archive contains 42 exact source records beyond this visible handoff. HandoffCatalog and HandoffSource are available only to the current compaction request; these tools are absent from the continuation tool set.'}]
    model = p.ProviderFrameModel(calls,p.e.CLIENT,'scope-fact-diagnostic',1024)
    summary = await g.generate(model,visible,AbortController(),sources=rows,account=lambda _:None,output_tokens=1024)
    calls.report['scope_diagnostic'] = {'summary':summary,'requests':model.state['counter'],
        'account_retained':'acct-cedar-29' in summary,'exact_value_retained':'85317' in summary}
    calls.save()


async def main():
    p = trial.t.p; root = ROOT/'cold-api'
    assert not root.exists(), 'No paid rerun'; root.mkdir()
    p.e.ROOT=root; p.e.CLIENT=CountedClient(api_key='not-sent',model='deepseek-flash',thinking='disabled')
    os.environ['WSC_AD_TRANSPORT']='httpx-direct'
    calls=trial.ValidatedCalls();calls.semaphore=asyncio.Semaphore(1)
    calls.report['protocol']={'scope':__doc__,'http_retries':0,'per_call_cny_max':2.5,
        'consumer_artifact':'identical fixed semantic text; same source corpus; both native Read/Grep',
        'scope_diagnostic':'Fact-only tool availability hypothesis; one reused failure sample, exploratory only',
        'three_reviews':['Observed model deferral may confuse present recall tools with future continuation.',
                         'Scope metadata states actual capability only, no directive, no source values injected.',
                         'Keep initial failure; no production prompt change without independent benefit evidence.'],
        'code_sha256':p.sha(Path(__file__).read_bytes())}
    p.e.write(root/'preflight-manifest.json',calls.report['protocol'])
    activate=configure()
    with trial.t.environment(root):
        os.environ.update(XEYO_WSC='1',XEYO_WSC_HEAD_STORE='1')
        for before,arm in [(True,'before'),(False,'after')]:
            activate(before);await consumer(calls,arm)
        activate(False);await scope_diagnostic(calls)
    calls.report['cost_estimate_cny']=sum(x['cost_estimate'] for x in calls.report['calls']);calls.save()


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');asyncio.run(main())
