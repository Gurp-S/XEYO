from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from native_span_handles import project,expand


class SpanHandleTests(unittest.TestCase):
    def test_bijection_preserves_exact_text_and_source_order(self):
        offered=dict(events=[dict(id='s1',spans=[dict(ref='s1:0:3:hash-A',text='原文🙂'),dict(ref='s1:3:9:hash-B',text=' next ')]),
            dict(id='s2',spans=[dict(ref='s2:0:3:hash-C',text='原文🙂')])],other='unchanged')
        original=deepcopy(offered)
        wire,bindings=project(offered)
        restored=deepcopy(wire)
        for event in restored['events']:
            for span in event['spans']:
                span['ref']=bindings[span['ref']]
        self.assertEqual(restored,original)
        self.assertEqual(offered,original)
        self.assertEqual(expand(dict(span_refs=['p2','p0'],clues=[dict(text='same')]),bindings),
            dict(span_refs=['s2:0:3:hash-C','s1:0:3:hash-A'],clues=[dict(text='same')]))

    def test_unknown_handles_and_ambiguous_catalogs_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'not_offered'):
            expand(dict(span_refs=['unknown']),{'p0':'canonical'})
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            project(dict(events=[dict(spans=[dict(ref='same',text='a'),dict(ref='same',text='b')])]))


if __name__=='__main__':
    unittest.main()
