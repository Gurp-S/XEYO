"""Replay already-paid writes plus byte/failure contracts, zero HTTP."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

from evals.wsc_artifact_bytes_candidate import ExactArtifactSink
from evals.wsc_task_acceptance_protocol import judge, scenarios, sha

ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-artifact-byte-contracts-276')


def main():
    ROOT.mkdir(exist_ok=False)
    old_source = ROOT.parent / 'wsc-task-protocol-contracts-271/task-protocol-source.py'
    spec = importlib.util.spec_from_file_location('original_task_protocol_270', old_source)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    checks = []

    def check(name, value):
        checks.append({'name': name, 'passed': bool(value)})

    writes = json.loads((ROOT.parent / 'wsc-task-uncompressed-275/run-report.json').read_text(encoding='utf-8'))['task_results']
    task = next(s for s in scenarios() if s['case'] == 'asset_manifest')
    args = next(w for t in writes if t['case'] == task['case'] for w in t['write_attempts'])
    before = old.ArtifactSink(ROOT / 'original')
    try:
        before.call(args)
        failed = False
    except AssertionError:
        failed = True
    check('paid_original_write_reproduces_post_write_failure', failed and judge(before, task['steps'][0]['expected_artifact'])['success'])
    after = ExactArtifactSink(ROOT / 'candidate')
    receipt = after.call(args)
    raw = (after.root / 'result.json').read_bytes()
    check('same_paid_write_succeeds_byte_exact', raw == args['content'].encode('utf-8') and receipt['sha256'] == sha(raw)
          and judge(after, task['steps'][0]['expected_artifact'])['success'])
    for index, content in enumerate(('a\nb\n', 'a\r\nb\r\n', '中文\n🙂', 'a\x00b\n', '')):
        sink = ExactArtifactSink(ROOT / f'bytes-{index}')
        value = sink.call({'file_path': 'result.json', 'content': content})
        raw = (sink.root / 'result.json').read_bytes()
        check(f'byte_sequence_{index}_and_receipt', raw == content.encode('utf-8') and value['bytes'] == len(raw) and value['sha256'] == sha(raw))
    sink = ExactArtifactSink(ROOT / 'failure')
    sink.call({'file_path': 'result.json', 'content': 'original\n'})
    before_raw = (sink.root / 'result.json').read_bytes()
    with patch('rewind.service.os.replace', side_effect=OSError('controlled replace failure')):
        try:
            sink.call({'file_path': 'result.json', 'content': 'replacement\n'})
            failed = False
        except OSError:
            failed = True
    check('atomic_replace_failure_preserves_old_file', failed and (sink.root / 'result.json').read_bytes() == before_raw)
    check('failed_publication_cleans_temporary_file', not list(sink.root.glob('*.rewind.*')) and len(sink.attempts) == 2)
    wrong = ExactArtifactSink(ROOT / 'wrong')
    wrong.call({'file_path': 'result.json', 'content': '{"value":8}\n'})
    check('wrong_task_content_not_auto_repaired', not judge(wrong, {'value': 7})['success'])
    denied = ExactArtifactSink(ROOT / 'denied')
    try:
        denied.call({'file_path': '../outside.json', 'content': 'x\n'})
        blocked = False
    except ValueError:
        blocked = True
    check('scope_denial_precedes_publish_and_records_attempt', blocked and not (ROOT / 'outside.json').exists()
          and len(denied.attempts) == 1 and not judge(denied, None)['success'])
    cancelled = ExactArtifactSink(ROOT / 'cancelled')
    cancelled.call({'file_path': 'result.json', 'content': '{"value":7}\n'})
    digest = sha((cancelled.root / 'result.json').read_bytes())
    cancelled.attempts.clear()
    cancelled.call({'file_path': 'result.json', 'content': '{"value":7}\n'})
    check('unchanged_write_still_violates_cancelled_task', not judge(cancelled, None, digest)['success'])
    report = {'api_calls': 0, 'paid_model_calls_reused': 1, 'checks': checks,
              'passed': sum(c['passed'] for c in checks), 'total': len(checks),
              'nonclaim': 'Offline tool execution repair; original 275 score and continuation failure unchanged.'}
    (ROOT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for path in (Path(__file__), Path('python/evals/wsc_artifact_bytes_candidate.py'), Path('python/evals/wsc_task_acceptance_protocol.py')):
        (ROOT / path.name).write_bytes(path.read_bytes())
    print(json.dumps({k: v for k, v in report.items() if k != 'checks'}))
    assert report['passed'] == report['total']


if __name__ == '__main__':
    main()
