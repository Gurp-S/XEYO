from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'benchmarks'), str(ROOT/'src')]
from acceptance_matrix_v1.task_specs import build_task, SPECS
from acceptance_matrix_v1.evidence import seal, canonical
from wsc import WSC, Store
from wsc.adapters.codex import CodexCheckpointAdapter


class MatrixHistoryChecks(unittest.TestCase):
    def test_same_explicit_input_is_reproducible(self):
        for task in SPECS:
            self.assertEqual(build_task(task, public_failure_log='captured smoke', noise=2),
                             build_task(task, public_failure_log='captured smoke', noise=2))

    def test_private_answer_map_is_separate_and_source_bound(self):
        for task in SPECS:
            public, oracle = build_task(task, public_failure_log='captured smoke', noise=1)
            self.assertNotIn('expected_assertions', canonical(public))
            self.assertNotIn('oracle', canonical(public))
            self.assertEqual(seal(public), oracle['public_sha256'])
            self.assertEqual(2, oracle['expected_assertions']['revision'])
            for source in oracle['sources'].values():
                self.assertEqual(seal(source['data']), source['sha256'])
            self.assertFalse(public['history_dependency_qualified'])

    def test_local_source_import_requires_real_presentation_receipts(self):
        for task in SPECS:
            with tempfile.TemporaryDirectory() as folder:
                public, _ = build_task(task, public_failure_log='captured smoke', noise=1)
                core = WSC(Store(Path(folder)/'state.db', session_id=task, workspace=folder), access=lambda *a: True)
                batch = CodexCheckpointAdapter().import_items(public['prefix'], thread_id='fixture')
                core.ingest(batch)
                with self.assertRaisesRegex(ValueError, 'result_presentation_unknown'):
                    core.capture()
                result_ids = tuple(event.id for event in batch if event.kind == 'result')
                core.presented('import-receipt', result_ids, receiver='fixture-receiver')
                self.assertEqual(len(public['prefix']), core.capture().cut)

    def test_later_assistant_hypothesis_does_not_change_private_policy(self):
        public, oracle = build_task('T3', public_failure_log='captured smoke', noise=0)
        self.assertEqual(SPECS['T3']['latest']['deleted_rows'], oracle['expected_assertions']['deleted_rows'])
        self.assertNotEqual(SPECS['T3']['old']['deleted_rows'], oracle['expected_assertions']['deleted_rows'])
        self.assertEqual('assistant', public['prefix'][-1]['role'])

    def test_unimplemented_task_and_invalid_size_are_not_silently_substituted(self):
        for task, noise in [('T6', 1), ('T1', -1), ('T1', True)]:
            with self.assertRaisesRegex(ValueError, 'invalid'):
                build_task(task, public_failure_log='captured smoke', noise=noise)


if __name__ == '__main__':
    unittest.main()
