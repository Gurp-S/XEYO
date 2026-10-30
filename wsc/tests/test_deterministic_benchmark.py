"""Scorer counterexamples and real WSC adapter boundary checks; no LLM."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks/deterministic_v1'))
from dataset import generate,native_items,canonical,seal
from evaluator import evaluate,state,decode
from adapters import WscReplay
from cases import lifecycle


class BenchmarkTests(unittest.TestCase):
    def setUp(self):self.public,self.oracle=generate(seed=7,rounds=2,noise=2)
    def score(self,events,round_index=1):
        checkpoint=self.public['checkpoints'][round_index]
        return evaluate(native_items(events),self.oracle['answers'][round_index],checkpoint['tick'])
    def test_full_history_exact_fields_and_long_distance(self):
        self.assertEqual(10,self.score(self.public['events'])['correct'])
        self.assertEqual(seal(self.public),self.oracle['public_sha256'])
    def test_constraint_inversion_is_incorrect_despite_same_identifier(self):
        rows=json.loads(canonical(self.public['events']))
        for row in rows:
            if row['record'].get('fact_id')=='constraint.delete_production':row['record']['value']=True
        detail={x['fact_id']:x for x in self.score(rows)['details']}
        self.assertEqual('incorrect',detail['constraint.delete_production']['verdict'])
    def test_expired_artifact_and_wrong_version_do_not_pass(self):
        first=self.public['events'][:self.public['checkpoints'][0]['event_count']]
        detail={x['fact_id']:x for x in self.score(first)['details']}
        self.assertEqual('incorrect',detail['artifact.present']['verdict'])
        self.assertEqual('incorrect',detail['source.version']['verdict'])
        self.assertEqual('undecidable',detail['temporary.lease']['verdict'])
    def test_relation_not_just_presence_of_two_facts(self):
        correct=self.score(self.public['events'])
        self.assertEqual(False,next(x['actual'] for x in correct['details'] if x['fact_id']=='validation.current'))
        rows=json.loads(canonical(self.public['events']))
        for row in rows:
            if row['record'].get('fact_id')=='test.version':row['record']['dependencies']=['wrong-resource']
        detail={x['fact_id']:x for x in self.score(rows)['details']}
        self.assertEqual('undecidable',detail['validation.current']['verdict'])
    def test_opaque_and_keywords_abstain_instead_of_passing_or_failing(self):
        items=[dict(type='compaction',encrypted_content='opaque'),
            dict(type='message',role='assistant',content=[dict(type='output_text',text='source.version v2 artifact.present false tests passed')])]
        score=evaluate(items,self.oracle['answers'][1],2)
        self.assertEqual((0,0,10),(score['correct'],score['incorrect'],score['undecidable']))
    def test_real_wsc_fixed_empty_selection_recovers_via_actual_api(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);adapter=WscReplay(root,selection_ordinals=[])
            area=root/'cell';area.mkdir()
            product=adapter.compress(self.public['events'],area,byte_limit=32768)
            self.assertEqual(10,evaluate(product['items'],self.oracle['answers'][1],2)['undecidable'])
            recovered=adapter.recover(64,32768)
            self.assertEqual([],recovered['failures'])
            self.assertEqual(10,evaluate(product['items']+recovered['items'],self.oracle['answers'][1],2)['correct'])
            self.assertGreater(recovered['io_calls'],1)
            self.assertEqual('not_executed',product['installation'])
    def test_noise_and_event_order_preserve_reference_answer(self):
        public,oracle=generate(seed=7,rounds=2,noise=80)
        self.assertEqual(self.oracle['answers'],oracle['answers'])
        self.assertEqual(10,self.score(public['events'])['correct'])

    def test_other_task_cannot_override_application_facts(self):
        rows=json.loads(canonical(self.public['events']))
        other=json.loads(canonical(rows[0]))
        other['seq']=len(rows)+100
        other['record'].update(task='other-task',value='wrong/path.py',priority=99)
        rows.append(other)
        self.assertEqual(10,self.score(rows)['correct'])

    def test_lifecycle_cases_reject_stale_artifact_and_stale_validation(self):
        for name,key in (('artifact-lifecycle','artifact.present'),('version-validation','validation.current')):
            public,oracle=lifecycle(name)
            first=public['events'][:public['checkpoints'][0]['event_count']]
            stale=evaluate(native_items(first),oracle['answers'][1],2)
            self.assertEqual('incorrect',next(x['verdict'] for x in stale['details'] if x['fact_id']==key))
            current=evaluate(native_items(public['events']),oracle['answers'][1],2)
            self.assertEqual(0,current['incorrect'])
            self.assertEqual(0,current['undecidable'])

    def test_runner_does_not_publish_oracle_or_scores_until_all_adapters_finish(self):
        import run
        observed=[]
        class PublicOnly:
            scope='test fixture, not native'
            def __init__(self,root,**kwargs):self.root=root
            def compress(self,events,area,**kwargs):
                self_outer.assertFalse((self.root.parent/'oracle.private.json').exists())
                for path in self.root.parent.rglob('result.json'):
                    self_outer.assertNotIn('hot',json.loads(path.read_text(encoding='utf-8')))
                self_outer.assertEqual({'byte_limit'},set(kwargs))
                observed.append(len(events))
                return dict(items=native_items(events),external_bytes=0,model_usage=None)
        self_outer=self
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'run'
            with patch.object(run,'WscReplay',PublicOnly),patch.object(run,'write_report'),patch.object(sys,'argv',[
                'run.py','--rounds','2','--noise','0','--adapters','wsc-fixed-selection','--out',str(output)]):
                run.main()
            self.assertEqual(2,len(observed))
            self.assertTrue((output/'oracle.private.json').is_file())
            result=json.loads((output/'results.json').read_text(encoding='utf-8'))
            self.assertTrue(all(row['hot']['correct']==10 for row in result['results']))

    def test_recovery_does_not_read_beyond_its_byte_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);adapter=WscReplay(root,selection_ordinals=[])
            area=root/'cell';area.mkdir()
            adapter.compress(self.public['events'],area,byte_limit=32768)
            result=adapter.recover(1,8)
            self.assertLessEqual(result['bytes'],8)
            self.assertEqual(['index_budget_exceeded'],result['failures'])


if __name__=='__main__':unittest.main()
