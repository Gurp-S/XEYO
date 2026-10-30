from pathlib import Path
from copy import deepcopy
import sys,unittest
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).resolve().parents[1]/'experiments')]
from native_event_table import project,restore
from wsc.contracts import encode,digest,WSCError


class EventTableTests(unittest.TestCase):
    def material(self):
        return dict(events=[dict(id=f's{i}',seq=i,role='user' if i==1 else 'assistant',kind='message',spans=[],
            public_text_available=False,public_text_characters=None,text_in_frontier=False,
            cold_source=dict(manifest_key=f's{i}'),value=False if i%2 else 0) for i in range(1,65)],
            prose='Keep this exact source string s1',scope=dict(id='s2'))
    def test_strict_types_order_and_prose_survive(self):
        value=self.material();value['events'].insert(9,dict(id='hot',text='🙂 new observation',text_in_frontier=True))
        original=deepcopy(value);wire,binding=project(value)
        self.assertTrue(binding['applied']);self.assertEqual(encode(original),encode(restore(wire,binding)))
        self.assertEqual(original,value);self.assertEqual(original['prose'],wire['prose'])
        decoded=restore(wire,binding);self.assertIs(decoded['events'][0]['value'],False);self.assertIs(type(decoded['events'][1]['value']),int)
    def test_missing_and_null_do_not_merge_and_no_gain_is_passthrough(self):
        value=self.material();value['events'][0].pop('public_text_characters')
        wire,binding=project(value);self.assertFalse(binding['applied']);self.assertEqual(encode(value),encode(wire))
        wire,binding=project(dict(events=[]));self.assertFalse(binding['applied'])
        value=dict(events=[dict(text_in_frontier=False,x=None)])
        wire,binding=project(value);self.assertFalse(binding['applied']);self.assertEqual(value,restore(wire,binding))
    def test_binding_and_malformed_positions_rejected(self):
        wire,binding=project(self.material());changed=deepcopy(wire);changed['events']['rows'][0][1]='other'
        with self.assertRaises(WSCError):restore(changed,binding)
        for position in (False,-1,10**12):
            changed=deepcopy(wire);changed['events']['rows'][0][0]=position
            forged={**binding,'represented_sha256':digest(changed)}
            with self.assertRaisesRegex(WSCError,'position_invalid'):restore(changed,forged)
        changed=deepcopy(wire);changed['events']['rows'][1][0]=changed['events']['rows'][0][0]
        with self.assertRaisesRegex(WSCError,'position_invalid'):restore(changed,{**binding,'represented_sha256':digest(changed)})


if __name__=='__main__':unittest.main()
