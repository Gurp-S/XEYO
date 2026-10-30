from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wsc import WSC,Store,Selection,Understanding,WSCError
from wsc.contracts import Event,encode
from wsc import events
from unittest.mock import patch


class ScopedQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'state.db',session_id='s',workspace=self.temp.name)
        self.old=WSC(self.store,access=lambda *a:True)
        self.fast=WSC(self.store,access=lambda *a:True,query_policy='prefix_index_v1')
        self.old.ingest([Event('call','call',{},call_id='c'),Event('result','result',{},call_id='c'),
            *[Event(f'noise-{n}','observation',{},text='noise') for n in range(50)]])
        self.old.presented('p',('result',),receiver='fixture')
    def test_equal_prefix_and_only_requested_rows_hashed(self):
        # rows() verifies the recorded digest against the stored text, so the
        # per-row hash count is the proxy for how much was actually read.
        with patch('wsc.events.sha256',wraps=events.sha256) as old:
            a=self.old.capture(cut=2)
        with patch('wsc.events.sha256',wraps=events.sha256) as fast:
            b=self.fast.capture(cut=2)
        self.assertEqual(a,b);self.assertEqual(2,old.call_count);self.assertEqual(2,fast.call_count)
    def test_projection_tracks_updates_deletes_and_duplicate_receipts(self):
        self.fast.capture(cut=2)
        self.old.presented('p2',('result',),receiver='fixture')
        with self.store.transaction() as db:db.execute('DELETE FROM presentations WHERE id=?',('p',))
        self.fast.capture(cut=2)
        with self.store.transaction() as db:db.execute('UPDATE presentations SET data=? WHERE id=?',(encode(dict(source_ids=[],receiver='fixture')),'p2'))
        with self.assertRaisesRegex(WSCError,'result_presentation_unknown'):self.fast.capture(cut=2)
        with self.assertRaisesRegex(WSCError,'result_presentation_unknown'):self.old.capture(cut=2)
    def test_remember_checks_only_named_sources_and_keeps_missing_rejection(self):
        with patch('wsc.understanding.rows',side_effect=AssertionError('full scan')):
            self.fast.remember(Understanding('supported','observation',('result',)),producer='fixture')
        with self.assertRaisesRegex(WSCError,'understanding_source_missing'):
            self.fast.remember(Understanding('unsupported','observation',('missing',)),producer='fixture')
    def test_prepare_still_rejects_in_prefix_corruption_and_pending_tools(self):
        snapshot=self.fast.capture(cut=2)
        with self.store.transaction() as db:db.execute("UPDATE events SET digest='corrupt' WHERE id='result'")
        with self.assertRaisesRegex(WSCError,'source_integrity_mismatch'):self.fast.prepare(snapshot,Selection(),producer='fixture')
        with self.assertRaisesRegex(WSCError,'pending_tool_results'):self.fast.capture(cut=1)


if __name__=='__main__':unittest.main()
