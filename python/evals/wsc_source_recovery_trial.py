"""363: reuse existing source tools on the exact sealed 362-before product.

Diagnostic capability comparison, not a production Memory integration.
"""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

from evals import wsc_minimal_recovery_trial as base
from evals.wsc_native_task_files import NativeTaskFiles
from memory.wsc_cold_locator_candidate import AddressedSources
from tools.base_tool import ToolResult

ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-source-recovery-363')
ORIGIN = ROOT.parent/'wsc-readable-evidence-362'
e = base.e


class SourceTools(NativeTaskFiles):
    archive = None

    def schemas(self):
        return [*super().schemas(), *AddressedSources.schemas()]

    async def execute(self, use, abort):
        if use.name not in {'SourceCatalog','SourceRead'}:
            return await super().execute(use, abort)
        abort.raise_if_aborted()
        try:
            result = self.archive.call(use.name, use.input)
        except ValueError as exc:
            return ToolResult(str(exc), is_error=True, error_kind='INVALID_ARGUMENT')
        return ToolResult(json.dumps(result, ensure_ascii=False, separators=(',',':')))


def archive(prepared):
    # The native publication's raw compression source is sealed and already in
    # the evidence allowlist. Neither a model path nor a private oracle selects it.
    source_bytes = ('\n'.join(json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':'))
                             for row in prepared['source'])+'\n').encode('utf-8')
    digest = base.sha(source_bytes)
    path = next(Path(name) for name in prepared['paths'] if base.sha(Path(name).read_bytes()) == digest)
    return AddressedSources(path,digest)


async def prepare():
    assert not ROOT.exists(), 'Fresh output required'
    (ROOT/'work').mkdir(parents=True)
    prepared = base.load(ORIGIN/'prepared-private.json')['before']
    hot = prepared['hot']['before']
    prepared['hot'] = {arm:deepcopy(hot) for arm in ('files','sources')}
    prepared['system'] = await base.PromptAssembler().build_system(cwd=str(ROOT/'work'), workspace_root=str(ROOT/'work'),
        model='deepseek-flash',tool_names=['Read','Grep','Write'],date_iso='2026-10-16')
    cold = archive(prepared)
    target = prepared['tasks'][1]['expected']['call_id']
    page = cold.catalog({'start':0,'limit':16,'query':target})
    result = next(row for row in page['records'] if target in row.get('tool_result_call_ids',[]))
    receipt = cold.source({'source_index':result['source'],'call_id':target,'offset':0,'limit':4096})
    assert receipt['content'].startswith(prepared['tasks'][1]['expected']['excerpt'])
    assert receipt['tool_call_id'] == target
    assert prepared['hot']['files'] == prepared['hot']['sources']
    paths = [__file__, base.__file__, 'python/evals/wsc_native_task_files.py',
             *('python/memory/'+name for name in ('wsc_cold_source_candidate.py','wsc_cold_discovery_candidate.py',
               'wsc_cold_locator_candidate.py','wsc_handoff_catalog.py','wsc_handoff_recall.py',
               'wsc_handoff_source_content.py','wsc_handoff_search.py'))]
    plan = dict(scope=__doc__, arms=['files','sources'], trajectories=8,samples_per_task=1,
        same_hot_and_tail=True,source_sha256=base.fingerprint(prepared['source']),
        summary_sha256=base.sha(prepared['summary'].encode()),summary_generation_calls=0,
        consumer_request_cap=6,output_tokens=2048,http_retries=0,per_call_cny_max=2.5,
        proposed_new_run_cost_ceiling_cny=1,tools_delta='SourceCatalog and SourceRead; existing candidate implementations',
        grading='Same exact artifact/task completion; all four read/search tool names counted in recovery.',
        reviews='docs/wsc-source-recovery-plan-2026-10-16.md',
        code_sha256={str(path):base.sha(Path(path).read_bytes()) for path in paths})
    e.write(ROOT/'prepared-private.json',prepared)
    e.write(ROOT/'preflight-manifest.json',plan)
    (ROOT/'runner.py').write_bytes(Path(__file__).read_bytes())
    (ROOT/'base-runner.py').write_bytes(Path(base.__file__).read_bytes())
    print(e.canonical({'prepared':True,'same_hot':True,'native_archive':str(cold.path)}),flush=True)


def include_source_reads(calls, task, arm):
    folder = ROOT/f"{task['name']}-{arm}-0"
    actor = base.load(folder/'actor.json')
    reads = [a for a in actor['activity'] if a['tool'] in {'Read','Grep','SourceRead','SourceCatalog'}
             and str(a['input'].get('file_path') or '') != str(ROOT/'work/result.json')]
    delivered = e.canonical([a['result'] for a in reads if not a['is_error']])
    row = calls.report['branches'][-1]
    seen = all(m in delivered for m in task['markers']) if task['cold'] else None
    row.update(evidence_calls=len(reads),triggered=bool(reads),target_evidence_delivered=seen,
               effective_recovery=bool(seen and row['artifact_correct']) if task['cold'] else None,
               source_calls=sum(a['tool'].startswith('Source') for a in reads))
    e.write(folder/'result.json',row)
    calls.save()


async def run():
    prepared,plan=base.load(ROOT/'prepared-private.json'),base.load(ROOT/'preflight-manifest.json')
    assert not (ROOT/'run-report.json').exists(), 'No paid rerun or HTTP retry'
    for path,digest in plan['code_sha256'].items(): assert base.sha(Path(path).read_bytes())==digest
    base.ROOT=e.ROOT=ROOT
    e.CLIENT=base.d.CountedClient(api_key='not-sent',model='deepseek-flash',thinking='disabled')
    calls=base.d.DiagnosticCalls()
    calls.semaphore=asyncio.Semaphore(1)
    calls.report.update(scope=__doc__,protocol=plan,branches=[])
    SourceTools.archive=archive(prepared)
    calls.save()
    try:
        for number,task in enumerate(prepared['tasks']):
            for arm in (('files','sources') if number%2==0 else ('sources','files')):
                with patch.object(base,'NativeTaskFiles',SourceTools if arm=='sources' else NativeTaskFiles):
                    await base.branch(calls,prepared,task,arm,0)
                include_source_reads(calls,task,arm)
        calls.report['completed']=True
    except Exception as exc:
        calls.report['error']=type(exc).__name__+': '+str(exc)[:400]
        raise
    finally:
        calls.report['cost_estimate_cny']=sum(row['cost_estimate'] for row in calls.report['calls'])
        calls.save()


async def main():
    with base.environment(ROOT):
        os.environ.update(XEYO_WSC='1',XEYO_WSC_HEAD_STORE='1',XEYO_WSC_SEMANTIC_HANDOFF='1',WSC_AD_TRANSPORT='httpx-direct')
        await (prepare() if sys.argv[1]=='prepare' else run())


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(main())
