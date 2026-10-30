"""Protect unchanged native control and source-bound C-only opt-in."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_host_controls import settings
from native_evidence import file_hash


class CCompactionPolicyChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.json'
        self.source.write_text('{}', encoding='utf-8')
        self.path = self.root / 'audit.json'
        self.reg = dict(effort='max', model='fixture', executable_sha256='cli', study_arm='C')
        self.proof = dict(format='native_post_compaction_access_v1', native_session=dict(self.reg),
            same_service_and_thread=True, in_turn_compaction_receipt_bound=True, post_compaction_tool_access=True,
            same_pid_nonce_heartbeat_observed=True, all_local_usage_complete=True, cleanup_empty=True,
            inputs_sha256={'source.json': file_hash(self.source)})
        self.write_proof()

    def write_proof(self):
        self.path.write_text(json.dumps(self.proof), encoding='utf-8')
        self.reg['native_c_auto_compaction'] = dict(token_limit=96000, qualification_path=str(self.path),
            qualification_sha256=file_hash(self.path))

    def test_default_and_B_without_flag_keep_exact_startup_settings(self):
        expected = ['features.multi_agent=false', 'model_reasoning_effort="max"']
        self.assertEqual(expected, settings(dict(effort='max')))
        self.assertEqual(expected, settings(dict(effort='max', study_arm='B')))
        self.assertEqual(expected + ['model_auto_compact_token_limit=96000'], settings(self.reg))

    def test_flag_cannot_be_applied_to_B_or_relabelled_unknown_arm(self):
        for arm in ('B', None):
            self.reg['study_arm'] = arm
            with self.assertRaisesRegex(ValueError, 'requires_C_arm'):
                settings(self.reg)

    def test_unknown_usage_or_unproven_access_cannot_admit(self):
        for key in ('all_local_usage_complete', 'post_compaction_tool_access'):
            self.proof[key] = False
            self.write_proof()
            with self.assertRaisesRegex(ValueError, 'unqualified'):
                settings(self.reg)
            self.proof[key] = True

    def test_changed_source_and_different_native_cannot_reuse_qualification(self):
        self.reg['model'] = 'different'
        with self.assertRaisesRegex(ValueError, 'binding_changed'):
            settings(self.reg)
        self.reg['model'] = 'fixture'
        self.source.write_text('{"changed":true}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'source_changed'):
            settings(self.reg)


if __name__ == '__main__':
    unittest.main()
