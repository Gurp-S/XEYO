"""Budget changes require new registration; observed cost cannot disappear."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from native_phase_budget import PhaseBudget
from native_evidence import FIELDS
from run_native_pair import phase


def spec(responses=12, seconds=60, tokens=10000):
    return {'phase_budget': {'max_responses': responses, 'max_seconds': seconds, 'max_total_tokens': tokens}}


class BudgetContractTests(unittest.TestCase):
    def test_legacy_response_and_compaction_caps_remain(self):
        old = PhaseBudget.resolve({}, begin=100, deadline=900, spent_responses=6)
        self.assertEqual((4, 900, None, False), (old.responses, old.deadline, old.tokens, old.explicit))
        compact = PhaseBudget.resolve({}, begin=100, deadline=900, compact=True)
        self.assertEqual(340, compact.deadline)

    def test_registered_limits_override_constants_but_not_earlier_deadline(self):
        new = PhaseBudget.resolve(spec(24, 600, 1200000), begin=100, deadline=900)
        self.assertEqual((24, 700, 1200000), (new.responses, new.deadline, new.tokens))
        self.assertEqual(110, PhaseBudget.resolve(spec(), begin=100, deadline=110).deadline)

    def test_invalid_contract_and_exhausted_entry_reject_before_inference(self):
        for value in [None, {}, {'max_responses': 3},
                      {'max_responses': True, 'max_seconds': 1, 'max_total_tokens': 1},
                      {'max_responses': 1, 'max_seconds': float('inf'), 'max_total_tokens': 1},
                      {'max_responses': 1, 'max_seconds': 1, 'max_total_tokens': 0}]:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'phase_budget_'):
                PhaseBudget.resolve({'phase_budget': value}, begin=1, deadline=100)
        with self.assertRaisesRegex(ValueError, 'legacy_spend_conflict'):
            PhaseBudget.resolve(spec(), begin=1, deadline=100, spent_responses=2)
        with self.assertRaisesRegex(ValueError, 'deadline_exhausted'):
            PhaseBudget.resolve(spec(), begin=1, deadline=1)


class PhaseBudgetIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'frozen-workspace').mkdir()

    def execute(self, name, registration, *, count=11, final_first=False, updates=True):
        cell = self.root / name
        cell.mkdir()
        path = cell / 'live.jsonl'
        path.write_bytes(b'')
        value = dict.fromkeys(FIELDS, 0)
        value.update(input_tokens=10, output_tokens=2, total_tokens=12)
        rows = [{'type': 'token_usage_record', 'payload': {
            'thread_id': 't', 'turn_id': 'turn', 'response_id': str(i), 'usage': value,
            'turn_token_usage': {k:v*i for k,v in value.items()}}} for i in range(1, count+1)]
        rows += [{'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {
            'total_token_usage': {k:v*count for k,v in value.items()}, 'last_token_usage': value}}},
                 {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'turn'}}]
        final = {'method': 'item/completed', 'params': {'threadId': 't', 'item': {
            'type': 'agentMessage', 'phase': 'final_answer', 'text': 'fixture final'}}}
        completed = {'method': 'turn/completed', 'params': {'threadId': 't', 'turn': {
            'id': 'turn', 'status': 'completed'}}}
        events = [{'method': 'thread/tokenUsage/updated', 'params': {'threadId': 't'}}] if updates else []
        events = ([final] + events if final_first else events + [final]) + [completed]
        class Server:
            def __init__(self):
                self.calls, self.events = [], iter(events)
            def call(self, method, params):
                self.calls.append(method)
                if method == 'turn/start':
                    path.write_text(''.join(json.dumps(r)+'\n' for r in rows), encoding='utf8')
                return {'turn': {'id': 'turn'}}
            def event(self, **kwargs):
                return next(self.events, completed)
        server = Server()
        reg = {'purpose': 'automatic_selection_generation_only', 'shared_request': 'fixture',
               'origin': str(self.root), 'initial_manifest': {}, 'pins': {}, **registration}
        result = phase(server, {'thread': {'id': 't', 'path': str(path)}}, reg, cell, None, time.monotonic()+60)
        return result, server.calls

    def test_same_trace_old_cap_stops_new_registered_cap_completes(self):
        old, oldcalls = self.execute('old', {})
        new, newcalls = self.execute('new', spec())
        self.assertEqual('registered_response_cap', old['failure'])
        self.assertIn('turn/interrupt', oldcalls)
        self.assertTrue(new['completed'] and new['usage_complete'])
        self.assertIsNone(new['failure'])
        self.assertNotIn('turn/interrupt', newcalls)
        self.assertEqual(old['receipts']['all_usage'], new['receipts']['all_usage'])

    def test_token_overshoot_stops_and_preserves_full_observed_cost(self):
        out, calls = self.execute('token-stop', spec(tokens=120))
        self.assertEqual('registered_token_cap', out['failure'])
        self.assertIn('turn/interrupt', calls)
        self.assertEqual(132, out['receipts']['all_usage']['total_tokens'])
        self.assertFalse(out['usage_complete'])

    def test_completed_final_at_exact_caps_is_accepted(self):
        out, calls = self.execute('exact', spec(responses=11, tokens=132), final_first=True)
        self.assertTrue(out['completed'] and out['usage_complete'])
        self.assertIsNone(out['failure'])
        self.assertNotIn('turn/interrupt', calls)

    def test_final_receipts_over_limit_detected_without_token_update(self):
        out, _ = self.execute('terminal', spec(tokens=120), updates=False)
        self.assertTrue(out['completed'] and out['usage_complete'])
        self.assertEqual('registered_token_cap', out['failure'])
        self.assertEqual(132, out['budget_observation']['observed_total_tokens'])

    def test_compaction_at_one_response_limit_needs_no_agent_final_message(self):
        cell = self.root / 'compact'
        cell.mkdir()
        path = cell / 'live.jsonl'
        value = dict.fromkeys(FIELDS, 0)
        value.update(input_tokens=10, output_tokens=2, total_tokens=12)
        receipt = {'thread_id':'t', 'turn_id':'compact', 'response_id':'one', 'usage':value,
                   'turn_token_usage':value}
        rows = [{'type':'event_msg','payload':{'type':'task_started','turn_id':'compact'}},
                {'type':'token_usage_record','payload':receipt},
                {'type':'compacted','payload':{'compaction_response_id':'one','latest_token_usage_record':receipt,
                                             'replacement_history':[]}},
                {'type':'event_msg','payload':{'type':'task_complete','turn_id':'compact'}}]
        path.write_text(''.join(json.dumps(r)+'\n' for r in rows), encoding='utf8')
        complete = {'method':'turn/completed','params':{'threadId':'t','turn':{'id':'compact','status':'completed'}}}
        class Server:
            def __init__(self):
                self.calls = []
                self.events = iter([{'method':'turn/started','params':{'threadId':'t','turn':{'id':'compact'}}},
                                    {'method':'thread/tokenUsage/updated','params':{'threadId':'t'}}, complete])
            def call(self, method, params):
                self.calls.append(method)
                return {}
            def event(self, **kwargs):
                return next(self.events, complete)
        server = Server()
        reg = {'purpose':'automatic_selection_generation_only', 'origin':str(self.root),
               'initial_manifest':{}, 'pins':{}, **spec(responses=1, tokens=12)}
        result = phase(server, {'thread':{'id':'t','path':str(path)}}, reg, cell, None,
                       time.monotonic()+60, compact=True)
        self.assertTrue(result['completed'] and result['usage_complete'], result)
        self.assertIsNone(result['failure'])
        self.assertNotIn('turn/interrupt', server.calls)


if __name__ == '__main__':
    unittest.main()
