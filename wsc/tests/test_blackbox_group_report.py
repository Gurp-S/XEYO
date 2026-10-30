from pathlib import Path
import sys,unittest,tempfile,json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks/deterministic_v1'))
from blackbox_group_report import collect,paired_interval


class GroupReportTests(unittest.TestCase):
    def test_missing_cost_is_unknown_and_partial_cost_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            result=dict(status='failed_preserved',repetitions={'1':dict(status='failed_preserved')},
                ledger=dict(study=dict(tokens=7,responses=1,uncertain=False),inflight={}))
            (root/'result.json').write_text(json.dumps(result))
            area=root/'R01/native-compression';area.mkdir(parents=True)
            (area/'phase-outcome.json').write_text(json.dumps(dict(completed=True,usage_complete=True,failure=None,seconds=1,
                receipts=dict(all_usage=dict(total_tokens=7),response_receipts=[dict(response_id='r')]))))
            report=collect(root);rows={r['arm']:r for r in report['rows']}
            self.assertIsNone(rows['native']['usage']);self.assertEqual(7,rows['native']['known_partial_usage']['total_tokens'])
            self.assertIsNone(rows['wsc']['usage']);self.assertIsNone(rows['wsc']['known_partial_usage']['total_tokens'])
            self.assertIsNone(report['paired']['total_tokens_wsc_minus_native'])
    def test_intervals_resample_repetitions(self):
        self.assertIsNone(paired_interval([]))
        result=paired_interval([1,2,3]);self.assertEqual(2,result['mean']);self.assertEqual(3,result['repetitions'])
        self.assertGreaterEqual(result['empirical_bootstrap_95'][0],1);self.assertLessEqual(result['empirical_bootstrap_95'][1],3)


if __name__=='__main__':unittest.main()
