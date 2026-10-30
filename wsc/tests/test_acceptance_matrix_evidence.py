from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'benchmarks'))
from acceptance_matrix_v1.evidence import evaluate, seal


class MatrixEvidenceChecks(unittest.TestCase):
    def setUp(self):
        self.sources = {identity: {'data': data, 'sha256': seal(data)} for identity, data in {
            'old': {'version': 'v1', 'enabled': True},
            'current': {'version': 'v2', 'enabled': False},
            'relation': {'artifact': {'source_version': 'v2', 'tested_version': 'v1'}}}.items()}

    def claim(self, identity, value, source, path):
        return dict(assertion_id=identity, value=value, source_id=source, field_path=path)

    def test_correct_answer_and_exact_citation(self):
        result = evaluate([self.claim('version', 'v2', 'current', ['version'])], {'version': 'v2'}, self.sources)
        self.assertEqual(1, result['exact_answer_accuracy'])
        self.assertEqual(1, result['citation_byte_match_rate'])

    def test_correct_without_citation_has_zero_citation_coverage(self):
        result = evaluate([{'assertion_id': 'version', 'value': 'v2'}], {'version': 'v2'}, self.sources)
        self.assertEqual(1, result['exact_answer_accuracy'])
        self.assertEqual(0, result['citation_byte_match_rate'])
        self.assertIsNone(result['task_success'])

    def test_stale_value_with_real_citation_is_still_wrong_current_answer(self):
        result = evaluate([self.claim('version', 'v1', 'old', ['version'])], {'version': 'v2'}, self.sources)
        self.assertEqual(1, result['citation_byte_match_rate'])
        self.assertEqual(0, result['exact_answer_accuracy'])
        self.assertIsNone(result['free_text_semantic_support_rate'])

    def test_constraint_inversion_does_not_pass(self):
        result = evaluate([self.claim('enabled', True, 'current', ['enabled'])], {'enabled': False}, self.sources)
        self.assertEqual(0, result['exact_answer_accuracy'])
        self.assertEqual(0, result['citation_byte_match_rate'])

    def test_wrong_relation_field_does_not_pass(self):
        result = evaluate([self.claim('tested', 'v2', 'relation', ['artifact', 'tested_version'])],
                          {'tested': 'v1'}, self.sources)
        self.assertEqual(0, result['exact_answer_accuracy'])
        self.assertEqual(0, result['citation_byte_match_rate'])

    def test_unknown_source_and_wrong_path_fail_citation(self):
        for source, path in [('invented', ['version']), ('current', ['missing'])]:
            result = evaluate([self.claim('v', 'v2', source, path)], {'v': 'v2'}, self.sources)
            self.assertEqual(0, result['citation_byte_match_rate'])

    def test_omitting_required_assertion_cannot_shrink_denominator(self):
        result = evaluate([self.claim('v', 'v2', 'current', ['version'])], {'v': 'v2', 'e': False}, self.sources)
        self.assertEqual(2, result['required_assertions'])
        self.assertEqual(.5, result['citation_byte_match_rate'])

    def test_bool_is_not_integer_and_duplicate_claims_are_invalid(self):
        result = evaluate([self.claim('e', 0, 'current', ['enabled'])], {'e': False}, self.sources)
        self.assertEqual(0, result['exact_answer_accuracy'])
        self.assertEqual(0, result['citation_byte_match_rate'])
        claim = self.claim('e', False, 'current', ['enabled'])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            evaluate([claim, claim], {'e': False}, self.sources)

    def test_changed_source_catalog_is_rejected(self):
        self.sources['current']['data']['version'] = 'v3'
        with self.assertRaisesRegex(ValueError, 'integrity'):
            evaluate([], {'v': 'v2'}, self.sources)


if __name__ == '__main__':
    unittest.main()
