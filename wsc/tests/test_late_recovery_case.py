from pathlib import Path
import sys,json,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks/deterministic_v1'))
from late_recovery_case import build
from blackbox import questions,score_answer


class LateRecoveryCaseTests(unittest.TestCase):
    def test_ground_truth_is_late_and_not_announced_in_initial_task(self):
        public,oracle,target=build();self.assertEqual(641,len(public['prefix']))
        self.assertEqual(target,json.loads(public['prefix'][539]['content'][0]['text']))
        self.assertEqual(270,target['build_number']);self.assertEqual(321,oracle['questions'][1]['expected'])
        self.assertEqual('release.tracking/1',json.loads(public['prefix'][0]['content'][0]['text'])['record_type'])
        self.assertFalse(any('expected' in q for q in questions(oracle)['questions']))
        answer=json.dumps(dict(answers=[dict(question_id='nonce',value=target['nonce']),dict(question_id='current',value=321)]))
        self.assertEqual(2,score_answer(answer,oracle)['counts']['correct'])
        wrong=json.dumps(dict(answers=[dict(question_id='nonce',value=None),dict(question_id='current',value=320)]))
        self.assertEqual(2,score_answer(wrong,oracle)['counts']['incorrect'])
        for number in (3,256,310):
            with self.assertRaises(ValueError):build(target_number=number)


if __name__=='__main__':unittest.main()
