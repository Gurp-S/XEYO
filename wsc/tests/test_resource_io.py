"""Before/after I/O and host-window experiments; no model calls."""
from pathlib import Path
from hashlib import sha256
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wsc import WSC,Store,Selection,WSCError
from wsc.resource_io import ResourceIO
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.callback import CallbackHost
from wsc.content_archive import publish_object
from wsc.publication import check_evidence
from wsc.evidence import write_once
from wsc.excerpts import Excerpt
from test_contracts import DurableTestHost,message


class ResourceIOTests(unittest.TestCase):
    def test_failed_file_sync_never_exposes_new_final_name_in_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=root/'old';new=root/'new'
            with patch('os.fsync',side_effect=OSError('injected flush failure')):
                with self.assertRaises(OSError):write_once(old,b'payload')
                with self.assertRaisesRegex(WSCError,'evidence_object_unavailable'):ResourceIO().write_once(new,b'payload')
            self.assertTrue(old.exists());self.assertFalse(new.exists())
            self.assertFalse(list(root.glob('.pending-*')))
            ResourceIO().write_once(new,b'payload')
            self.assertFalse(ResourceIO().capabilities()['power_loss_recovery_proven'])
    @unittest.skipUnless(os.name=='nt','Pinned Windows publication cache')
    def test_publication_cache_is_pinned_and_closes_before_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'object';io=ResourceIO()
            with io.publication_writer() as writer:
                writer(path,b'original');read=io.bytes_read
                writer(path,b'original');self.assertEqual(read,io.bytes_read)
                with self.assertRaisesRegex(WSCError,'evidence_object_conflict'):writer(path,b'other')
                with self.assertRaises(OSError):path.write_bytes(b'changed')
            path.write_bytes(b'changed')
            with io.publication_writer() as writer:
                with self.assertRaisesRegex(WSCError,'evidence_object_conflict'):writer(path,b'original')

    def test_streamed_hash_and_comparison_do_not_use_read_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'object';payload=b'large payload'*100000
            io=ResourceIO(chunk_bytes=4096);io.write_once(path,payload)
            with patch.object(Path,'read_bytes',side_effect=AssertionError('unbounded read')):
                io.write_once(path,payload)
                self.assertEqual(sha256(payload).hexdigest(),io.digest(path))
            self.assertFalse(list(Path(directory).glob('.pending-*')))

    def test_existing_read_failure_is_neutral_and_can_recover_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'object';io=ResourceIO();io.write_once(path,b'original')
            with patch.object(io,'equal',side_effect=PermissionError('fixture unreadable')):
                with self.assertRaisesRegex(WSCError,'evidence_object_unavailable'):io.write_once(path,b'original')
            self.assertEqual(b'original',path.read_bytes())

    def test_conflict_comparison_does_not_read_whole_object(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'object';payload=b'x'*200000;write_once(path,payload)
            with patch.object(Path,'read_bytes',side_effect=AssertionError('unbounded read')):
                write_once(path,payload)
                with self.assertRaisesRegex(WSCError,'evidence_object_conflict'):write_once(path,b'y'*200000)

    def test_stale_symlink_precheck_cannot_bypass_descriptor_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'target';outside=root/'outside';outside.write_bytes(b'original')
            try:target.symlink_to(outside)
            except OSError:self.skipTest('local symlink creation unavailable')
            # Some sandboxes accept symlink_to and create nothing; the case is
            # only meaningful when the link actually exists.
            if not os.path.lexists(target):self.skipTest('local symlink creation ignored')
            # Inject the stale precheck result possible during a replacement race.
            with patch.object(Path,'is_symlink',return_value=False):
                publish_object(target,b'original') # Baseline accepts a substituted link.
                with self.assertRaises((WSCError,OSError)):ResourceIO().write_once(target,b'original')
            self.assertEqual(b'original',outside.read_bytes())

    @unittest.skipUnless(os.name=='nt','Windows mandatory sharing lease')
    def test_host_commit_window_before_after(self):
        observations=[]
        for hardened,target_kind in ((False,'object'),(True,'object'),(False,'reference'),(True,'reference')):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);io=ResourceIO() if hardened else None
                core=WSC(Store(root/'state.db',session_id='s',workspace=str(root)),access=lambda *a:True,resource_io=io)
                adapter=CodexCheckpointAdapter();items=[message('user','task'),message('assistant','observation')]
                ids=core.ingest(adapter.import_items(items,thread_id='original'))
                live=root/'live.txt';live.write_bytes(b'observation')
                selected=Selection(excerpts=(Excerpt('live',ids[1],(),0,11,sha256(b'observation').hexdigest(),
                    basis='public_text',current_resource=str(live),current_resource_sha256=sha256(b'observation').hexdigest()),)) if target_kind=='reference' else Selection()
                view=core.prepare(core.capture(),selected,producer='fixture')
                op=core.stage(view,directory=root/'exports',adapter=adapter)
                package=core.package(op);path=live if target_kind=='reference' else Path(package['evidence'][ids[1]]['file_path'])
                host=DurableTestHost(root/'host.db',core,items)
                blocked=[]
                def commit(value):
                    try:
                        if target_kind=='reference':
                            replacement=root/'replacement.tmp';replacement.write_bytes(b'changed-after-validation');os.replace(replacement,path)
                        else:path.write_bytes(b'changed-after-validation')
                        blocked.append(False)
                    except OSError:blocked.append(True)
                    return host.install(value)
                core.install(op,CallbackHost(commit=commit,lookup=host.lookup))
                observations.append(blocked[0])
                if hardened:check_evidence(core,package)
                else:
                    with self.assertRaisesRegex(WSCError,'reference_resource_changed' if target_kind=='reference' else 'exported_source_changed'):check_evidence(core,package)
                self.assertEqual('confirmed',core.status()['operations'][0]['state'])
        self.assertEqual([False,True,False,True],observations)

    def test_archive_disappears_at_open_before_after(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'object';path.write_bytes(b'content')
            original=Path.read_bytes
            def vanished(target):
                if target==path:target.unlink()
                return original(target)
            with patch.object(Path,'read_bytes',vanished):
                with self.assertRaises(FileNotFoundError):publish_object(path,b'content')
            path.write_bytes(b'content');io=ResourceIO();open_fd=io._fd;first=True
            def delete_once(target,**kwargs):
                nonlocal first
                if Path(target)==path and first:path.unlink();first=False
                return open_fd(target,**kwargs)
            with patch.object(io,'_fd',delete_once):io.write_once(path,b'content')
            self.assertEqual(b'content',path.read_bytes())

    def test_existing_object_read_error_does_not_permanently_block_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);io=ResourceIO()
            core=WSC(Store(root/'state.db',session_id='s',workspace=str(root)),access=lambda *a:True,resource_io=io)
            adapter=CodexCheckpointAdapter();core.ingest(adapter.import_items([message('user','task')],thread_id='s'))
            view=core.prepare(core.capture(),Selection(),producer='fixture')
            first=core.stage(view,directory=root/'exports',archive_directory=root/'shared',adapter=adapter);core.discard(first)
            with patch.object(io,'equal',side_effect=PermissionError('transient read failure')):
                with self.assertRaisesRegex(WSCError,'evidence_object_unavailable'):
                    core.stage(view,directory=root/'exports',archive_directory=root/'shared',adapter=adapter)
            self.assertIn('failed',[op['state'] for op in core.status()['operations']])
            recovered=core.stage(view,directory=root/'exports',archive_directory=root/'shared',adapter=adapter)
            check_evidence(core,core.package(recovered))

    def test_post_commit_confirmation_failure_reconciles_without_second_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            core=WSC(Store(root/'state.db',session_id='s',workspace=str(root)),access=lambda *a:True)
            adapter=CodexCheckpointAdapter();items=[message('user','task')]
            core.ingest(adapter.import_items(items,thread_id='source'))
            view=core.prepare(core.capture(),Selection(),producer='fixture');op=core.stage(view,directory=root/'exports',adapter=adapter)
            host=DurableTestHost(root/'host.db',core,items)
            with patch('wsc.publication.confirm',side_effect=RuntimeError('injected local settlement failure')):
                with self.assertRaises(RuntimeError):core.install(op,host)
            self.assertEqual('recovery_required',core.status()['operations'][0]['state'])
            core.reconcile(op,host)
            self.assertEqual('confirmed',core.status()['operations'][0]['state'])
            self.assertEqual(1,host.state()['effects'])


if __name__=='__main__':unittest.main()
