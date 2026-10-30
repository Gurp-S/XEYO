from pathlib import Path
import sys
from unittest import TestCase, main

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'experiments'),str(ROOT/'benchmarks')]
from native_measured_chain import open_measured_session, measured_provider
from acceptance_matrix_v1.phase_timing import PhaseTiming


class Handler:
    reader=object()
    def __init__(self):self.calls=[];self.reply=object()
    def handle(self,*args,**kwargs):self.calls.append((args,kwargs));return self.reply


class Session:
    def __init__(self):self.closed=False;self.server=object();self.calls=[];self.outcome={}
    def execute_stage(self,*args,**kwargs):
        self.calls.append((args,kwargs))
        if kwargs['tool_handler']:
            self.reply=kwargs['tool_handler'].handle('event',thread_id='thread',turn_id='turn')
        args[3](self.outcome)
        return self.outcome
    def close(self):self.closed=True;return 'closed'


class MeasuredChainChecks(TestCase):
    def test_entry_arguments_receipts_and_live_state_preserved(self):
        timing=PhaseTiming();session=Session();handler=Handler();recorded=[]
        with timing.measure('full_chain'):
            wrapped=open_measured_session(lambda:session,timing)
            wrapped.fork_binding={'fixture':True}
            self.assertIs(wrapped.fork_binding,session.fork_binding)
            del wrapped.fork_binding
            self.assertFalse(hasattr(session,'fork_binding'))
            outcome=wrapped.execute_stage('request','destination',{'max_seconds':10},recorded.append,
                tool_handler=handler,output_schema={'type':'object'})
            wrapped.execute_stage('compact','next',{},recorded.append,compact=True)
            self.assertIs(session.server,wrapped.server)
            self.assertEqual('closed',wrapped.close());self.assertTrue(wrapped.closed)
        self.assertIs(session.outcome,outcome);self.assertIs(outcome,recorded[0])
        self.assertIs(handler.reply,session.reply)
        self.assertEqual([(('event',),{'thread_id':'thread','turn_id':'turn'})],handler.calls)
        self.assertEqual('request',session.calls[0][0][0])
        self.assertEqual({'type':'object'},session.calls[0][1]['output_schema'])
        self.assertTrue(timing.snapshot()['complete'])
        self.assertEqual(1,timing.snapshot()['components']['wsc.recovery_callback']['calls'])
        self.assertEqual(1,timing.snapshot()['components']['native.compaction']['calls'])

    def test_provider_bytes_and_return_identity_preserved(self):
        timing=PhaseTiming();raw=b'opaque request';result=(200,'text/event-stream',b'opaque response');seen=[]
        callback=measured_provider(lambda body:(seen.append(body),result)[1],timing)
        self.assertIs(result,callback(raw));self.assertIs(raw,seen[0])
        self.assertEqual(1,timing.snapshot()['components']['provider.http']['calls'])

    def test_factory_failure_propagates_without_retry(self):
        timing=PhaseTiming();calls=[]
        def fail():calls.append(1);raise ValueError('fixture')
        with self.assertRaisesRegex(ValueError,'fixture'):open_measured_session(fail,timing)
        self.assertEqual([1],calls)
        self.assertEqual(1,timing.snapshot()['components']['host.session_open']['errors'])

    def test_actual_mapped_stage_keeps_missing_receipts_unknown(self):
        import test_native_context_session as fixtures
        fixture=fixtures.MappedSessionTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        timing=PhaseTiming();recorded=[]
        with timing.measure('full_chain'):
            wrapped=open_measured_session(lambda:fixture.session,timing)
            outcome=wrapped.execute_stage('fixture request',fixture.root/'measured-phase',
                dict(max_total_tokens=1000,max_responses=3,max_seconds=3),recorded.append)
            wrapped.close()
        self.assertTrue(outcome['completed'])
        self.assertFalse(outcome['usage_complete'])
        self.assertEqual([outcome],recorded)
        self.assertEqual('turn/start',fixture.server.calls[0][0])
        self.assertEqual(1,len(fixture.server.calls))
        self.assertTrue(timing.snapshot()['complete'])
        self.assertEqual(1,timing.snapshot()['components']['native.task_stage']['calls'])


if __name__=='__main__':main()
