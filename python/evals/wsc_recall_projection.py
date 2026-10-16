"""335 same semantic artifact, real-corpus publication/read/restart comparison."""
import asyncio
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2] / '_wsc_out/wsc-recall-projection-335'


def baseline(name):
    path = ROOT / 'before/python' / Path(*name.split('.')).with_suffix('.py')
    spec = importlib.util.spec_from_file_location('_baseline_' + name.replace('.', '_'), path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


async def main(arm):
    from evals.wsc_unfolded_source_ab import environment
    from evals.wsc_production_continuation import ProductionTask
    from engine.abort import AbortController
    from memory import wsc_semantic_compaction as semantic, wsc_semantic_evidence as evidence, wsc_evidence_index as index
    from memory.wsc_semantic_binding import capture
    from memory.wsc_semantic_originals import from_store
    from memory.wsc_handoff_transaction import fingerprint
    from memory import wsc_head_store as hs
    from memory.working import flush
    from tools.file_read_tool.file_read_tool import FileReadTool
    from tools.grep_tool.grep_tool import GrepTool
    from model.deepseek import DeepSeekModelClient
    if arm == 'before':
        evidence.publish = baseline('memory.wsc_semantic_evidence').publish
        index.records = baseline('memory.wsc_evidence_index').records
    result = {'arm': arm, 'cases': [], 'api_calls': 0}
    tokenizer = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash')
    with environment(ROOT / ('env-v2-' + arm)):
        os.environ.update(XEYO_WSC='1', XEYO_WSC_HEAD_STORE='1', XEYO_WSC_MEDIA_ARCHIVE='1', XEYO_MEDIA_DIR=str(ROOT/'media'))
        for name in ('long_noise_task', 'completed_waiting_authority'):
            case = json.loads((ROOT.parent/'wsc-semantic-format-307'/name/'case-private.json').read_text(encoding='utf-8'))
            # Both arms deliberately share paths; immutable source objects are reusable.
            cwd = ROOT / 'same-path-v2' / name
            assert not (cwd/'native-transcript.jsonl').exists()
            task = ProductionTask(cwd, case['rows'], session='projection335-' + name)
            task.persist(); rows = deepcopy(task.source())
            text = 'Current work and constraints remain as declared. Pending verification.'
            candidate = dict(text=text, rows=rows, cut=semantic.boundary(rows, task.working),
                previous_cursor=0, binding=capture(cwd, task.working),
                source_fingerprint=fingerprint(rows), original_rows=from_store(task.store))
            hot = semantic.publish(candidate, rows, task.working, cwd=cwd)
            rec = json.loads(hs.path_for(task.working.session_id).read_text(encoding='utf-8'))
            directory = next(Path(p) for p in rec['publication']['objects'] if '-evidence-index.' in p)
            header = json.loads(directory.read_text(encoding='utf-8').splitlines()[0])
            reader = FileReadTool(cwd=str(cwd)); grep = GrepTool(cwd=str(cwd))
            reads = []
            for path in rec['publication']['objects']:
                read = await reader.execute({'file_path': path, 'offset': 1, 'limit': 1}, AbortController())
                assert not read.is_error, str(read.content)[:200]
                reads.append(path)
            found = await grep.execute({'pattern': 'message_id', 'path': str(directory), 'output_mode': 'content', 'head_limit': 2}, AbortController())
            assert not found.is_error and 'message_id' in str(found.content), str(found.content)[:300]
            flush(task.working.session_id, task.working)
            restored = task.restart()
            assert restored.project() == hot and restored.source() == rows
            assert task.project() == hot
            from memory.token import token_len
            measurement = tokenizer.context_token_measure(tokenizer.context_input([hot[0]], []))
            count = measurement[0] if measurement else token_len(hot[0]['content'])
            result['cases'].append(dict(case=name, source_fingerprint=fingerprint(rows), semantic=text,
                hot=hot, head_bytes=len(hot[0]['content'].encode()), head_tokens_estimate=count,
                objects=rec['publication']['objects'], index_header=header, actual_reads=len(reads),
                grep_ok=True, restart_equal=True, frozen_equal=True))
            task.path.unlink()
    (ROOT / (arm + '-projection.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: [{a:c[a] for a in ('case','head_bytes','head_tokens_estimate','actual_reads','grep_ok')} for c in result[k]] if k=='cases' else result[k] for k in ('arm','cases','api_calls')}))


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1]))
