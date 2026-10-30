from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from native_fork_policy import execution_mode


class ForkPolicyChecks(unittest.TestCase):
    def test_default_retains_workspace_write(self):
        self.assertEqual(execution_mode({}), ('workspace-write', 'workspaceWrite'))

    def test_explicit_read_only(self):
        self.assertEqual(execution_mode({'sandbox': 'read-only'}), ('read-only', 'readOnly'))

    def test_unknown_mode_rejected(self):
        for value in ('full-access', None, False):
            with self.assertRaisesRegex(ValueError, 'sandbox_unregistered'):
                execution_mode({'sandbox': value})
