from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_application_budget import StudyBudget
from native_application_quality import settle_quality
from native_evidence import save, file_hash


def limits(tokens=100):
    return dict(max_total_tokens=tokens, max_responses=10, max_seconds=100)


def phase(rid='r1', tokens=10, complete=True):
    return dict(usage_complete=complete, failure=None,
        receipts=dict(response_receipts=[dict(response_id=rid, usage=dict(total_tokens=tokens))]))


class ApplicationBudgetChecks(unittest.TestCase):
    def test_parallel_reservations_share_study_cap(self):
        study = {**limits(120), 'max_responses': 20}
        budget = StudyBudget({'B': limits(), 'C': limits()}, study, clock=lambda: 0.)
        b, first = budget.reserve('B', limits(100))
        c, second = budget.reserve('C', limits(100))
        self.assertEqual(first['max_total_tokens'], 100)
        self.assertEqual(second['max_total_tokens'], 20)
        budget.settle(b, phase(tokens=10))
        budget.settle(c, phase('r2', tokens=10))
        self.assertEqual(budget.snapshot()['study']['tokens'], 20)

    def test_overshoot_is_fully_charged_and_stops_arm(self):
        budget = StudyBudget({'B': limits()}, limits(), clock=lambda: 0.)
        ticket, _ = budget.reserve('B', limits(10))
        result = budget.settle(ticket, phase(tokens=17))
        self.assertTrue(result['observed_overshoot'])
        self.assertEqual(budget.snapshot()['study']['tokens'], 17)
        with self.assertRaisesRegex(ValueError, 'stopped_or_active'):
            budget.reserve('B', limits())

    def test_unknown_cost_preserves_known_usage_and_stops_new_calls(self):
        budget = StudyBudget({'B': limits(), 'C': limits()}, limits(200), clock=lambda: 0.)
        ticket, _ = budget.reserve('B', limits())
        budget.settle(ticket, phase(tokens=23, complete=False))
        self.assertEqual(budget.snapshot()['study']['tokens'], 23)
        self.assertTrue(budget.snapshot()['study']['uncertain'])
        with self.assertRaisesRegex(ValueError, 'budget_unknown'):
            budget.reserve('C', limits())

    def test_duplicate_receipt_freezes_admission_without_double_charge(self):
        budget = StudyBudget({'B': limits(), 'C': limits()}, limits(200), clock=lambda: 0.)
        first, _ = budget.reserve('B', limits())
        budget.settle(first, phase(tokens=10))
        second, _ = budget.reserve('C', limits())
        with self.assertRaisesRegex(ValueError, 'response_reused'):
            budget.settle(second, phase(tokens=10))
        self.assertEqual(budget.snapshot()['study']['tokens'], 10)
        self.assertTrue(budget.snapshot()['study']['uncertain'])


class ApplicationQualityChecks(unittest.TestCase):
    def binding(self, folder):
        root = Path(folder)
        auto = root / 'C1.json'
        manual = root / 'browser-review.json'
        registration = root / 'registration.json'
        result = root / 'result.json'
        save(auto, dict(id='C1', passed=True))
        save(manual, dict(observation='Recorded actual workflow review'))
        save(registration, dict(source_manifest={'app.py': 'h1'}, package='p1', harness_manifest={'runner': 'grader'}))
        save(result, dict(status='completed_checks', stage='S8', mutation='none', selected_subset=False,
                          outcomes=[dict(id='C1', passed=True, receipt='C1.json')]))
        return dict(kind='a3', source_manifest={'app.py': 'h1'}, auxiliary={'package': 'p1'},
            registration_path=str(registration), result_path=str(result), grader_manifest={'runner': 'grader'},
            files={str(p): file_hash(p) for p in (auto, manual, registration, result)},
            automatic=[dict(id='C1', passed=True, receipt=str(auto))],
            manual=[dict(id='ui', status='pass', evidence=[str(manual)])])

    def test_automatic_success_cannot_replace_missing_browser_review(self):
        with tempfile.TemporaryDirectory() as folder:
            binding = self.binding(folder)
            binding['manual'] = []
            result = settle_quality(binding, {'app.py': 'h1'}, ['C1'], ['ui'], current_auxiliary={'package': 'p1'})
            self.assertEqual(result['status'], 'unknown')

    def test_old_source_or_package_receipt_cannot_certify_current_source(self):
        with tempfile.TemporaryDirectory() as folder:
            binding = self.binding(folder)
            for source, package in [({'app.py': 'h2'}, 'p1'), ({'app.py': 'h1'}, 'p2')]:
                result = settle_quality(binding, source, ['C1'], ['ui'], current_auxiliary={'package': package})
                self.assertEqual(result['status'], 'unknown')

    def test_complete_bound_evidence_passes_and_changed_file_does_not(self):
        with tempfile.TemporaryDirectory() as folder:
            binding = self.binding(folder)
            kwargs = dict(current_auxiliary={'package': 'p1'})
            self.assertEqual(settle_quality(binding, {'app.py': 'h1'}, ['C1'], ['ui'], **kwargs)['status'], 'passed')
            Path(binding['manual'][0]['evidence'][0]).write_text('Changed after review', encoding='utf8')
            self.assertEqual(settle_quality(binding, {'app.py': 'h1'}, ['C1'], ['ui'], **kwargs)['status'], 'unknown')

    def test_invented_extra_automatic_check_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            binding = self.binding(folder)
            binding['automatic'].append(dict(id='invented', passed=True, receipt=binding['automatic'][0]['receipt']))
            self.assertEqual(settle_quality(binding, {'app.py': 'h1'}, ['C1'], ['ui'],
                current_auxiliary={'package': 'p1'})['status'], 'unknown')

    def test_old_registered_run_cannot_be_rebound_to_current_source(self):
        with tempfile.TemporaryDirectory() as folder:
            binding = self.binding(folder)
            binding['source_manifest'] = {'app.py': 'h2'}
            self.assertEqual(settle_quality(binding, {'app.py': 'h2'}, ['C1'], ['ui'],
                current_auxiliary={'package': 'p1'})['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()
