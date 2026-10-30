from base64 import b64encode
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'src')]
from native_chain_gateway import ChainGateway,PhaseBoundSession


def frame(compact=False):
    value=dict(model='fixed',input=[dict(type='compaction_trigger')] if compact else [])
    if compact:value['client_metadata']={'x-codex-turn-metadata':json.dumps(dict(request_kind='compaction'))}
    return dict(method='POST',path='/v1/responses',body=b64encode(json.dumps(value).encode()).decode())


class GatewayChecks(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.calls=[]
        self.gateway=ChainGateway(model='fixed',max_calls=3,directory=Path(self.temp.name)/'gate',
            exchange=lambda raw:self.calls.append(raw) or (200,'application/json',b'{}'))
        self.remaining=lambda:dict(max_total_tokens=100,max_responses=1,max_seconds=10)

    def test_each_stage_gets_fresh_bound_grant_and_global_ordinals(self):
        with self.gateway.stage(compact=True,remaining=self.remaining):
            self.assertEqual(1,self.gateway.handle(frame(True))['ordinal'])
            with self.assertRaisesRegex(ValueError,'allowance_exhausted'):self.gateway.handle(frame(True))
        with self.gateway.stage(compact=False,remaining=self.remaining):
            self.assertEqual(2,self.gateway.handle(frame())['ordinal'])
        self.assertEqual(2,len(self.calls))

    def test_inactive_or_wrong_request_mode_never_reaches_provider(self):
        with self.assertRaisesRegex(ValueError,'no_active'):self.gateway.handle(frame())
        with self.gateway.stage(compact=False,remaining=self.remaining):
            with self.assertRaisesRegex(ValueError,'auto_compaction'):self.gateway.handle(frame(True))
        with self.gateway.stage(compact=True,remaining=self.remaining):
            with self.assertRaises(ValueError):self.gateway.handle(frame())
        self.assertEqual([],self.calls)

    def test_stale_budget_callback_rejected_before_exchange(self):
        def expired():raise ValueError('expired grant')
        with self.assertRaisesRegex(ValueError,'expired grant'):
            with self.gateway.stage(compact=False,remaining=expired):pass
        self.assertEqual([],self.calls)

    def test_session_requires_a_new_budget_binding_for_each_stage(self):
        gateway=self.gateway
        class Session:
            def execute_stage(self,*args,compact=False,**kwargs):return gateway.handle(frame(compact))
        session=PhaseBoundSession(Session(),gateway)
        with self.assertRaisesRegex(ValueError,'unbound'):session.execute_stage()
        session.bind_phase_budget(self.remaining);self.assertEqual(1,session.execute_stage()['ordinal'])
        with self.assertRaisesRegex(ValueError,'unbound'):session.execute_stage()


if __name__=='__main__':main()
