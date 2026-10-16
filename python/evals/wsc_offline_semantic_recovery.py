"""Archived real conversations and paid handoffs; no new model quality scores.

This exercises current native render/publication/Read/restart. The D arm is a
renderer reconstruction from existing declarations, not a fresh D generation.
"""
import asyncio
from copy import deepcopy
import ast
import json
import os
from pathlib import Path
import socket
from unittest.mock import patch

from engine.abort import AbortController
from evals.wsc_production_continuation import ProductionTask, PublishedRead
from evals.wsc_unfolded_source_ab import environment
from evals import wsc_semantic_format_pilot as p
from memory import wsc_semantic_compaction as semantic, wsc_head_store as hs, wsc_projection as wp
from memory.wsc_handoff_transaction import fingerprint
from memory.wsc_publication import _READ
from msgtypes.message import Message, ToolUse

ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-offline-semantic-recovery-321')
ORIGIN = ROOT.parent/'wsc-semantic-format-307'


async def replay(case, artifact, arm):
    root = ROOT/case['case']/arm
    root.mkdir(parents=True)
    result = {'case': case['case'], 'arm': arm, 'success': False}
    with environment(root):
        os.environ.update(XEYO_WSC='1', XEYO_WSC_HEAD_STORE='1', XEYO_WSC_MEDIA_ARCHIVE='1')
        task = ProductionTask(root, case['rows'], session='offline-321-'+arm)
        task.persist()
        before = deepcopy(task.source())
        original = task.path.read_bytes()
        result['source_fingerprint'] = fingerprint(before)
        result['source_records'] = len(before)
        try:
            if arm == 'semantic_replay':
                candidate = dict(text=artifact['hot'], rows=before, cut=semantic.boundary(before, task.working),
                    previous_cursor=0, source_fingerprint=fingerprint(before))
                hot = semantic.publish(candidate, before, task.working, cwd=root)
                assert hot[0]['content'].startswith(artifact['hot'])
                result['paid_summary_sha256'] = p.sha(artifact['hot'].encode())
            else:
                hot = task.fold()['hot']
            head_path = hs.path_for(task.working.session_id)
            head_bytes = head_path.read_bytes()
            head = json.loads(head_bytes)
            objects = {name: Path(name).read_bytes() for name in head['publication']['objects']}
            assert task.source() == before and task.path.read_bytes() == original
            if arm == 'semantic_replay':
                archived = [json.loads(line) for line in Path(head['view_path']).read_text(encoding='utf-8').splitlines()]
                assert archived == before
                result['exact_source_rows'] = len(archived)
                entrance = _READ.search(head['text'][len(artifact['hot']):])
                readable = Path(ast.literal_eval(entrance.group(1)))
            else:
                readable = Path(head['view_path'])
            lines = readable.read_text(encoding='utf-8').splitlines()
            reader = PublishedRead(task, head)
            reads = []
            for offset in sorted({1, max(1, len(lines)//2), len(lines)}):
                response = await reader.execute(ToolUse('offline-read-'+str(offset), 'Read',
                    {'file_path': str(readable), 'offset': offset, 'limit': 1}), AbortController())
                exact = not response.is_error and lines[offset-1] in str(response.content)
                reads.append({'offset': offset, 'exact': exact, 'is_error': response.is_error})
            assert all(row['exact'] for row in reads)
            result['cold_reads'] = reads
            task = task.restart()
            assert task.source() == before and task.project() == hot
            result['restart_equal'] = True
            result['head_tokens_estimate'] = p.e.tokens([hot[0]])
            result['projection_tokens_estimate'] = p.e.tokens(hot)
            result['retired_region_end'] = head['region_end']
            result['a1_text_only_tokens_estimate'] = p.e.tokens([{'role':'assistant','content':artifact['hot']}])
            # No new fold is authorized by a new ordinary message or restart.
            task.store.append(Message(role='user', content='OFFLINE_APPEND_RECEIPT: source append boundary probe'))
            task.persist()
            emitted = task.project()
            assert emitted[0] == hot[0] and head_path.read_bytes() == head_bytes
            assert task.path.read_bytes().startswith(original)
            task = task.restart()
            assert task.project() == emitted
            result['append_and_restart_prefix_equal'] = True
            # A rejected publication must expose retained source, not an
            # unverifiable summary; inject refusal without altering cold bytes.
            wp._STATE.clear()
            with patch('memory.wsc_publication.validate', return_value=False):
                rejected = task.project()
            result['invalid_publication_rejects_head'] = all(row.get('content') != head['text'] for row in rejected)
            assert result['invalid_publication_rejects_head']
            result['invalid_publication_retains_source_rows'] = len(rejected) >= len(task.source())
            assert result['invalid_publication_retains_source_rows']
            wp._STATE.clear()
            task = task.restart()
            assert task.project() == emitted
            assert all(Path(name).read_bytes() == data for name,data in objects.items())
            result['cold_objects_unchanged'] = True
            result['success'] = True
            p.e.write(root/'published.json', head)
            p.e.write(root/'projection.json', hot)
        except Exception as exc:
            result['error'] = type(exc).__name__ + ': ' + str(exc)
        p.e.write(root/'result.json', result)
    return result


async def main():
    ROOT.mkdir(exist_ok=False)
    paid = p.load(ORIGIN/'run-report.json')
    report = {'scope': __doc__, 'API_calls': 0, 'new_cost_cny': 0,
        'reviews': ['Reuse existing paid text without attributing new generation quality.',
                    'Current native publication, actual Read and restart; no network and no production session mutation.',
                    'Same archived source per pair; render footprint is not semantic noninferiority or task success.'],
        'cases': []}
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('offline_network_forbidden')):
        for name in ('long_noise_task', 'completed_waiting_authority'):
            case = p.load(ORIGIN/name/'case-private.json')
            assert p.sha(Path(case['archive']).read_bytes()) == case['raw_sha256']
            artifact = next(row for row in paid['branches'] if row['case'] == name and row['arm'] == 'A1_prompt_anchor')
            assert artifact['accepted'] and isinstance(artifact['hot'], str)
            for arm in ('D_renderer', 'semantic_replay'):
                result = await replay(case, artifact, arm)
                report['cases'].append(result)
                p.e.write(ROOT/'report.json', report)
                print(json.dumps(result, ensure_ascii=False), flush=True)
    report['source_hashes'] = {str(path): p.sha(path.read_bytes()) for path in
        [Path(__file__), Path('python/memory/wsc_semantic_compaction.py'), Path('python/memory/wsc_semantic_evidence.py')]}
    p.e.write(ROOT/'report.json', report)


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(main())
