from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'experiments'), str(ROOT/'benchmarks/deterministic_v1')]
import native_blackbox_sessions as sessions


class RPC:
    profile = 'matrix-test'
    def __init__(self, *args, **kwargs):
        self.calls, self.settings, self.closed = [], kwargs['settings'], False
        self.owner = SimpleNamespace(receipt=None)
    def call(self, method, params, timeout=20):
        # Mirror NativeRPC.call: the receiver path passes a startup timeout.
        self.calls.append((method, params))
        if method == 'thread/start':
            return dict(model='model', reasoningEffort='max',
                        activePermissionProfile=dict(id=self.profile), thread=dict(path='not-used'))
        return {}
    def send(self, value):
        pass
    def close(self):
        self.closed = True
        return dict(empty_confirmed=True)


class NativePermissionChecks(unittest.TestCase):
    def run_factory(self, host_permissions=None, **kwargs):
        reg = dict(executable='fixture-exe', executable_sha256='seal', workspace=self.folder.name,
                   model='model', effort='max')
        return sessions.fresh(reg, Path(self.folder.name)/'receiver', host_permissions=host_permissions, **kwargs)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.stack = []
        for target, replacement in [('OwnedNativeRPC', RPC), ('file_hash', lambda p: 'seal'),
                ('capture_rollout', lambda p: SimpleNamespace(metadata=dict(exists=False)))]:
            mocked = patch.object(sessions, target, replacement)
            mocked.start()
            self.stack.append(mocked)
    def tearDown(self):
        for mocked in reversed(self.stack):
            mocked.stop()
        self.folder.cleanup()

    def test_default_caller_keeps_original_read_only_parameters(self):
        session = self.run_factory()
        params = next(p for m, p in session.server.calls if m == 'thread/start')
        self.assertEqual('read-only', params['sandbox'])
        self.assertNotIn('permissions', params)
        self.assertFalse((session.destination/'host-permissions.json').exists())
        session.close()

    def test_explicit_profile_is_bound_without_conflicting_legacy_sandbox(self):
        session = self.run_factory(dict(profile='matrix-test', startup_flags=['permissions.matrix-test.network.enabled=false']))
        params = next(p for m, p in session.server.calls if m == 'thread/start')
        self.assertEqual('matrix-test', params['permissions'])
        self.assertNotIn('sandbox', params)
        self.assertIn('permissions.matrix-test.network.enabled=false', session.server.settings)
        session.close()

    def test_profile_mismatch_closes_receiver(self):
        with patch.object(RPC, 'profile', 'unexpected'):
            with self.assertRaisesRegex(ValueError, 'profile_changed'):
                self.run_factory(dict(profile='matrix-test', startup_flags=[]))
        self.assertTrue((Path(self.folder.name)/'receiver/process-cleanup.json').is_file())

    def test_invalid_binding_cannot_open_process(self):
        with patch.object(sessions, 'OwnedNativeRPC') as factory:
            with self.assertRaisesRegex(ValueError, 'binding_invalid'):
                self.run_factory(dict(profile='matrix-test', startup_flags='invalid-string'))
            factory.assert_not_called()

    def test_selector_runtime_does_not_replace_permission_flags(self):
        with patch('native_selector_runtime.configure',return_value=['features.shell_tool=false']):
            session=self.run_factory(dict(profile='matrix-test',startup_flags=['permissions.matrix-test.network.enabled=false']),
                                     selector_runtime='source_selector_minimal_v1')
        self.assertIn('permissions.matrix-test.network.enabled=false',session.server.settings)
        self.assertIn('features.shell_tool=false',session.server.settings)
        session.close()


if __name__ == '__main__':
    unittest.main()
