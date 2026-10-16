"""Same-source offline index audit. No model/network requests or semantic score."""
import asyncio
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

from engine.abort import AbortController
from evals.wsc_production_continuation import ProductionTask, PublishedRead
from evals.wsc_unfolded_source_ab import environment
from memory import wsc_semantic_compaction as semantic, wsc_head_store as hs
from memory.token import token_len
from memory.wsc_publication import _READ
from memory.wsc_semantic_originals import from_store
from model.chunks import ModelChunk
from msgtypes.message import ToolUse

ROOT = Path(__file__).resolve().parents[2] / '_wsc_out' / 'wsc-offline-recovery-328'


def load(path): return json.loads(path.read_text(encoding='utf-8'))


class Fixed:
    context_limit = 1048576
    last_usage = None
    def __init__(self, text): self.text = text
    def for_handoff(self, max_tokens): return self
    async def stream(self, messages, tools, abort):
        yield ModelChunk(kind='text_delta', text=self.text)


async def main():
    output = ROOT / 'real-source-report.json'
    assert not output.exists(), 'immutable completed report'
    spec = importlib.util.spec_from_file_location('baseline_evidence', ROOT/'semantic-evidence-before.py')
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    generations = load(ROOT.parent/'wsc-glm-real-sources-324/run-report.json')
    report = {'paid_calls': 0, 'behavior_quality': None, 'effective_recovery_rate': None,
              'scope': __doc__, 'token_basis': 'ceil(UTF-8 bytes/4), not billing', 'cases': []}
    with environment(ROOT/'isolated'):
        os.environ.update(XEYO_WSC='1', XEYO_WSC_HEAD_STORE='1', XEYO_WSC_MEDIA_ARCHIVE='1')
        for name in ('long_noise_task', 'completed_waiting_authority'):
            case = load(ROOT.parent/'wsc-semantic-format-307'/name/'case-private.json')
            saved = next(call for call in generations['calls'] if call['label'] == name+'-A1-gen-provider-1')
            summary = saved['response']['choices'][0]['message']['content']
            task = ProductionTask(ROOT/name, case['rows'], session='evidence-328-'+name)
            source, originals = deepcopy(task.source()), from_store(task.store)
            cut = semantic.boundary(source, task.working)
            raw_before, entrance_before = baseline.publish(source, cut, task.working, task.root, original_rows=originals)
            # Every old object is retained byte-for-byte, including oversized views.
            from memory.wsc_publication import manifest
            old_objects = manifest(entrance_before, str(raw_before), str(task.root), {})['objects']
            old_bytes = {path: Path(path).read_bytes() for path in old_objects}
            candidate = await semantic.prepare(model=Fixed(summary), messages=case['common_messages'],
                source=task.source, working=task.working, abort=AbortController(), account=lambda _:None,
                persist=task.persist, cwd=task.root, original_source=lambda: from_store(task.store))
            hot = semantic.publish(candidate, source, task.working, cwd=task.root)
            head = load(hs.path_for(task.working.session_id))
            entrance = next(line for line in hot[0]['content'].split('\n') if line.startswith('证据定位目录:'))
            index_path = Path(ast.literal_eval(_READ.search(entrance).group(1)))
            entries = [json.loads(line) for line in index_path.read_text(encoding='utf-8').split('\n') if line]
            header, entries = entries[0], entries[1:]
            views = {view: Path(path).read_text(encoding='utf-8').split('\n') for view, path in header['views'].items()}
            expected = {'compression': source, 'original': originals}
            exact = 0
            for entry in entries:
                page = views[entry['view']][entry['offset']-1:entry['offset']-1+entry['limit']]
                blocks = [json.loads(line) for line in page]
                row = json.loads(''.join(block['text'] for block in blocks[1:])) if blocks[0].get('format') == 'json_chunks' else blocks[0]
                assert row == expected[entry['view']][entry['source']]
                exact += 1
            reader, reads = PublishedRead(task, head), 0
            # Executable directory plus first/last available receipt for each view.
            request = {'file_path': str(index_path), 'offset': 1, 'limit': 2}
            assert not (await reader.execute(ToolUse('index', 'Read', request), AbortController())).is_error
            reads += 1
            for view in views:
                candidates = [entry for entry in entries if entry['view'] == view and entry.get('tool_result_call_ids')]
                for entry in (candidates[:1] + candidates[-1:]):
                    result = await reader.execute(ToolUse('receipt-'+str(reads), 'Read', {
                        'file_path': header['views'][view], 'offset': entry['offset'],
                        'limit': min(2, entry['limit'])}), AbortController())
                    assert not result.is_error
                    reads += 1
            assert task.source() == source and task.restart().project() == hot
            assert all(Path(path).read_bytes() == data for path, data in old_bytes.items())
            report['cases'].append({'case': name, 'source_rows': len(source), 'index_records_exact': exact,
                'index_records_total': len(entries), 'native_read_success': reads,
                'restart_equal': True, 'old_evidence_bytes_equal': True,
                'summary_sha256': hashlib.sha256(summary.encode()).hexdigest(),
                'index_bytes': index_path.stat().st_size, 'index_entrance_tokens_estimate': token_len(entrance),
                'head_tokens_estimate': token_len(hot[0]['content']),
                'baseline_has_identity_ranges': False, 'after_has_identity_ranges': True,
                'source_sha256': case['raw_sha256']})
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__': asyncio.run(main())
