from base64 import b64encode,b64decode
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
import json
import struct
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from native_provider_frames import receive,send,MAX_FRAME
from native_provider_gate import ProviderGate,dispatch


class BridgeTests(TestCase):
    def gate(self,exchange,calls=2):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        return ProviderGate(model='fixed',max_calls=calls,seconds=10,
            directory=Path(temp.name)/'gate',exchange=exchange)

    def frame(self,raw=None,**extra):
        return dict(method='POST',path='/v1/responses',body=b64encode(
            raw if raw is not None else b'{"model":"fixed","input":[]}').decode(),**extra)

    def test_frame_roundtrip_and_rejections(self):
        stream=BytesIO();send(stream,{'text':'原文🙂'});stream.seek(0)
        self.assertEqual(receive(stream),{'text':'原文🙂'})
        for value in (b'\0',struct.pack('!I',MAX_FRAME+1),struct.pack('!I',7)+b'{"x":',
                      struct.pack('!I',13)+b'{"x":1,"x":2}'):
            with self.subTest(value=value),self.assertRaises((EOFError,ValueError)): receive(BytesIO(value))

    def test_bytes_preserved_and_call_limit(self):
        seen=[];body=b'event: fixture\ndata: {"x":1}\n\n'
        gate=self.gate(lambda raw:(seen.append(raw) or 200,'text/event-stream',body),calls=1)
        frame=self.frame();reply=gate.handle(frame)
        self.assertEqual(seen,[b64decode(frame['body'])]);self.assertEqual(b64decode(reply['body']),body)
        with self.assertRaisesRegex(ValueError,'call_limit'):gate.handle(frame)
        self.assertEqual(len(seen),1)

    def test_routes_headers_and_wrong_model_do_not_dispatch(self):
        seen=[]
        for frame in (dict(self.frame(),path='/v1/responses?url=private'),
                      self.frame(url='https://private/'),self.frame(b'{"model":"other"}'),
                      self.frame(b'{"model":"fixed","model":"other"}')):
            gate=self.gate(lambda raw:seen.append(raw))
            with self.assertRaises(ValueError):gate.handle(frame)
        self.assertEqual(seen,[])

    def test_upstream_failure_reserved_without_retry(self):
        seen=[]
        def failed(raw):seen.append(raw);raise OSError('fixture')
        gate=self.gate(failed,calls=1)
        with self.assertRaises(OSError):gate.handle(self.frame())
        with self.assertRaises(ValueError):gate.handle(self.frame())
        self.assertEqual(len(seen),1);self.assertEqual(gate.trace[0]['error_type'],'OSError')

    def test_invalid_response_not_forwarded(self):
        for response in ((True,'application/json',b'{}'),(200,'text/html',b'{}'),(200,'application/json','{}')):
            with self.subTest(response=response):
                with self.assertRaisesRegex(ValueError,'response'):
                    self.gate(lambda raw:response).handle(self.frame())

    def test_deadline_before_dispatch(self):
        gate=self.gate(lambda raw:self.fail('dispatch'));gate.deadline=0
        with self.assertRaises(TimeoutError):gate.handle(self.frame())

    def test_owner_failure_is_returned_as_immediate_json_reply(self):
        def failed(raw):raise ValueError('provider_response_content_type')
        gate=self.gate(failed,calls=1)
        reply,error=dispatch(gate,self.frame(),1)
        self.assertEqual(reply['status'],502);self.assertEqual(reply['ordinal'],1)
        self.assertEqual(json.loads(b64decode(reply['body'])),{'error':{'code':'provider_owner_exchange_failed'}})
        self.assertEqual(error['code'],'provider_response_content_type')
        self.assertEqual(gate.calls,1)


if __name__=='__main__':main()
