"""All accepted307 handoffs, unchanged, corrected existing byte/Read adapters."""
import asyncio
from copy import deepcopy
from pathlib import Path
import os
import sys

import evals.wsc_semantic_format_pilot as p
from evals.wsc_artifact_bytes_candidate import ExactArtifactSink
from engine.abort import AbortController
from msgtypes.message import ToolUse
from synaptic.contracts import publish
from tools.file_read_tool.file_read_tool import FileReadTool
from tools.tool_registry import ToolRegistry

ORIGINAL = p.ROOT
ROOT = ORIGINAL.parent/'wsc-factorial-consumer-correction-308'


class AccessibleSealedRead(p.SealedRead):
    def __init__(self, root, archive):
        self.path = Path(archive).resolve()
        self.root = self.path.parent
        self.registry = ToolRegistry(cwd=str(self.root))
        self.registry.register(FileReadTool(cwd=str(self.root)))


async def prepare():
    assert not ROOT.exists()
    ROOT.mkdir()
    old = p.load(ORIGINAL/'run-report.json')
    assert old['completed'] and len(old['branches']) == 18
    accepted = [deepcopy(r) for r in old['branches'] if r['accepted']]
    checks = {}
    case = p.load(ORIGINAL/'clearing_holdout/case-private.json')
    request = ToolUse('native-boundary', 'Read', {'file_path': case['archive'], 'offset': 1, 'limit': 1})
    previous = await p.SealedRead(ROOT/'branch', case['archive']).execute(request, AbortController())
    fixed = await AccessibleSealedRead(ROOT/'branch', case['archive']).execute(request, AbortController())
    assert previous.is_error and not fixed.is_error
    checks['before_outside_cwd_denied_after_allowed'] = True
    private = await AccessibleSealedRead(ROOT/'branch', case['archive']).execute(ToolUse('private', 'Read', {'file_path': str(ORIGINAL/'clearing_holdout/case-private.json')}), AbortController())
    assert private.is_error
    checks['private_oracle_denied'] = True
    sealed = publish(ROOT/'free-check/source.txt', b'original\n')
    sealed.write_bytes(b'corrupt')
    corrupt = await AccessibleSealedRead(ROOT/'branch', sealed).execute(ToolUse('corrupt', 'Read', {'file_path': str(sealed)}), AbortController())
    assert corrupt.is_error and 'digest mismatch' in str(corrupt.content)
    checks['corrupt_source_denied'] = True
    sink = ExactArtifactSink(ROOT/'free-check/artifacts')
    text = '{\n  "value": 19\n}\n'
    sink.call({'file_path': 'result.json', 'content': text})
    assert (sink.root/'result.json').read_bytes() == text.encode('utf-8')
    checks['multiline_write_exact'] = True
    p.e.write(ROOT/'preflight-manifest.json', {'scope': __doc__, 'source_run_report_sha256': p.sha((ORIGINAL/'run-report.json').read_bytes()),
        'accepted_handoffs': [{'case': r['case'], 'arm': r['arm'], 'hot_sha256': p.sha(r['hot']), 'raw_candidate_sha256': p.sha(r['raw_candidate'])} for r in accepted],
        'generation_failures_unchanged': [r for r in old['branches'] if not r['accepted']],
        'free_checks': checks, 'code_sha256': p.sha(Path(__file__).read_bytes()),
        'consumer_requests': 4, 'consumer_output_limit': 3072, 'http_retries': 0, 'new_generation_calls': 0})
    print(p.e.canonical({'preflight': checks, 'accepted': len(accepted)}), flush=True)


async def execute():
    plan = p.load(ROOT/'preflight-manifest.json')
    assert not (ROOT/'run-report.json').exists()
    assert p.sha((ORIGINAL/'run-report.json').read_bytes()) == plan['source_run_report_sha256']
    assert p.sha(Path(__file__).read_bytes()) == plan['code_sha256']
    old = p.load(ORIGINAL/'run-report.json')
    p.ROOT = ROOT
    p.e.ROOT = ROOT
    p.ArtifactSink = ExactArtifactSink
    p.SealedRead = AccessibleSealedRead
    os.environ['WSC_AD_TRANSPORT'] = 'httpx-direct'
    calls = p.StopAwareCalls()
    calls.semaphore = asyncio.Semaphore(3)
    calls.report.update(protocol=plan, branches=[])
    calls.save()
    semaphore = asyncio.Semaphore(3)

    async def branch(prior):
        async with semaphore:
            if getattr(calls, 'evaluation_stopped', False): return
            record = {k: deepcopy(prior[k]) for k in ('case', 'arm', 'accepted', 'hot', 'raw_candidate', 'generation_calls', 'representation', 'rejections', 'generation_reads')}
            record['generation_source_run'] = '307'
            calls.report['branches'].append(record)
            try:
                case = p.load(ORIGINAL/prior['case']/'case-private.json')
                assert p.sha(Path(case['archive']).read_bytes()) == case['raw_sha256']
                await p.consume(calls, case, prior['arm'], record)
            except p.EvaluationStop: record['error'] = 'evaluation_stopped'
            except Exception as exc: record['error'] = type(exc).__name__+': '+str(exc)[:600]
            finally:
                calls.save()
                print(p.e.canonical({k: record.get(k) for k in ('case', 'arm', 'grade', 'error')}), flush=True)

    await asyncio.gather(*(branch(r) for r in old['branches'] if r['accepted']))
    calls.report['completed'] = True
    calls.report['cost_estimate_cny'] = sum(c['cost_estimate'] for c in calls.report['calls'])
    calls.save()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(prepare() if sys.argv[1] == 'prepare' else execute())
