"""Every child claim filename counts; uncertain children keep full allocations."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch
import json
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'validation'))
import audit_campaign_claims as audit


class ClaimGraphChecks(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def claim(self,name,amount):
        child=self.root/name;child.mkdir();private=child/'coordinator-private';private.mkdir()
        (private/'ledger.db').touch();(child/'registration.json').write_text('{}')
        path=self.root/(name+'.claim.json')
        path.write_text(json.dumps(dict(child=str(child),limits=dict(max_total_tokens=amount,
            max_responses=amount,max_seconds=amount),registration_sha256=audit.sha(child/'registration.json'))))
        return path,child

    def fake_ledger(self,path):
        return dict(path=str(path),status='closed',terminal_event='closed',uncertain='unknown' in str(path),
            inflight=0,tickets=0,tokens=1,responses=1,active_seconds=1,response_ids=[str(path)])

    def test_arbitrary_child_claim_name_is_counted_and_unknown_reservation_retained(self):
        parent,folder=self.claim('root',100);child,_=self.claim('unknown-child',80)
        (folder/'hot-continuation-probe.claim.json').write_bytes(child.read_bytes())
        with patch.object(audit,'ledger',self.fake_ledger):value=audit.inspect_claim(parent)
        self.assertEqual(1,len(value['continuations']))
        self.assertFalse(value['all_ledgers_closed_and_certain'])
        self.assertEqual(19,value['own_remainder_after_child_reservations']['max_responses'])
        self.assertEqual(2,value['known_responses'])

    def test_three_levels_traversed(self):
        parent,folder=self.claim('root',100);child,child_folder=self.claim('child',80)
        grandchild,_=self.claim('grandchild',60)
        (folder/'controls-continuation.claim.json').write_bytes(child.read_bytes())
        (child_folder/'paired-r1-allocation.claim.json').write_bytes(grandchild.read_bytes())
        with patch.object(audit,'ledger',self.fake_ledger):value=audit.inspect_claim(parent)
        self.assertEqual(3,value['known_responses'])
        self.assertEqual(1,len(value['continuations'][0]['continuations']))

    def test_duplicate_child_identity_rejected(self):
        parent,folder=self.claim('root',100);child,_=self.claim('child',20)
        for name in ('one.claim.json','two.claim.json'):(folder/name).write_bytes(child.read_bytes())
        with patch.object(audit,'ledger',self.fake_ledger):
            with self.assertRaisesRegex(ValueError,'cycle_or_duplicate'):
                audit.inspect_claim(parent)


if __name__=='__main__':main()
