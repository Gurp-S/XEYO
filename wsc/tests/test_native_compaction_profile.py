from pathlib import Path
from tempfile import TemporaryDirectory
import base64
import json
import sys
from unittest import TestCase,main

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from native_compaction_profile import PROFILE,settings,admit_request
from native_provider_gate import ProviderGate,dispatch


class CompactionAdmissionTests(TestCase):
    def request(self,items):
        return dict(model='fixed',input=items,client_metadata={'x-codex-turn-metadata':json.dumps(dict(request_kind='compaction'))})

    def test_profile_is_opt_in_and_closed(self):
        self.assertEqual(settings(None),[])
        self.assertEqual(settings(PROFILE),['model_providers.wsc_bridge.capabilities.remote_compaction="v2"'])
        with self.assertRaises(ValueError):settings('other')
        with self.assertRaises(ValueError):settings(PROFILE,provider='unregistered')

    def test_route_and_kind_alone_do_not_prove_remote_compaction(self):
        with self.assertRaisesRegex(ValueError,'trigger_unverified'):
            admit_request(self.request([dict(type='message',role='user',content=[])]))
        self.assertEqual(admit_request(self.request([dict(type='compaction_trigger')]))['trigger_count'],1)

    def test_duplicate_or_wrong_kind_rejected(self):
        with self.assertRaises(ValueError):admit_request(self.request([dict(type='compaction_trigger')]*2))
        value=self.request([dict(type='compaction_trigger')]);value['client_metadata']={}
        with self.assertRaises(ValueError):admit_request(value)

    def test_unqualified_request_never_dispatches_and_is_archived(self):
        with TemporaryDirectory() as temp:
            gate=ProviderGate(model='fixed',max_calls=1,seconds=5,directory=Path(temp)/'gate',
                exchange=lambda raw:self.fail('upstream dispatch'),require_compaction_v2=True)
            value=self.request([dict(type='message')]);raw=json.dumps(value).encode()
            reply,error=dispatch(gate,dict(method='POST',path='/v1/responses',body=base64.b64encode(raw).decode()),1)
            self.assertEqual(reply['status'],502)
            self.assertEqual(error['code'],'native_remote_compaction_trigger_unverified')
            self.assertEqual((Path(temp)/'gate/001-request.json').read_bytes(),raw)


if __name__=='__main__':main()
