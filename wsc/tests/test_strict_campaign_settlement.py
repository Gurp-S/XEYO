from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase, main

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'validation'),str(ROOT/'tests')]
import settle_campaign_reservations as settlement
import test_native_turn_accounting as fixtures


class StrictSettlementChecks(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        example=fixtures.NativeTurnAccountingTests();example.setUp()
        raw=fixtures.raw(example.before+example.delta)
        proof=example.proof();self.assertTrue(proof['complete'])
        phase=dict(usage_complete=True,thread_id='thread',turn_accounting=proof,
                   receipts=proof['receipts'],rollout_sha256=proof['after']['sha256'])
        self.raw=self.root/'rollout.jsonl';self.raw.write_bytes(raw)
        self.phase=self.root/'phase-outcome.json';self.phase.write_text(json.dumps(phase))
        self.db=self.root/'ledger.db'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('CREATE TABLE events(seq INTEGER PRIMARY KEY,kind TEXT,identity TEXT,payload TEXT)')
            for kind,payload in [('reserved',{}),('settled',dict(phase=phase,result=dict(usage_complete=True)))]:
                db.execute('INSERT INTO events(kind,identity,payload) VALUES(?,?,?)',(kind,'ticket',json.dumps(payload)))
        claim=self.root/'root.claim.json';claim.write_text('{}')
        self.entry=dict(child=str(self.root),claim=str(claim),claim_sha256=settlement.sha(claim),
            registration_hash_matches_claim=True,matching_registrations=[],continuations=[],
            ledger=dict(path=str(self.db),status='closed',terminal_event='closed',uncertain=False,
                tickets=0,inflight=0,response_ids=['first','compact','last'],responses=3,tokens=36))

    def test_complete_raw_receipts_verified(self):
        proof=settlement.verify_receipts(self.entry)
        self.assertEqual(3,proof['raw_receipt_proofs'][0]['responses'])
        self.assertIn(str(self.raw),proof['source_sha256'])

    def test_closed_but_uncertain_is_not_releasable(self):
        self.entry['ledger']['uncertain']=True
        with self.assertRaisesRegex(ValueError,'not_complete'):settlement.verify_receipts(self.entry)

    def test_changed_raw_receipt_rejected(self):
        self.raw.write_bytes(self.raw.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'rollout_changed'):settlement.verify_receipts(self.entry)

    def test_totals_mismatch_is_not_zero_filled(self):
        self.entry['ledger']['tokens']=35
        with self.assertRaisesRegex(ValueError,'totals_mismatch'):settlement.verify_receipts(self.entry)

    def test_unsettled_reservation_rejected(self):
        with closing(sqlite3.connect(self.db)) as db, db:db.execute("INSERT INTO events(kind,identity,payload) VALUES('reserved','extra','{}')")
        with self.assertRaisesRegex(ValueError,'not_settled_once'):settlement.verify_receipts(self.entry)


if __name__=='__main__':main()
