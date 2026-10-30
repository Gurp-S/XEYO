"""A sparse fork file is not an empty effective native history."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from native_evidence import state
from native_rollout_snapshot import capture_rollout
from native_fork_history import observe_registered_fork


class ForkHistoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.parent, self.child = self.root / 'parent.jsonl', self.root / 'child.jsonl'
        self.compacted = {'replacement_history': [{'type': 'compaction', 'encrypted_content': 'opaque-bytes'}],
                         'replacement_history_metadata': [{'client_authored': False}],
                         'retained_context': {'user_messages': ['historical-control']},
                         'resume_metadata': {'previous_turn_settings': {'model': 'fixture'}}}
        self.parent_rows = [{'type': 'session_meta', 'payload': {'id': 'parent'}},
                            {'type': 'compacted', 'payload': self.compacted}]
        raw = self.write(self.parent, self.parent_rows)
        self.base = {'thread_id': 'parent', 'end_byte_offset': len(raw), 'end_ordinal_exclusive': 2}
        self.child_rows = [{'type': 'session_meta', 'payload': {'id': 'child', 'forked_from_id': 'parent',
            'forked_from_ordinal_exclusive': 2, 'history_mode': 'paginated', 'history_base': self.base}},
            {'type': 'event_msg', 'payload': {'type': 'thread_settings_applied'}}]
        child_raw = self.write(self.child, self.child_rows)
        self.binding = {'child_sha256': sha256(child_raw).hexdigest(),
                        'parent': {**self.base, 'path': str(self.parent), 'prefix_sha256': sha256(raw).hexdigest()}}

    @staticmethod
    def write(path, rows):
        raw = ''.join(json.dumps(r) + '\n' for r in rows).encode()
        path.write_bytes(raw)
        return raw

    def refresh_child(self):
        self.binding['child_sha256'] = sha256(self.write(self.child, self.child_rows)).hexdigest()

    def observe(self):
        return observe_registered_fork(self.child, self.binding)

    def test_sparse_local_file_retains_opaque_compaction_and_all_side_metadata(self):
        self.assertEqual([], state(capture_rollout(self.child).rows))
        result = self.observe()
        self.assertEqual(self.compacted['replacement_history'], result['items'])
        self.assertEqual(self.compacted, result['latest_compaction'])
        self.assertEqual(2, result['evidence']['local_records'])
        self.assertEqual(2, result['evidence']['inherited_records'])

    def test_child_local_increment_is_retained_after_parent_context(self):
        item = {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'new requirement'}]}
        self.child_rows.append({'type': 'response_item', 'payload': item})
        self.refresh_child()
        self.assertEqual([*self.compacted['replacement_history'], item], self.observe()['items'])

    def test_parent_suffix_append_does_not_invalidate_historical_prefix(self):
        before = self.observe()
        with self.parent.open('ab') as stream:
            stream.write(b'{"type":"event_msg","payload":{"type":"later"}}\n')
        self.assertEqual(before, self.observe())

    def test_changed_child_or_parent_prefix_is_rejected(self):
        child = self.child.read_bytes()
        self.child.write_bytes(child + b'\n')
        with self.assertRaisesRegex(ValueError, 'fork_history_child_changed'): self.observe()
        self.child.write_bytes(child)
        self.parent.write_bytes(self.parent.read_bytes().replace(b'opaque-bytes', b'opaque-other'))
        with self.assertRaisesRegex(ValueError, 'fork_history_parent_prefix_changed'): self.observe()

    def test_registered_ordinal_cannot_disagree_with_physical_prefix(self):
        self.base['end_ordinal_exclusive'] = 3
        self.child_rows[0]['payload']['forked_from_ordinal_exclusive'] = 3
        self.binding['parent']['end_ordinal_exclusive'] = 3
        self.refresh_child()
        with self.assertRaisesRegex(ValueError, 'fork_history_ordinal_mismatch'): self.observe()

    def test_changed_parent_reference_is_not_trusted_from_child_alone(self):
        self.base['thread_id'] = 'unregistered'
        self.refresh_child()
        with self.assertRaisesRegex(ValueError, 'fork_history_base_mismatch'): self.observe()

    def test_truncated_parent_and_unresolved_nested_base_are_rejected(self):
        original = self.parent.read_bytes()
        self.parent.write_bytes(original[:-1])
        with self.assertRaisesRegex(ValueError, 'fork_history_prefix_truncated'): self.observe()
        self.parent_rows[0]['payload']['history_base'] = {'thread_id': 'ancestor'}
        raw = self.write(self.parent, self.parent_rows)
        self.base['end_byte_offset'] = len(raw)
        self.binding['parent'].update(end_byte_offset=len(raw), prefix_sha256=sha256(raw).hexdigest())
        self.refresh_child()
        with self.assertRaisesRegex(ValueError, 'fork_history_nested_parent_unresolved'): self.observe()


if __name__ == '__main__':
    unittest.main()
