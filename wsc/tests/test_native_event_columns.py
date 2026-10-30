from pathlib import Path
from copy import deepcopy
import sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from native_event_columns import project,restore
from wsc.contracts import encode,digest


class EventColumnsTests(unittest.TestCase):
    def test_hot_text_identity_order_and_strict_types(self):
        rows=[dict(id='source'+str(i),seq=i,role='user' if i==0 else 'assistant',spans=[{'ref':'p'+str(i),'text':'原文'+str(i)}],flag=[False,0,None][i%3]) for i in range(100)]
        material=dict(events=rows,understandings=[{'scope':None,'text':'unverified'}]);encoded,binding=project(material)
        self.assertTrue(binding['applied']);self.assertEqual(encode(restore(encoded,binding)),encode(material))
        # Spans remain verbatim JSON values inside the representation.
        self.assertIn('原文99',encode(encoded));self.assertEqual(encoded['understandings'],material['understandings'])
        modified=deepcopy(encoded);modified['events']['event_count']+=1
        with self.assertRaisesRegex(Exception,'binding_changed'):restore(modified,binding)
        forged=deepcopy(binding);forged['represented_sha256']=digest(modified)
        with self.assertRaises(Exception):restore(modified,forged)

    def test_missing_fields_and_tiny_inputs_pass_through(self):
        for rows in ([],[{'x':1}],[{'x':None},{'y':None}]):
            original=dict(events=rows);encoded,binding=project(original)
            self.assertFalse(binding['applied']);self.assertEqual(encoded,original)


if __name__=='__main__':unittest.main()
