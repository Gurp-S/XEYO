"""Public comparison materials and actual grader/runtime identity, without inference."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from native_evidence import file_hash, read
from native_public_checks import publish_contract, check_contract, grade_public_contract


GRADER = '''from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import wsc
class Checks(unittest.TestCase):
    def test_first(self): self.assertEqual(wsc.value,1)
    def test_later(self): self.assertEqual(wsc.value,2)
'''


class PublicChecksTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.workspace = self.root / 'workspace'
        (self.workspace / 'src/wsc').mkdir(parents=True)
        (self.workspace / 'src/wsc/__init__.py').write_text('value=1\n', encoding='utf-8')
        self.grader = self.root / 'grader.py'
        self.grader.write_bytes(GRADER.encode())
        self.stages = [{'id': 'first', 'message': 'First requirement', 'methods': ['Checks.test_first']},
                       {'id': 'later', 'message': 'Later requirement', 'methods': ['Checks.test_later']}]
        self.coverage = [{'requirement': 'value follows stage', 'boundaries': 'one then two',
                         'methods': ['Checks.test_first', 'Checks.test_later']}]
        self.runtime = {'executable': str(Path(sys.executable).resolve()),
                        'executable_sha256': file_hash(sys.executable), 'version': list(sys.version_info[:3])}

    def publish(self):
        return publish_contract(self.workspace, self.grader, self.stages, self.coverage)

    def grade(self, binding, stage='first', name='grade'):
        return grade_public_contract(self.workspace, binding, stage, self.root / name, runtime=self.runtime)

    def test_all_stages_are_public_before_execution_and_cannot_be_overwritten(self):
        binding = self.publish()
        contract = check_contract(self.workspace, binding)
        self.assertEqual(self.grader.read_bytes(), (self.workspace / contract['grader']).read_bytes())
        self.assertEqual(self.stages, contract['stages'])
        self.assertEqual('public_from_initial_source', contract['visibility'])
        self.assertFalse((self.root / 'grade').exists())
        with self.assertRaises(FileExistsError): self.publish()

    def test_unknown_duplicate_unmapped_methods_stop_before_publication(self):
        for kind in ('unknown', 'duplicate', 'unmapped', 'duplicate_stage'):
            with self.subTest(kind=kind):
                stages, coverage = deepcopy(self.stages), deepcopy(self.coverage)
                if kind == 'unknown': stages[1]['methods'] = ['Checks.test_missing']
                if kind == 'duplicate': stages[1]['methods'] *= 2
                if kind == 'unmapped': coverage[0]['methods'] = ['Checks.test_first']
                if kind == 'duplicate_stage': stages[1]['id'] = 'first'
                with self.assertRaises(ValueError):
                    publish_contract(self.workspace, self.grader, stages, coverage)
                self.assertFalse((self.workspace / 'task-contract').exists())

    def test_modified_public_materials_stop_before_worker_execution(self):
        binding = self.publish()
        path = self.workspace / 'task-contract/checks.py'
        path.write_bytes(path.read_bytes() + b'\n# drift')
        with patch('native_public_checks.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'public_check_contract_files_changed'):
                self.grade(binding)
            run.assert_not_called()

    def test_actual_stage_scope_runtime_and_fixture_identity_are_bound(self):
        binding = self.publish()
        first = self.grade(binding)
        later = self.grade(binding, 'later', 'later-grade')
        self.assertTrue(first['passed'])
        self.assertFalse(later['passed'])
        for result, stage in ((first, 'first'), (later, 'later')):
            self.assertEqual(1, result['tests'])
            self.assertEqual(stage, result['contract_stage'])
            self.assertEqual(self.runtime['executable_sha256'], result['observed_runtime']['executable_sha256'])
            self.assertEqual(self.runtime['version'], result['observed_runtime']['version'])
            self.assertEqual(sys.get_int_max_str_digits(), result['observed_runtime']['int_max_str_digits'])
            self.assertEqual(file_hash(self.grader), result['executed_grader_sha256'])
            self.assertEqual(binding['contract_sha256'], result['contract_sha256'])

    def test_runtime_drift_or_unknown_stage_stops_before_execution(self):
        binding = self.publish()
        with patch('native_public_checks.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'public_check_stage_not_executable'):
                self.grade(binding, 'missing')
            self.runtime['executable_sha256'] = 'changed'
            with self.assertRaisesRegex(ValueError, 'public_check_runtime_changed'):
                self.grade(binding)
            run.assert_not_called()

    def test_worker_failure_is_archived_without_public_receipt(self):
        binding = self.publish()
        with patch('native_public_checks.subprocess.run', return_value=subprocess.CompletedProcess([], 9, '', 'failed')):
            with self.assertRaisesRegex(ValueError, 'public_check_worker_failed'):
                self.grade(binding)
        self.assertEqual('failed', (self.root / 'grade/worker-stderr.txt').read_text('utf-8'))
        self.assertFalse((self.root / 'grade/public-receipt.json').exists())

    def test_runtime_report_mismatch_cannot_become_a_passing_receipt(self):
        binding = self.publish()
        self.runtime['version'] = [3, 11, 999]
        with self.assertRaisesRegex(ValueError, 'public_check_runtime_observation_mismatch'):
            self.grade(binding)
        self.assertTrue((self.root / 'grade/receipt.json').exists())
        self.assertFalse((self.root / 'grade/public-receipt.json').exists())


if __name__ == '__main__':
    unittest.main()
