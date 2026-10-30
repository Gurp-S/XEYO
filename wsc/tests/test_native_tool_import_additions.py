from pathlib import Path
import sys
import unittest
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'experiments'))
from native_evidence import import_evidence


class NativeToolImportChecks(unittest.TestCase):
    def setUp(self):
        self.items = [dict(type='function_call', call_id='call-1', name='fixture_observe', arguments='{"source":"one"}'),
                      dict(type='function_call_output', call_id='call-1', output='{"value":2}')]
        self.observed = [dict(item, id='transport-'+str(i), internal_chat_message_metadata_passthrough={})
                         for i, item in enumerate(self.items)]

    def test_observed_transport_additions_preserve_all_supplied_values(self):
        result = import_evidence(self.observed, self.items)
        self.assertTrue(result['matched'])
        self.assertTrue(result['supplied_fields_unchanged'])
        self.assertEqual(2, len(result['native_added_fields']))

    def test_call_identity_arguments_and_output_remain_strict(self):
        for index, field in [(0, 'call_id'), (0, 'arguments'), (1, 'call_id'), (1, 'output')]:
            changed = deepcopy(self.observed)
            changed[index][field] = 'changed'
            self.assertFalse(import_evidence(changed, self.items)['matched'])

    def test_unobserved_fields_or_supplied_identity_replacement_are_rejected(self):
        changed = deepcopy(self.observed)
        changed[1]['source_status'] = 'current'
        self.assertFalse(import_evidence(changed, self.items)['matched'])
        supplied = deepcopy(self.items)
        supplied[0]['id'] = 'caller-owned-id'
        self.assertFalse(import_evidence(self.observed, supplied)['matched'])


if __name__ == '__main__':
    unittest.main()
