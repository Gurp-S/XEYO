import base64
from hashlib import sha256
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from native_typed_content import TypedNativeAdapter,text_projection
from native_evidence import digest


class TypedContentTests(unittest.TestCase):
    def test_mixed_image_and_literal_text_preserve_source_and_time(self):
        raw=b'\x89PNG\r\n\x1a\nsource-image-bytes'
        uri='data:image/png;base64,'+base64.b64encode(raw).decode()
        literal='data:image/png;base64,this is literal text'
        item=dict(type='custom_tool_call_output',call_id='call-media',output=[
            dict(type='input_text',text='原文🙂'),dict(type='input_image',image_url=uri),dict(type='input_text',text=literal)])
        with tempfile.TemporaryDirectory() as directory:
            adapter=TypedNativeAdapter(directory)
            events=adapter.import_items([item],thread_id='thread',observed_at=['old-observation-time'])
            self.assertEqual(events[0].payload,item)
            self.assertEqual(events[0].id,'native:thread:0:'+digest(item))
            self.assertEqual(events[0].text,'原文🙂\n'+literal)
            media=events[1]
            self.assertEqual(media.observed_at,'old-observation-time')
            self.assertEqual(media.payload['source_id'],events[0].id)
            self.assertEqual(media.payload['sha256'],sha256(raw).hexdigest())
            self.assertEqual(Path(media.payload['path']).read_bytes(),raw)
            self.assertEqual(adapter.import_items([item],thread_id='thread',observed_at=['old-observation-time']),events)

    def test_plain_json_data_remains_data(self):
        item=dict(type='custom_tool_call_output',call_id='plain',output=[dict(type='invoice',amount=42)])
        self.assertIn('invoice',text_projection(item))
        self.assertIn('42',text_projection(item))
        self.assertEqual(text_projection(dict(type='custom_tool_call_output',output='original\n🙂')),'original\n🙂')

    def test_malformed_media_fails_without_a_successful_archive(self):
        item=dict(type='custom_tool_call_output',call_id='bad',output=[dict(type='input_image',image_url='data:image/png;base64,@@@')])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                TypedNativeAdapter(directory).import_items([item],thread_id='thread')
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_nonlocal_media_stays_explicitly_unresolved(self):
        item=dict(type='custom_tool_call_output',call_id='remote',output=[dict(type='input_image',image_url='https://example.invalid/image.png')])
        with tempfile.TemporaryDirectory() as directory:
            events=TypedNativeAdapter(directory).import_items([item],thread_id='thread')
            self.assertIsNone(events[0].text)
            self.assertEqual(events[1].payload['availability'],'original_payload_only')
            self.assertNotIn('path',events[1].payload)
            self.assertEqual(events[0].payload,item)


if __name__=='__main__':
    unittest.main()
