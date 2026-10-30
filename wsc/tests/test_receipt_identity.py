"""Receipt identity is explicit, byte-bound and opt-in through both host routes."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from native_receipt_identity import receipt_reference
from native_evidence import file_hash, save
from native_host_checkpoint import PendingHostCheckpoint
from native_successor_checkpoint import PendingSuccessorCheckpoint
from native_message_checkpoint import prepare_message_checkpoint
from run_control_continuation import prior_fact
from wsc.contracts import digest, WSCError
import test_message_checkpoint as message_fixture
import test_host_checkpoint as host_fixture
import test_successor_checkpoint as successor_fixture


class ReceiptIdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / 'receipt.json'
        self.receipt = {'source_manifest_sha256': 'manifest', 'names': ['检查'],
                        'tests': 1, 'passed': True, 'grader_sha256': 'grader'}
        save(self.path, self.receipt)

    def test_legacy_fact_is_unchanged_new_fact_explains_both_hashes(self):
        old = prior_fact(self.receipt, self.path)
        new = prior_fact(self.receipt, self.path, bind_receipt_file=True)
        self.assertEqual(old, {k: new[k] for k in old})
        self.assertNotEqual(old['receipt_sha256'], file_hash(self.path))
        self.assertEqual('canonical_json_utf8_v1', new['receipt_sha256_basis'])
        self.assertEqual(file_hash(self.path), new['receipt_file_sha256'])
        self.assertEqual('raw_file_bytes', new['receipt_file_sha256_basis'])

    def test_format_changes_keep_value_identity_but_change_byte_identity(self):
        first = receipt_reference(self.receipt, self.path)
        self.path.write_bytes(b'\xef\xbb\xbf' + json.dumps(self.receipt, ensure_ascii=True).encode())
        second = receipt_reference(self.receipt, self.path)
        self.assertEqual(first['receipt_sha256'], second['receipt_sha256'])
        self.assertNotEqual(first['receipt_file_sha256'], second['receipt_file_sha256'])

    def test_changed_receipt_and_type_changes_cannot_inherit_old_observation(self):
        for updates in ({'passed': False}, {'tests': True}, {'tests': 1.0}):
            with self.subTest(updates=updates):
                self.path.write_text(json.dumps({**self.receipt, **updates}), encoding='utf-8')
                with self.assertRaisesRegex(WSCError, 'receipt_value_mismatch'):
                    receipt_reference(self.receipt, self.path)

    def test_corrupt_or_ambiguous_files_are_not_normalized_into_valid_receipts(self):
        cases = [b'\xff', b'{"a":1,"a":1}', b'{"a":{"x":0,"\\u0078":0}}',
                 b'{"x":NaN}', b'{"x":1e9999}']
        for raw in cases:
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    receipt_reference(self.receipt, self.path)

    def test_single_read_binds_hashes_to_same_observed_bytes(self):
        original = self.path.read_bytes()
        with patch.object(Path, 'read_bytes', return_value=original) as reader:
            reference = receipt_reference(self.receipt, self.path)
        reader.assert_called_once_with()
        self.assertEqual(digest(self.receipt), reference['receipt_sha256'])
        self.assertEqual(file_hash(self.path), reference['receipt_file_sha256'])

    def test_missing_file_only_rejected_in_opt_in_mode(self):
        missing = self.root / 'absent.json'
        self.assertEqual(digest(self.receipt), prior_fact(self.receipt, missing)['receipt_sha256'])
        with self.assertRaises(FileNotFoundError):
            prior_fact(self.receipt, missing, bind_receipt_file=True)

    def test_mismatched_checkpoint_receipt_stops_before_store_or_publication(self):
        fixture = message_fixture.MessageCheckpointTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        save(fixture.root / 'receipt.json', {**fixture.receipt, 'passed': False})
        area = fixture.root / 'rejected'
        with self.assertRaisesRegex(WSCError, 'receipt_value_mismatch'):
            prepare_message_checkpoint(area, fixture.root, fixture.raw, fixture.phase,
                fixture.receipt, fixture.root / 'receipt.json', bind_receipt_file=True)
        self.assertFalse(area.exists())

    def test_both_pending_host_routes_publish_typed_receipt_observation(self):
        for successor in (False, True):
            with self.subTest(successor=successor):
                fixture = (successor_fixture.SuccessorCheckpointTests() if successor
                           else host_fixture.HostCheckpointTests())
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                f = fixture.f if successor else fixture
                save(f.root / 'receipt.json', f.receipt)
                area = f.root / 'typed-pending'
                area.mkdir()
                target = fixture.target
                identity = 'third' if successor else 'target'
                args = (area / 'checkpoint', f.root, fixture.source, fixture.phase,
                        f.receipt, f.root / 'receipt.json')
                if successor:
                    pending = PendingSuccessorCheckpoint(*args, origin=fixture.origin,
                        parent_path=fixture.parent_path, parent_digest=fixture.parent['package_digest'],
                        bind_receipt_file=True)
                else:
                    pending = PendingHostCheckpoint(*args, f.source_cell, bind_receipt_file=True)
                calls = []
                def inject(server, opened, items, cell):
                    calls.append(items)
                    f.write_rollout(target, identity, [*f.current, *items])
                with patch('run_native_pair.import_items', side_effect=inject):
                    items = pending.import_into(None, {'thread': {'id': identity, 'path': str(target)}},
                                                area, host_fixture.message('developer', 'current fact'))
                self.assertEqual(2, len(calls))
                state = json.loads(items[-2]['content'][0]['text'])
                receipt = next(json.loads(e['text']) for e in state['historical_excerpts']
                               if json.loads(e['text']).get('kind') == 'independent_named_check_observation')
                self.assertEqual(file_hash(f.root / 'receipt.json'), receipt['receipt_file_sha256'])
                self.assertEqual(digest(f.receipt), receipt['receipt_sha256'])
                self.assertEqual('canonical_json_utf8_v1', receipt['receipt_sha256_basis'])


if __name__ == '__main__':
    unittest.main()
