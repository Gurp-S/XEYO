from pathlib import Path
import json
import tempfile
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from native_cleanup_terminal import observe, observe_final
from native_application_session import NativeApplicationSession
from native_evidence import FIELDS


class CleanupTerminalTests(unittest.TestCase):
    def test_cleanup_final_is_turn_bound_deduplicated_and_does_not_clear_failure(self):
        result=dict(completed=False,failure='registered_token_cap',finals=[])
        params=dict(threadId='t',turnId='u',item=dict(type='agentMessage',id='f',phase='final_answer',text='done'))
        self.assertFalse(observe_final(result,{**params,'turnId':'foreign'},thread_id='t',turn_id='u'))
        self.assertFalse(observe_final(result,{**params,'threadId':'foreign'},thread_id='t',turn_id='u'))
        for _ in range(2):self.assertTrue(observe_final(result,params,thread_id='t',turn_id='u'))
        params['item']['text']='changed'
        self.assertEqual(['done'],[item['text'] for item in result['finals']])
        self.assertFalse(result['completed'])
        self.assertEqual('registered_token_cap',result['failure'])

    def test_completed_during_cleanup_does_not_erase_cap_breach(self):
        result=dict(completed=False,failure='registered_token_cap')
        self.assertTrue(observe(result,dict(threadId='t',turn=dict(id='u',status='completed')),thread_id='t',turn_id='u'))
        self.assertTrue(result['completed'])
        self.assertEqual('registered_token_cap',result['failure'])

    def test_interrupt_is_not_completion_and_foreign_turn_is_ignored(self):
        result=dict(completed=False,failure='registered_token_cap')
        self.assertFalse(observe(result,dict(threadId='t',turn=dict(id='other',status='completed')),thread_id='t',turn_id='u'))
        self.assertTrue(observe(result,dict(threadId='t',turn=dict(id='u',status='interrupted')),thread_id='t',turn_id='u'))
        self.assertFalse(result['completed'])
        self.assertEqual('registered_token_cap',result['failure'])

    def test_real_session_cleanup_branch_before_after_preserves_overshoot(self):
        outputs=[]
        for enabled in (False,True):
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);work=root/'workspace';work.mkdir()
                path=root/'native.jsonl'
                meta=dict(type='session_meta',payload=dict(id='t'))
                path.write_text(json.dumps(meta)+'\n',encoding='utf-8')
                value=dict.fromkeys(FIELDS,0)
                value.update(input_tokens=20,cached_input_tokens=10,output_tokens=2,total_tokens=22)
                rows=[dict(type='event_msg',payload=dict(type='task_started',turn_id='u')),
                    dict(type='token_usage_record',payload=dict(thread_id='t',turn_id='u',response_id='r',usage=value,
                        turn_token_usage=value,thread_token_usage=value)),
                    dict(type='event_msg',payload=dict(type='token_count',info=dict(total_token_usage=value,last_token_usage=value))),
                    dict(type='event_msg',payload=dict(type='task_complete',turn_id='u'))]
                class RPC:
                    def __init__(self):
                        self.events=iter([dict(method='thread/tokenUsage/updated',params=dict(threadId='t',turnId='u')),
                            dict(method='item/completed',params=dict(threadId='t',turnId='u',item=dict(
                                type='agentMessage',id='final-1',phase='final_answer',text='done'))),
                            dict(method='turn/completed',params=dict(threadId='t',turn=dict(id='u',status='completed')))])
                    def call(self,method,params,**kwargs):
                        if method=='turn/start':
                            with path.open('a',encoding='utf-8') as stream:
                                for row in rows:stream.write(json.dumps(row)+'\n')
                            return dict(turn=dict(id='u'))
                        assert method=='turn/interrupt'
                        return {}
                    def event(self,**kwargs):return next(self.events)
                reg=dict(workspace=str(work),model='fixture',effort='max',native_cleanup_terminal_observation=enabled)
                session=NativeApplicationSession(reg,root/'session')
                session.server=RPC();session.opened=dict(thread=dict(id='t',path=str(path)))
                outcome=session.execute_stage('fixture',root/'phase',dict(max_total_tokens=10,max_responses=4,max_seconds=30),lambda result:None)
                outputs.append((outcome['completed'],outcome['failure'],outcome['receipts']['all_usage']['total_tokens'],outcome['usage_complete'],len(outcome['finals'])))
        self.assertEqual([(False,'registered_token_cap',22,True,0),(True,'registered_token_cap',22,True,1)],outputs)


if __name__=='__main__':unittest.main()
