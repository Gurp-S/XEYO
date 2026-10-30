from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from native_scoped_selection_state import compare, ALGORITHM


class ScopedBindingChecks(unittest.TestCase):
    def value(self, scope='gui/src', value='a', algorithm=ALGORITHM):
        return dict(scope=scope, sha256=value * 64, algorithm=algorithm)

    def test_different_scope_is_not_a_version_mismatch(self):
        self.assertEqual(compare(self.value('workspace'), self.value('gui/src', 'b')),
            dict(status='different_scopes', equal=None))

    def test_same_scope_detects_content_equality_and_changes(self):
        self.assertEqual(compare(self.value(), self.value())['status'], 'same_content')
        self.assertEqual(compare(self.value(), self.value(value='b')), dict(status='different_content', equal=False))

    def test_algorithm_or_missing_binding_is_not_silently_equal(self):
        self.assertEqual(compare(self.value(), self.value(algorithm='other'))['equal'], None)
        with self.assertRaisesRegex(ValueError, 'binding_invalid'):
            compare({}, {})
