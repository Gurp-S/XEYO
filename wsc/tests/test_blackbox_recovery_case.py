from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'benchmarks/deterministic_v1'))
from blackbox_recovery_case import build,tool_recovery_evidence
from dataset import canonical,seal


class RecoveryCaseTests(unittest.TestCase):
    def test_predeclared_target_and_current_state(self):
        public,oracle,target=build(count=8)
        self.assertEqual('build-003',target['receipt_id']);self.assertEqual(seal(public),oracle['public_sha256'])
        self.assertEqual(9,oracle['questions'][1]['expected'])
        self.assertEqual(target['nonce'],oracle['questions'][0]['expected'])
        self.assertNotIn(target['nonce'],canonical(public['delta']))
        self.assertEqual((public,oracle,target),build(count=8))
    def test_exact_tool_object_not_assistant_claim_or_wrong_receipt(self):
        _,_,target=build(count=8);source=dict(id='original',text=canonical(target));manifest={'cold_sources':{'s4':source}}
        assistant=dict(type='response_item',payload=dict(type='message',role='assistant',content=[dict(text=canonical(source))]))
        wrong={**target,'nonce':'not-original'}
        outputs=[assistant,dict(type='response_item',payload=dict(type='function_call_output',output='Output:\n'+canonical(wrong)))]
        proof=tool_recovery_evidence(outputs,manifest,source,target)
        self.assertFalse(proof['target_receipt_observed']);self.assertFalse(proof['full_source_object_observed'])
        outputs.append(dict(type='response_item',payload=dict(type='function_call_output',output='Output:\n'+canonical(source))))
        proof=tool_recovery_evidence(outputs,manifest,source,target)
        self.assertTrue(proof['target_receipt_observed']);self.assertTrue(proof['full_source_object_observed'])


if __name__=='__main__':unittest.main()
