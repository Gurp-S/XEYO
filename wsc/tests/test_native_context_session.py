"""Mapped host paths and existing stage/accounting behavior; no model requests."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'experiments')]
from native_context_session import MappedContextSession
from native_application_session import NativeApplicationSession


class Server:
    def __init__(self):
        self.calls = []
        self.events = [dict(method='item/completed', params=dict(threadId='t', turnId='turn',
            item=dict(type='agentMessage', phase='final_answer', text='fixture'))),
            dict(method='turn/completed', params=dict(threadId='t', turn=dict(id='turn', status='completed')))]

    def call(self, method, params, timeout=20):
        self.calls.append((method, params))
        return dict(turn=dict(id='turn'))

    def event(self, timeout=5):
        return self.events.pop(0)


class MappedSessionTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.actor = self.root/'actor-root'
        (self.actor/'actor').mkdir(parents=True)
        (self.actor/'actor/task.txt').write_text('source')
        self.history = self.actor/'home/.codex/sessions/test.jsonl'
        self.history.parent.mkdir(parents=True)
        self.history.write_text(json.dumps(dict(type='session_meta', payload=dict(id='t')))+'\n')
        self.opened = dict(cwd='/work/actor', model='fixed', reasoningEffort='max',
            thread=dict(id='t', path='/work/home/.codex/sessions/test.jsonl'))
        self.server = Server()
        self.cleanups = []
        self.session = MappedContextSession(dict(workspace='/work/actor', model='fixed', effort='max'),
            self.root/'session', server=self.server, opened=self.opened, actor_root=self.actor,
            cleanup=lambda server: self.cleanups.append(server) or dict(stopped=True))

    def test_paths_keep_guest_metadata_and_map_manifest(self):
        self.assertEqual(self.session.rollout_path(), self.history.resolve())
        self.assertEqual(self.session.workspace_path(), (self.actor/'actor').resolve())
        self.assertEqual(set(self.session.source_manifest()), {'task.txt'})
        self.assertEqual(self.opened['thread']['path'], '/work/home/.codex/sessions/test.jsonl')

    def test_actual_stage_uses_host_rollout_and_preserves_unknown_usage(self):
        recorded = []
        outcome = self.session.execute_stage('fixture request', self.root/'phase',
            dict(max_total_tokens=1000, max_responses=3, max_seconds=3), recorded.append)
        self.assertTrue(outcome['completed'])
        self.assertFalse(outcome['usage_complete'])
        self.assertEqual((self.root/'phase/rollout.jsonl').read_bytes(), self.history.read_bytes())
        self.assertEqual(len(recorded), 1)
        self.assertEqual([m for m,p in self.server.calls], ['turn/start'])

    def test_unmapped_baseline_fails_before_any_request(self):
        legacy = NativeApplicationSession(self.session.registration, self.root/'legacy')
        legacy.server, legacy.opened = self.server, self.opened
        with self.assertRaises(FileNotFoundError):
            legacy.execute_stage('fixture request', self.root/'baseline-phase',
                dict(max_total_tokens=1000, max_responses=3, max_seconds=3), lambda _: None)
        self.assertEqual(self.server.calls, [])

    def test_changed_owner_or_server_rejected_before_dispatch(self):
        for field in ('owner', 'cwd', 'server'):
            with self.subTest(field=field):
                original = self.opened['thread']['id'], self.opened['cwd'], self.session.server
                if field == 'owner': self.opened['thread']['id'] = 'other'
                if field == 'cwd': self.opened['cwd'] = '/work/elsewhere'
                if field == 'server': self.session.server = Server()
                with self.assertRaisesRegex(ValueError, 'owner_changed'):
                    self.session.rollout_path()
                self.opened['thread']['id'], self.opened['cwd'], self.session.server = original
        self.assertEqual(self.server.calls, [])

    def test_changed_history_and_model_rejected(self):
        self.opened['thread']['path'] = '/work/home/.codex/sessions/other.jsonl'
        with self.assertRaisesRegex(ValueError, 'history_changed'): self.session.rollout_path()
        self.opened['thread']['path'] = self.session._guest_history
        self.opened['model'] = 'other'
        with self.assertRaisesRegex(ValueError, 'model_changed'): self.session.rollout_path()

    def test_traversal_and_outside_history_rejected(self):
        for value in ('/work/actor/answers.jsonl', '/work/home/.codex/sessions/../../../private.jsonl',
                      '/work/home/.codex/sessions/test.txt', 'C:\\private.jsonl'):
            with self.subTest(value=value):
                self.opened['thread']['path'] = value
                self.session._guest_history = value
                with self.assertRaises(ValueError): self.session.rollout_path()

    def test_link_rejected(self):
        target = self.root/'other.jsonl'
        target.write_text('private')
        self.history.unlink()
        try: self.history.symlink_to(target)
        except OSError: self.skipTest('symlink unavailable')
        if not self.history.is_symlink(): self.skipTest('symlink not created')
        with self.assertRaisesRegex(ValueError, 'path_link'): self.session.rollout_path()

    def test_cleanup_once_and_retry_failure(self):
        attempts = []
        def cleanup(server):
            attempts.append(server)
            if len(attempts) == 1: raise OSError('fixture')
            return dict(stopped=True)
        self.session._cleanup = cleanup
        with self.assertRaises(OSError): self.session.close()
        self.assertFalse(self.session.closed)
        self.assertEqual(self.session.close(), dict(stopped=True))
        self.assertEqual(self.session.close(), dict(stopped=True))
        self.assertEqual(len(attempts), 2)
        with self.assertRaisesRegex(ValueError, 'closed'): self.session.rollout_path()


if __name__ == '__main__': main()
