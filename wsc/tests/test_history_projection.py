"""History reads are repeatable; returned mutable items do not alias evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from native_history_projection import project_items
from native_evidence import state


class HistoryProjectionTests(unittest.TestCase):
    def test_shared_state_entry_is_repeatable_without_editing_input(self):
        rows = [{'type': 'compacted', 'payload': {'replacement_history': []}},
                {'type': 'response_item', 'payload': {'id': 'tail'}}]
        original = deepcopy(rows)
        self.assertEqual([{'id': 'tail'}], state(rows))
        self.assertEqual([{'id': 'tail'}], state(rows))
        self.assertEqual(original, rows)

    def test_repeated_projection_does_not_duplicate_tail_or_mutate_compaction(self):
        rows = [{'type': 'compacted', 'payload': {'replacement_history': [{'type': 'compaction', 'encrypted_content': 'opaque'}]}},
                {'type': 'response_item', 'payload': {'type': 'message', 'content': [{'text': 'later'}]}}]
        original = deepcopy(rows)
        first = project_items(rows)
        self.assertEqual(2, len(first))
        self.assertEqual(first, project_items(rows))
        self.assertEqual(original, rows)

    def test_mutating_result_cannot_edit_native_message_or_opaque_source(self):
        rows = [{'type': 'compacted', 'payload': {'replacement_history': [{'encrypted_content': 'opaque'}]}},
                {'type': 'response_item', 'payload': {'content': [{'text': 'original'}]}}]
        original = deepcopy(rows)
        value = project_items(rows)
        value[0]['encrypted_content'] = 'changed'
        value[1]['content'][0]['text'] = 'changed'
        value.append({})
        self.assertEqual(original, rows)

    def test_latest_compaction_replaces_prior_history_without_changing_either(self):
        rows = [{'type': 'response_item', 'payload': {'id': 'old'}},
                {'type': 'compacted', 'payload': {'replacement_history': [{'id': 'first'}]}},
                {'type': 'response_item', 'payload': {'id': 'between'}},
                {'type': 'compacted', 'payload': {'replacement_history': [{'id': 'second'}]}},
                {'type': 'event_msg', 'payload': {'type': 'task_complete'}},
                {'type': 'response_item', 'payload': {'id': 'tail'}}]
        original = deepcopy(rows)
        self.assertEqual([{'id': 'second'}, {'id': 'tail'}], project_items(rows))
        self.assertEqual(original, rows)

    def test_plain_history_also_returns_detached_payloads(self):
        rows = [{'type': 'response_item', 'payload': {'nested': [1]}}]
        result = project_items(rows)
        result[0]['nested'].append(2)
        self.assertEqual([1], rows[0]['payload']['nested'])


if __name__ == '__main__':
    unittest.main()
