"""Regression checks for stored-view integrity before incremental selection."""
from pathlib import Path
from unittest.mock import patch
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'experiments')]

import native_incremental_candidate as candidate
from wsc import WSC, Store, Selection
from wsc.contracts import Event, encode
from wsc.excerpts import Excerpt
from hashlib import sha256


class PreviousViewIntegrityChecks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.core = WSC(Store(self.root/'state.db', session_id='regression', workspace=str(self.root)),
                        access=lambda *args: True)
        self.core.ingest([Event('control', 'message', {'text': 'task'}, role='user', text='task'),
                          Event('receipt', 'observation', {'text': 'original receipt'}, text='original receipt')])
        snap = self.core.capture()
        excerpt = Excerpt('receipt-slice', 'receipt', (), 0, 8,
                          sha256(b'original').hexdigest(), basis='public_text')
        view = self.core.prepare(snap, Selection(source_ids=('receipt',),
            clues=({'text': 'historical interpretation', 'sources': ['receipt']},), excerpts=(excerpt,)),
            producer='test')
        from dataclasses import asdict
        self.previous = dict(session_id=snap.session_id, workspace=snap.workspace, cut=snap.cut,
            source_digest=snap.source_digest, understanding_refs=[], excerpts=[asdict(excerpt)], view_id=view)
        self.core.ingest([Event('tail', 'observation', {'text': 'new fact'}, text='new fact')])
        self.snapshot = self.core.capture()
        self.archive = self.root/'new-archive'

    def alter_body(self, alter):
        with self.core.store.transaction() as db:
            saved = json.loads(db.execute('SELECT data FROM views WHERE id=?',
                                        (self.previous['view_id'],)).fetchone()[0])
            seal = saved['digest']
            alter(saved['body'])
            self.assertEqual(seal, saved['digest'])
            db.execute('UPDATE views SET data=? WHERE id=?',
                       (encode(saved), self.previous['view_id']))

    def reject_changed_body(self, alter):
        self.alter_body(alter)
        with self.assertRaisesRegex(ValueError, '^view_integrity_mismatch$'):
            candidate.frontier(self.core, self.snapshot, self.previous, self.archive)
        self.assertFalse(self.archive.exists())

    def test_changed_clue_is_rejected_before_archive_export(self):
        self.reject_changed_body(lambda body: body['clues'][0].update(text='changed interpretation'))

    def test_changed_selected_source_is_rejected(self):
        self.reject_changed_body(lambda body: body['sources'][-1].update(text='changed receipt'))

    def test_changed_excerpt_with_same_key_is_rejected(self):
        self.reject_changed_body(lambda body: body['excerpts'][0].update(text='changed slice'))

    def test_invalid_previous_never_calls_generator_or_starts_usage(self):
        self.alter_body(lambda body: body['clues'][0].update(text='changed interpretation'))
        calls = []
        def generate(offered):
            calls.append(offered)
            raise AssertionError('generator reached with changed stored view')
        with self.assertRaisesRegex(ValueError, '^view_integrity_mismatch$'):
            candidate.prepare(self.core, self.snapshot, self.previous, self.archive, generate)
        self.assertEqual(calls, [])
        self.assertEqual(self.core.status()['usage']['attempts'], [])
        self.assertFalse(self.archive.exists())

    def test_valid_material_is_identical_to_legacy_loader(self):
        validated = candidate.frontier(self.core, self.snapshot, self.previous, self.archive)
        def legacy_load(db, view_id):
            return json.loads(db.execute('SELECT data FROM views WHERE id=?', (view_id,)).fetchone()[0])
        with patch.object(candidate, 'view_record', legacy_load, create=True):
            legacy = candidate.frontier(self.core, self.snapshot, self.previous, self.archive)
        self.assertEqual(encode(validated), encode(legacy))
        material, offered = validated
        self.assertEqual(material['previous_selection']['clues'],
                         [{'text': 'historical interpretation', 'sources': ['receipt']}])
        self.assertEqual(offered['previous_excerpts'][0]['text'], 'original')

    def test_missing_view_keeps_existing_error_code(self):
        with self.core.store.transaction() as db:
            db.execute('DELETE FROM views WHERE id=?', (self.previous['view_id'],))
        with self.assertRaisesRegex(ValueError, '^incremental_previous_view_missing$'):
            candidate.frontier(self.core, self.snapshot, self.previous, self.archive)
        self.assertFalse(self.archive.exists())


if __name__ == '__main__':
    unittest.main()
