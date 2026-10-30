from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'experiments')]
from wsc import WSC, Store
from wsc.contracts import Event, Understanding, Selection, digest
from native_evidence import manifest, file_hash
from native_equivalent_selection_replay import replay


class EquivalentReplayChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        old, new = self.root / 'old', self.root / 'new'
        for work in (old, new):
            work.mkdir()
            (work / 'data.txt').write_text('same source', encoding='utf8')
        self.oldreg = dict(workspace=str(old), initial_manifest=manifest(old))
        self.newreg = dict(workspace=str(new), initial_manifest=manifest(new))
        self.db = self.root / 'old.db'
        self.core = WSC(Store(self.db, session_id='old', workspace=str(old)), access=lambda *a: True)
        self.core.ingest([Event('user', 'message', {}, role='user', text='task', control=True)])
        r = self.core.remember(Understanding('prior', 'state', ('user',)), producer='model')
        self.core.remember(Understanding('revision', 'state', ('user',), id=r['id'], expected_revision=1), producer='model')
        snap = self.core.capture()
        self.refs = [v['ref'] for v in snap.understandings]
        view = self.core.prepare(snap, Selection(('user',), tuple(self.refs)), producer='model')
        self.previous = dict(session_id='old', workspace=str(old.resolve()), cut=snap.cut,
            source_digest=snap.source_digest, view_id=view, understanding_refs=self.refs, excerpts=[])

    def run_replay(self):
        return replay(self.db, self.previous, self.oldreg, self.root / 'new.db', self.newreg, session_id='new')

    def test_preserves_record_identity_revisions_and_control_source(self):
        before = file_hash(self.db)
        new, previous, proof = self.run_replay()
        self.assertEqual(self.core.capture().events, new.capture().events)
        self.assertEqual(self.core.capture().understandings, new.capture().understandings)
        self.assertEqual(self.core.capture().control_epoch, new.capture().control_epoch)
        self.assertEqual(self.refs, previous['understanding_refs'])
        self.assertTrue(proof['selected_body_identical'])
        self.assertEqual(before, file_hash(self.db))

    def test_changed_receiver_rejected_before_database_creation(self):
        (Path(self.newreg['workspace']) / 'data.txt').write_text('different', encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'not_equivalent'):
            self.run_replay()
        self.assertFalse((self.root / 'new.db').exists())

    def test_published_state_is_not_selection_replay(self):
        from wsc.store import setmeta
        with self.core.store.transaction() as db:
            setmeta(db, 'head', self.previous['view_id'])
        with self.assertRaisesRegex(ValueError, 'unpublished_closed_state'):
            self.run_replay()
        self.assertFalse((self.root / 'new.db').exists())


if __name__ == '__main__':
    unittest.main()
