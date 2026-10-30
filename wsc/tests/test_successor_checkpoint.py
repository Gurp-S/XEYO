"""Repeated-boundary publication retains phase history and registered cold ancestry."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'experiments'))
from test_host_checkpoint import HostCheckpointTests, message
from native_evidence import read, file_hash, digest
from native_rollout_snapshot import capture_rollout
from native_successor_checkpoint import host_origin, SuccessorHostAdapter, PendingSuccessorCheckpoint
from native_message_checkpoint import prepare_message_checkpoint
from wsc import WSCError


class SuccessorCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.f = HostCheckpointTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        f = self.f
        self.parent = f.build('parent', f.adapter())
        self.parent_path = f.root/'parent/package.json'
        origin_path = f.root/'origin.jsonl'
        origin_path.write_bytes(f.target.read_bytes())
        self.origin = host_origin(origin_path, f.target_admission, f.marker)
        self.source = f.root/'continued.jsonl'
        self.tail = [*f.marker, *self.parent['items'], message('user','new requirement'),
                     message('assistant','new observation')]
        f.write_rollout(self.source, 'target', [*f.current, *self.tail])
        self.phase = {**f.phase, 'thread_id':'target', 'rollout_sha256':file_hash(self.source)}
        self.target = f.root/'third.jsonl'
        self.marker = [message('assistant','second host observation')]
        f.write_rollout(self.target, 'third', [*f.current, *self.marker])
        self.admission = f.admit('third', f.current, self.marker)

    def adapter(self):
        return SuccessorHostAdapter(capture_rollout(self.source), self.phase, self.f.root,
            self.origin, self.parent_path, self.parent['package_digest'],
            capture_rollout(self.target), self.admission, self.marker)

    def build(self, name):
        return prepare_message_checkpoint(self.f.root/name, self.f.root, self.source, self.phase,
            self.f.receipt, self.f.root/'receipt.json', adapter=self.adapter())

    def test_successor_preserves_prior_state_and_later_task_controls(self):
        result = self.build('successor')
        self.assertEqual(self.tail, result['items'][:-1])
        self.assertEqual([{'path':str(self.parent_path.resolve()),
                          'package_digest':self.parent['package_digest']}], result['adapter']['ancestor_packages'])
        self.assertNotIn('source_registration_sha256', result['adapter']['host_context_binding'])
        self.assertEqual(digest(self.phase), result['adapter']['host_context_binding']['source_phase_sha256'])

    def test_changed_origin_or_other_thread_rejected(self):
        self.origin['sha256'] = 'changed'
        with self.assertRaisesRegex(WSCError,'successor_origin_changed'): self.adapter()
        self.origin['sha256'] = file_hash(self.origin['rollout'])
        self.phase['thread_id'] = 'other'
        with self.assertRaisesRegex(WSCError,'host_admission_identity_mismatch'): self.adapter()

    def test_parent_must_be_registered_and_actually_imported(self):
        self.parent['package_digest'] = 'changed'
        with self.assertRaisesRegex(WSCError,'successor_parent_package_changed'): self.adapter()
        self.parent = read(self.parent_path)
        self.f.write_rollout(self.source,'target', [*self.f.current,*self.f.marker,message('user','unrelated')])
        self.phase['rollout_sha256'] = file_hash(self.source)
        with self.assertRaisesRegex(WSCError,'successor_parent_not_in_source'): self.adapter()

    def test_cold_dependency_mutation_after_admission_is_detected(self):
        adapter = self.adapter()
        path = next(iter(self.parent['evidence'].values()))['file_path']
        Path(path).write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(WSCError,'successor_dependency_changed'): adapter.validate_dependencies()
        with self.assertRaisesRegex(WSCError,'successor_cold_evidence_changed'): self.adapter()

    def test_origin_with_prior_inference_cannot_be_promoted_to_bootstrap(self):
        raw = Path(self.origin['rollout']).read_text(encoding='utf-8')
        Path(self.origin['rollout']).write_text(raw+json.dumps({'type':'event_msg','payload':{'type':'task_started'}})+'\n',encoding='utf-8')
        with self.assertRaisesRegex(WSCError,'host_target_not_fresh'):
            host_origin(self.origin['rollout'],self.origin['admission'],self.origin['controls'])

    def test_origin_context_cannot_be_rewritten_in_later_archive(self):
        rows = [json.loads(line) for line in self.source.read_text(encoding='utf-8').splitlines()]
        rows[1]['payload']['cwd'] = 'changed'
        self.source.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
        self.phase['rollout_sha256'] = file_hash(self.source)
        with self.assertRaisesRegex(WSCError,'successor_origin_history_changed'): self.adapter()

    def test_dependency_change_after_publication_prevents_native_injection(self):
        area = self.f.root/'pending'
        area.mkdir()
        pending = PendingSuccessorCheckpoint(area/'checkpoint',self.f.root,self.source,self.phase,
            self.f.receipt,self.f.root/'receipt.json',origin=self.origin,
            parent_path=self.parent_path,parent_digest=self.parent['package_digest'])
        calls = []
        def inject(server, opened, items, cell):
            calls.append(deepcopy(items))
            self.f.write_rollout(self.target,'third',[*self.f.current,*items])
        def publish(*args,**kwargs):
            package = prepare_message_checkpoint(*args,**kwargs)
            Path(next(iter(self.parent['evidence'].values()))['file_path']).write_text('{}',encoding='utf-8')
            return package
        with patch('run_native_pair.import_items',side_effect=inject), \
             patch('native_host_checkpoint.prepare_message_checkpoint',side_effect=publish):
            with self.assertRaisesRegex(WSCError,'successor_dependency_changed'):
                pending.import_into(None,{'thread':{'id':'third','path':str(self.target)}},area,
                                    message('developer','current execution'))
        self.assertEqual(1,len(calls))  # host observation only

    def test_third_boundary_checks_grandparent_cold_archive(self):
        second = self.build('second')
        third_origin = host_origin(self.target,self.admission,self.marker)
        third_source = self.f.root/'third-continued.jsonl'
        self.f.write_rollout(third_source,'third', [*self.f.current,*self.marker,*second['items'],message('user','later')])
        fourth = self.f.root/'fourth.jsonl'
        self.f.write_rollout(fourth,'fourth',[*self.f.current,*self.marker])
        phase = {**self.phase,'thread_id':'third','rollout_sha256':file_hash(third_source)}
        def build_adapter():
            return SuccessorHostAdapter(capture_rollout(third_source),phase,self.f.root,third_origin,
                self.f.root/'second/package.json',second['package_digest'],capture_rollout(fourth),
                self.f.admit('fourth',self.f.current,self.marker),self.marker)
        self.assertEqual(2,len(build_adapter().ancestors))
        path = next(iter(self.parent['evidence'].values()))['file_path']
        Path(path).unlink()
        with self.assertRaises(FileNotFoundError): build_adapter()


if __name__ == '__main__': unittest.main()
