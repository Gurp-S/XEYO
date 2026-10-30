"""Independent state resolution checks authored oracle; no LLM or runtime fake."""
from pathlib import Path
import sys,unittest,copy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks/deterministic_v1'))
from blackbox_matrix_cases import CASES,build,material,plan
from dataset import canonical,seal
from blackbox import score_answer,questions


def resolve(public,task,key,tick):
    eligible=[e for e in public['events'] if e['record']['record_type']=='bench.fact/1'
        and e['record']['task']==task and e['record']['key']==key
        and e['record']['valid_from']<=tick
        and (e['record']['valid_to'] is None or tick<e['record']['valid_to'])]
    if not eligible:return None
    return max(eligible,key=lambda e:(e['record']['priority'],e['seq']))['record']['value']


class MatrixCaseTests(unittest.TestCase):
    def test_predefined_answers_match_independent_public_state_machine(self):
        mapping={'authority':{'delete':('release','production_delete_allowed'),'environment':('release','environment')},
            'version-relations':{'source':('application','source_version'),'validation':('application','validation')},
            'task-switch':{'active':('workspace','active_task'),'editor':('editor','status'),'sync':('sync','status')},
            'long-distance':{'key':('application','recovery_key'),'path':('application','config_path')},
            'expiry-recovery':{'lease':('worker','lease'),'present':('artifact','present'),'historical-lease':('worker','lease')}}
        for case in CASES:
            public,oracle=build(case,seed=7,rounds=5,noise=3)
            self.assertEqual(seal(public),oracle['public_sha256'])
            for point in oracle['checkpoints']:
                tick=point['round']
                for q in point['questions']:
                    key=q['question_id']
                    if key=='current':
                        validation=resolve(public,'application','validation',tick)
                        actual=validation==dict(tested_version=resolve(public,'application','source_version',tick),artifact_id=resolve(public,'application','artifact_id',tick))
                    else:
                        task,field=mapping[case][key];actual=resolve(public,task,field,1 if key=='historical-lease' else tick)
                    self.assertEqual(q['expected'],actual,(case,tick,key))
    def test_reversal_expiry_and_wrong_relation_fail_exact_scorer(self):
        for case,key,wrong in [('authority','delete',True),('expiry-recovery','lease','lease-1'),
                ('version-relations','current',True),('version-relations','validation',dict(tested_version='v1',artifact_id='artifact-2'))]:
            _,oracle=build(case,rounds=2,noise=0);point=oracle['checkpoints'][1]
            answers=[dict(question_id=q['question_id'],value=q['expected']) for q in point['questions']]
            for answer in answers:
                if answer['question_id']==key:answer['value']=wrong
            self.assertEqual(1,score_answer(canonical(dict(answers=answers)),point)['counts']['incorrect'])
    def test_material_is_public_only_and_queries_withheld(self):
        public,oracle=build('long-distance',noise=3);saved=copy.deepcopy(public)
        items=material(public,2)
        self.assertEqual(len(items),public['checkpoints'][1]['event_count']+1)
        for item in items:
            self.assertNotIn('expected',item['content'][0]['text'])
            self.assertNotIn('question_id',item['content'][0]['text'])
        self.assertEqual(saved,public)
        self.assertTrue(all(set(q)=={'question_id','question','answer_type'} for q in questions(oracle['checkpoints'][1])['questions']))
    def test_fixed_seed_repeat_pairing_and_real_compaction_not_claimed(self):
        matrix,_=plan(rounds=2,noise=0)
        again,_=plan(rounds=2,noise=0)
        self.assertEqual(matrix,again);self.assertEqual(30,len(matrix['cells']))
        self.assertEqual('prepared_not_executed',matrix['status']);self.assertEqual(0,matrix['model_calls'])
        for case in CASES:
            rows=[c for c in matrix['cells'] if c['case']==case and c['checkpoint']==2]
            self.assertEqual(1,len({r['items_sha256'] for r in rows}))
            self.assertEqual(1,len({r['query_sha256'] for r in rows}))
        with self.assertRaises(ValueError):plan(repeats=2)
    def test_noise_cannot_override_fact_and_long_cycles_compile(self):
        for rounds in (5,10,20,50):
            public,oracle=build('expiry-recovery',rounds=rounds,noise=1)
            self.assertEqual(rounds,len(oracle['checkpoints']))
            self.assertEqual(f'lease-{rounds}' if rounds%2 else None,resolve(public,'worker','lease',rounds))
            self.assertEqual('lease-1',resolve(public,'worker','lease',1))


if __name__=='__main__':unittest.main()
