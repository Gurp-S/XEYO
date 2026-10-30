"""Verify intentional recovery/concurrency boundaries without changing states."""
from pathlib import Path
import sys,tempfile,unittest,sqlite3,subprocess
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wsc import WSC,Store,Selection,WSCError
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.adapters.callback import CallbackHost
from wsc.publication import check_evidence
from test_contracts import DurableTestHost,message


class IssueProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.core=WSC(Store(self.root/'state.db',session_id='s',workspace=str(self.root)),access=lambda *a:True)
        self.adapter=CodexCheckpointAdapter();self.items=[message('user','task')]
        self.core.ingest(self.adapter.import_items(self.items,thread_id='s'))
        self.view=self.core.prepare(self.core.capture(),Selection(),producer='fixture')
    def stage(self):return self.core.stage(self.view,directory=self.root/'exports',adapter=self.adapter)
    def test_lookup_error_does_not_erase_receipt_or_reinstall(self):
        op=self.stage();host=DurableTestHost(self.root/'host.db',self.core,self.items);host.lose_reply=True
        with self.assertRaises(TimeoutError):self.core.install(op,host)
        before=self.core.status()
        for error in (OSError('transport unavailable'),sqlite3.OperationalError('lookup database locked')):
            def lookup(key):raise error
            with self.assertRaises(type(error)):
                self.core.reconcile(op,CallbackHost(commit=lambda p:None,lookup=lookup))
            self.assertEqual(before,self.core.status())
        self.core.reconcile(op,host)
        self.assertEqual(1,host.state()['effects'])
        self.assertEqual('confirmed',self.core.status()['operations'][0]['state'])
    def test_pending_is_per_bound_store_not_process_global(self):
        self.stage()
        with self.assertRaisesRegex(WSCError,'publication_pending'):self.stage()
        other=WSC(Store(self.root/'other.db',session_id='other',workspace=str(self.root)),access=lambda *a:True)
        other.ingest(self.adapter.import_items(self.items,thread_id='other'))
        view=other.prepare(other.capture(),Selection(),producer='fixture')
        self.assertTrue(other.stage(view,directory=self.root/'other-exports',adapter=self.adapter))
    def test_legacy_archive_read_failure_can_retry_after_availability_returns(self):
        first=self.core.stage(self.view,directory=self.root/'exports',archive_directory=self.root/'objects',adapter=self.adapter)
        self.core.discard(first)
        with patch.object(Path,'read_bytes',side_effect=PermissionError('temporary read failure')):
            with self.assertRaises(PermissionError):
                self.core.stage(self.view,directory=self.root/'exports',archive_directory=self.root/'objects',adapter=self.adapter)
        self.assertIn('failed',[x['state'] for x in self.core.status()['operations']])
        op=self.core.stage(self.view,directory=self.root/'exports',archive_directory=self.root/'objects',adapter=self.adapter)
        check_evidence(self.core,self.core.package(op))
    def test_crash_while_reading_existing_object_can_discard_unsubmitted_stage(self):
        first=self.core.stage(self.view,directory=self.root/'exports',archive_directory=self.root/'objects',adapter=self.adapter)
        self.core.discard(first)
        program=self.root/'crash.py'
        program.write_text('from pathlib import Path\nimport sys,os\nsys.path.insert(0,'+repr(str(Path(__file__).resolve().parents[1]/'src'))+')\n'
            'from wsc import WSC,Store\nfrom wsc.adapters.codex import CodexCheckpointAdapter\n'
            'root=Path('+repr(str(self.root))+')\n'
            "core=WSC(Store(root/'state.db',session_id='s',workspace=str(root)),access=lambda *a:True)\n"
            'Path.read_bytes=lambda self:os._exit(73)\n'
            'core.stage('+repr(self.view)+",directory=root/'exports',archive_directory=root/'objects',adapter=CodexCheckpointAdapter())\n",encoding='utf-8')
        process=subprocess.run([sys.executable,str(program)],timeout=5,capture_output=True)
        self.assertEqual(73,process.returncode)
        pending=[x for x in self.core.status()['operations'] if x['state']=='preparing']
        self.assertEqual(1,len(pending));self.core.discard(pending[0]['id'])
        recovered=self.core.stage(self.view,directory=self.root/'exports',archive_directory=self.root/'objects',adapter=self.adapter)
        check_evidence(self.core,self.core.package(recovered))


if __name__=='__main__':unittest.main()
