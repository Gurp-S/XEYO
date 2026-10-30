from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'benchmarks'))
from acceptance_matrix_v1.chain_coordinator import ChainCoordinator
from acceptance_matrix_v1.chain_dataset import build_chain
from acceptance_matrix_v1.dispatch_budget import DispatchBudget,inspect_ledger
from acceptance_matrix_v1.evidence import seal
from acceptance_matrix_v1.phase_timing import PhaseTiming


def no_inference_record():
    return dict(completed=True,usage_complete=True,failure=None,receipts=dict(response_receipts=[]))


def scripted_phase(identity):
    usage=dict(input_tokens=1,cached_input_tokens=0,cache_write_input_tokens=0,
               output_tokens=1,reasoning_output_tokens=0,total_tokens=2)
    return dict(completed=True,usage_complete=True,failure=None,
        receipts=dict(response_receipts=[dict(response_id='scripted-only-'+identity,usage=usage)]))


class ScriptedAdapter:
    real_dispatch_qualified=False
    supports_native_thread_continuity=False
    def __init__(self,*,fail_round=None,missing_receipt_round=None):
        self.calls=[];self.fail_round=fail_round;self.missing_receipt_round=missing_receipt_round;self.closed=False
    def open(self,initial,remaining,record):
        self.calls.append(('open',len(initial)));remaining();record(no_inference_record())
    def append_events(self,items,number,remaining,record):
        self.calls.append(('append',number));remaining()
        if any(type(i) is dict and 'expected_assertions' in i for i in items):raise AssertionError('oracle leak')
    def compress(self,number,remaining,record):
        self.calls.append(('compress',number));remaining()
        if number==self.fail_round:raise ValueError('scripted failure')
        if number!=self.missing_receipt_round:record(scripted_phase('compress-'+str(number)))
        return dict(confirmed=True,scope='scripted qualification only')
    def continue_task(self,request,number,remaining,record):
        self.calls.append(('task',number));remaining();record(scripted_phase('task-'+str(number)))
        return dict(round=number,request=request)
    def close(self):self.calls.append(('close',));self.closed=True


class CoordinatorChecks(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.schedule,self.oracle=build_chain('T1')
        phases={**{f'compress-{i}':dict(max_total_tokens=100,max_responses=1,max_seconds=10) for i in range(1,7)},
                **{f'task-{i}':dict(max_total_tokens=100,max_responses=1,max_seconds=10) for i in (2,4,6)}}
        self.registration=dict(schedule_sha256=seal(self.schedule),oracle_sha256=seal(self.oracle),arm='C',
            session_semantics='logical_task',phase_limits=phases,paid_dispatch_authorized=False)
        self.ledger=DispatchBudget(self.root/'ledger.db',{'run':dict(arm='C',limits=dict(max_total_tokens=1000,
            max_responses=10,max_seconds=120),binding=dict(schedule_sha256=seal(self.schedule),oracle_sha256=seal(self.oracle)))},
            dict(max_total_tokens=1000,max_responses=10,max_seconds=120))
        self.addCleanup(self.ledger.close)

    def coordinator(self,**kwargs):
        return ChainCoordinator(self.schedule,self.oracle,self.registration,self.ledger,'run',PhaseTiming(),**kwargs)

    def evaluate(self,snapshot,oracle):
        self.assertEqual(snapshot['round'],oracle['round'])
        return dict(task_success=True,scope='scripted evaluator, not model or artifact quality')

    def test_six_boundaries_three_checkpoints_and_exact_order_without_future_oracle_input(self):
        adapter=ScriptedAdapter();coordinator=self.coordinator(qualification_only=True)
        result=coordinator.run(adapter,self.evaluate)
        self.assertTrue(result['success'],result)
        self.assertFalse(result['experimental_result']);self.assertTrue(result['qualification_only'])
        expected=[('open',len(self.schedule['initial_history']))]
        for n in range(1,7):
            expected += [('append',n),('compress',n)]
            if n in (2,4,6):expected.append(('task',n))
        expected.append(('close',));self.assertEqual(expected,adapter.calls)
        self.assertEqual(9,len(result['stages']));self.assertTrue(result['timing']['complete'])
        self.assertFalse(result['cleanup_outside_reservation'])
        with self.assertRaisesRegex(ValueError,'no_replay'):coordinator.run(adapter,self.evaluate)

    def test_unregistered_paid_or_native_session_semantics_rejected_before_open(self):
        with self.assertRaisesRegex(ValueError,'not_authorized'):self.coordinator()
        self.registration['session_semantics']='same_native_thread'
        adapter=ScriptedAdapter()
        with self.assertRaisesRegex(ValueError,'cannot_preserve'):self.coordinator(qualification_only=True).run(adapter,self.evaluate)
        self.assertEqual([],adapter.calls)

    def test_failure_retains_finished_checkpoint_and_stops_without_retry(self):
        adapter=ScriptedAdapter(fail_round=3)
        result=self.coordinator(qualification_only=True).run(adapter,self.evaluate)
        self.assertFalse(result['success']);self.assertEqual([2],[c['round'] for c in result['checkpoints']])
        self.assertEqual(1,adapter.calls.count(('compress',3)))
        self.assertNotIn(('append',4),adapter.calls);self.assertTrue(adapter.closed)
        self.assertTrue(self.ledger.snapshot()['budget']['study']['uncertain'])

    def test_missing_record_does_not_become_free_success(self):
        result=self.coordinator(qualification_only=True).run(ScriptedAdapter(missing_receipt_round=2),self.evaluate)
        self.assertFalse(result['success']);self.assertEqual([],result['checkpoints'])
        self.assertTrue(self.ledger.snapshot()['budget']['study']['uncertain'])

    def test_changed_private_oracle_rejected_before_open(self):
        self.oracle['rounds']['2']['expected_assertions']['current_state']='wrong'
        with self.assertRaisesRegex(ValueError,'oracle_binding'):self.coordinator(qualification_only=True)


if __name__=='__main__':main()
