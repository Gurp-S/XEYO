from base64 import urlsafe_b64encode
from email.message import Message
from io import BytesIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
from unittest import TestCase,main

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments'))
from native_provider_chatgpt import ChatGPTProvider,BASE,NoRedirect


class Response(BytesIO):
    def __init__(self,body=b'{}',code=200,content_type='application/json'):
        super().__init__(body);self.code=code;self.headers=Message();self.headers['Content-Type']=content_type


class ProviderTests(TestCase):
    def provider(self,opener,*,expires=None):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup);path=Path(temp.name)/'auth.json'
        claim=urlsafe_b64encode(json.dumps({'exp':expires if expires is not None else time.time()+3600}).encode()).decode().rstrip('=')
        path.write_text(json.dumps({'auth_mode':'chatgpt','tokens':{'access_token':'fixture.'+claim+'.sig','account_id':'fixture-account'}}))
        return ChatGPTProvider(path,opener=opener,capture_directory=Path(temp.name)/'responses')

    def test_fixed_url_raw_body_and_redacted_trace(self):
        seen=[]
        def opener(req,timeout):seen.append(req);return Response(b'event: done\n\n',content_type='text/event-stream')
        api=self.provider(opener);body=b'{"model":"fixed"}';status,kind,response=api(body)
        self.assertEqual(seen[0].full_url,BASE+'/responses');self.assertEqual(seen[0].data,body)
        self.assertTrue(seen[0].get_header('Authorization').startswith('Bearer fixture.'))
        self.assertNotIn('fixture',repr(api));self.assertNotIn('fixture',json.dumps(api.trace))
        self.assertEqual((status,kind,response),(200,'text/event-stream',b'event: done\n\n'))

    def test_expired_token_does_not_dispatch(self):
        api=self.provider(lambda *a,**k:self.fail('network'),expires=1)
        with self.assertRaisesRegex(ValueError,'expired'):api.catalog()
        self.assertEqual(api.trace,[])

    def test_catalog_not_inference_and_route_refusal(self):
        seen=[]
        api=self.provider(lambda req,timeout:seen.append(req) or Response())
        api.catalog();self.assertEqual(seen[0].method,'GET');self.assertIsNone(seen[0].data)
        with self.assertRaisesRegex(ValueError,'route'):api._request('/private',limit=3)

    def test_redirect_is_never_followed(self):
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://private/'))
        api=self.provider(lambda *a,**k:Response(code=302))
        with self.assertRaisesRegex(ValueError,'redirect'):api.catalog()
        self.assertEqual(len(api.trace),1)

    def test_bad_content_or_size_not_retried(self):
        for response in (Response(content_type='text/html'),Response(b'123456')):
            api=self.provider(lambda *a,**k:response)
            with self.assertRaises(ValueError):api._request('/responses',b'{}',limit=3)
            self.assertEqual(len(api.trace),1)

    def test_untyped_valid_sse_preserved_before_normalizing_media_type(self):
        raw=b'event: response.created\ndata: {"type":"response.created"}\n\nevent: response.completed\ndata: {"type":"response.completed"}\n\n'
        api=self.provider(lambda *a,**k:Response(raw,content_type='text/plain'))
        status,kind,body=api(b'{}')
        self.assertEqual((status,kind,body),(200,'text/event-stream',raw))
        self.assertEqual((api.capture/'001-response.bin').read_bytes(),raw)
        self.assertEqual(api.trace[0]['content_type'],'text/plain')

    def test_invalid_body_preserved_without_forwarding(self):
        raw=b'not a Responses stream'
        api=self.provider(lambda *a,**k:Response(raw,content_type='text/plain'))
        with self.assertRaisesRegex(ValueError,'content_type'):api(b'{}')
        self.assertEqual((api.capture/'001-response.bin').read_bytes(),raw)
        self.assertTrue(api.trace[0]['response_complete'])

    def test_partial_response_preserved_on_read_failure(self):
        class Broken(Response):
            reads=0
            def read1(self,size):
                self.reads+=1
                if self.reads==1:return b'partial'
                raise TimeoutError('fixture')
        api=self.provider(lambda *a,**k:Broken(content_type='text/event-stream'))
        with self.assertRaises(TimeoutError):api(b'{}')
        self.assertEqual((api.capture/'001-response.bin').read_bytes(),b'partial')
        self.assertFalse(api.trace[0]['response_complete'])


if __name__=='__main__':main()
