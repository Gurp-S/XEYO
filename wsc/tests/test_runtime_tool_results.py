from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from unittest.mock import patch
import asyncio
import hashlib
import json
import sys
import os

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wsc.tool_results import ResultStore,RuntimeResults,ResultPolicy,ToolText,ResultQueryTool
from wsc.contracts import encode


class RuntimeResultChecks(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.denied=set()
        self.store=ResultStore(self.root/'results',session='test',access=lambda s,r,a:r not in self.denied)
        self.api=RuntimeResults(self.store,policy=ResultPolicy(enabled=True))

    def full(self,rid):
        parts=[];offset=0
        while True:
            result=self.api.read(rid,offset=offset,limit=32768);parts.append(result['text'])
            if result['next_offset'] is None:return ''.join(parts)
            self.assertGreater(result['next_offset'],offset);offset=result['next_offset']

    def test_actual_tool_wrapper_externalizes_and_preserves_unicode_crlf(self):
        text=('中文🙂\r\nINFO actual body\rprogress\n'*3000)
        calls=[]
        def tool():calls.append(1);return ToolText(text,kind='terminal_log',exit_code=0)
        view=self.api.call('call-1',tool)
        self.assertEqual([1],calls);self.assertTrue(view['external'])
        self.assertLessEqual(len(encode(view).encode()),2048)
        self.assertIn('strip_noise_lines',view['rules'])
        self.assertEqual(text,self.full(view['result_id']))
        self.assertEqual(text.encode(),next(self.store.objects.glob('*.txt')).read_bytes())

    def test_all_seven_strategies_have_applicable_cases(self):
        cases=[('terminal_log','\x1b[31mimportant\x1b[0m\r\n'*6000,'strip_noise_lines'),
               ('stack','frame\n'*8000,'collapse_stack'),
               ('diff','diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1,6000 +1,6000 @@\n'+'-old\n+new\n'*6000,'diff_digest'),
               ('json',json.dumps({'rows':[{'id':x,'value':'x'*80} for x in range(1500)]}),'outline_json'),
               ('unknown','start\n'+'original middle\n'*6000+'end','truncate_head_tail')]
        for index,(kind,text,rule) in enumerate(cases):
            view=self.api.present(str(index),ToolText(text,kind=kind))
            self.assertTrue(view['external']);self.assertIn(rule,view['rules'])
        text='duplicate\n'*6000
        a=self.api.present('d1',ToolText(text));b=self.api.present('d2',ToolText(text,exit_code=1))
        self.assertIn('dedupe_identical',b['rules']);self.assertNotEqual(a['result_id'],b['result_id'])
        self.assertEqual('nonzero_exit',b['execution_status'])
        source=dict(path='src.py',version='hash-v1',range=[1,200])
        self.api.present('s1',ToolText('source\n'*6000,kind='source',source=source))
        b=self.api.present('s2',ToolText('source\n'*6000,kind='source',source=source))
        self.assertIn('dedupe_reads',b['rules'])

    def test_same_path_new_version_keeps_old_original_and_current_metadata(self):
        first=self.api.present('v1',ToolText('old\n'*10000,kind='source',source=dict(path='a',version='v1',range=[0,10])))
        second=self.api.present('v2',ToolText('new\n'*10000,kind='source',source=dict(path='a',version='v2',range=[0,10])))
        self.assertNotIn('dedupe_reads',second['rules'])
        self.assertEqual('v2',second['source']['version'])
        self.assertEqual('old\n'*10000,self.full(first['result_id']))
        self.assertEqual('new\n'*10000,self.full(second['result_id']))

    def test_recovery_control_and_disabled_policy_are_exact_passthrough(self):
        text='raw source\r\n'*10000
        for value in (ToolText(text,recovery=True),ToolText(text,role='user'),ToolText(text,role='system'),ToolText(text,role='developer')):
            view=self.api.present('bypass',value);self.assertFalse(view['external']);self.assertEqual(text,view['text'])
        off=RuntimeResults(self.store)
        self.assertFalse(off.present('off',ToolText(text))['external'])
        with self.store.connect() as db:self.assertEqual(0,db.execute('SELECT COUNT(*) FROM results').fetchone()[0])

    def test_error_and_timeout_are_not_hidden_by_success_boolean(self):
        view=self.api.present('failed',ToolText('log\n'*20000,kind='build',status='success',exit_code=2,timed_out=True,facts={'failed':7}))
        self.assertEqual('timeout',view['execution_status']);self.assertEqual(2,view['exit_code'])
        self.assertEqual({'failed':7},view['facts'])

    def test_idempotent_call_and_conflicting_reuse(self):
        text='original\n'*5000
        one=self.api.present('same',ToolText(text));two=self.api.present('same',ToolText(text))
        self.assertEqual(one,two)
        with self.assertRaisesRegex(ValueError,'identity_conflict'):
            self.api.present('same',ToolText(text+'changed'))

    def test_queries_bypass_summary_and_find_across_chunk_boundary(self):
        text='a'*16382+'TARGET\r\n'+'z'*50000
        view=self.api.present('query',ToolText(text));rid=view['result_id']
        found=self.api.find(rid,'TARGET');self.assertEqual(16382,found['matches'][0]['offset'])
        raw=self.api.read(rid,offset=16382,limit=8)
        self.assertTrue(raw['recovery']);self.assertEqual('TARGET\r\n',raw['text'])
        self.assertEqual('z'*12,self.api.read_lines(rid,start_line=2,limit=12)['text'])
        self.assertEqual('a'*12,self.api.read_lines(rid,start_line=1,limit=12)['text'])

    def test_json_pointer_preserves_false_null_and_escaped_keys(self):
        raw=json.dumps({'a/b':{'~x':[False,None,42]},'padding':'q'*40000})
        rid=self.api.present('json',ToolText(raw,kind='json'))['result_id']
        for i,expected in enumerate((False,None,42)):
            self.assertEqual(expected,self.api.json_pointer(rid,f'/a~1b/~0x/{i}')['value'])
        for path in ('/a~2b','/a~1b/~0x/01','/missing'):
            with self.assertRaises(ValueError):self.api.json_pointer(rid,path)

    def test_duplicate_json_and_deep_or_oversize_json_never_get_fake_outline(self):
        raw='{"x":1,"x":2,"padding":"'+'p'*40000+'"}'
        view=self.api.present('invalid',ToolText(raw,kind='json'))
        self.assertNotIn('outline_json',view['rules'])
        with self.assertRaises(ValueError):self.api.json_pointer(view['result_id'],'/x')
        deep='['*1200+'0'+']'*1200+' '*40000
        view=self.api.present('deep',ToolText(deep,kind='json'))
        self.assertIn('structured_format_unavailable',view['notes'])
        small=RuntimeResults(self.store,policy=ResultPolicy(enabled=True,max_json_bytes=100))
        view=small.present('capped',ToolText(json.dumps({'v':'p'*40000}),kind='json'))
        self.assertIn('structured_parse_byte_limit',view['notes'])
        with self.assertRaisesRegex(ValueError,'structured_parse_limit'):small.json_pointer(view['result_id'],'/v')

    def test_permission_revocation_and_corruption_reject_original_queries(self):
        view=self.api.present('private',ToolText('evidence\n'*6000));rid=view['result_id']
        self.denied.add(rid)
        with self.assertRaisesRegex(ValueError,'Permission denied'):self.api.read(rid)
        self.denied.clear();record=self.store.record(rid)
        path=self.store.objects/(record['hash']+'.txt')
        with path.open('r+b') as f:f.write(b'X')
        with self.assertRaisesRegex(ValueError,'integrity_mismatch'):self.api.read(rid)
        fallback=self.api.present('again',ToolText('evidence\n'*6000))
        self.assertFalse(fallback['external']);self.assertEqual('evidence\n'*6000,fallback['text'])
        self.assertFalse(self.api.present('private',ToolText('evidence\n'*6000))['external'])

    def test_write_failure_and_quota_do_not_replace_original_with_a_dead_reference(self):
        text='original\n'*6000
        with patch('wsc.tool_results.storage.os.fsync',side_effect=OSError('disk failure')):
            view=self.api.present('write-fail',ToolText(text))
        self.assertFalse(view['external']);self.assertEqual(text,view['text'])
        self.assertFalse(list(self.store.objects.glob('*.tmp')))
        small=RuntimeResults(ResultStore(self.root/'small',session='s',max_object_bytes=100,max_storage_bytes=100),policy=ResultPolicy(enabled=True,externalize_bytes=10))
        view=small.present('over',ToolText(text));self.assertFalse(view['external']);self.assertEqual(text,view['text'])

    def test_orphan_exact_file_is_reconciled_without_overwrite(self):
        text='recoverable\n'*4000
        digest=hashlib.sha256(text.encode()).hexdigest();path=self.store.objects/(digest+'.txt')
        path.write_bytes(text.encode());view=self.api.present('orphan',ToolText(text))
        self.assertTrue(view['external']);self.assertEqual(text,self.full(view['result_id']))

    def test_source_is_not_terminal_and_large_facts_are_not_silently_dropped(self):
        text='\x1b[31mactual source\r\n'*4000
        view=self.api.present('source',ToolText(text,kind='source'))
        self.assertNotIn('strip_noise_lines',view['rules'])
        view=self.api.present('facts',ToolText('body\n'*10000,facts={'error':'e'*3000}))
        self.assertFalse(view['external']);self.assertEqual({'error':'e'*3000},view['facts'])

    def test_session_bound_ids_and_async_tool_only_runs_once(self):
        with self.assertRaisesRegex(ValueError,'session_mismatch'):ResultStore(self.store.root,session='other')
        calls=[]
        async def tool():calls.append(1);return ToolText('async\n'*10000)
        view=asyncio.run(self.api.acall('async',tool));self.assertTrue(view['external']);self.assertEqual([1],calls)

    def test_query_tool_dispatch_is_bounded_and_recovery_is_not_externalized_again(self):
        view=self.api.present('large',ToolText('original\r\n'*8000));rid=view['result_id']
        tool=ResultQueryTool(self.api,max_calls=2,max_return_bytes=131072)
        raw=tool.call(dict(operation='read',result_id=rid,limit=32768))
        wrapped=self.api.present('query',raw)
        self.assertTrue(wrapped['recovery']);self.assertFalse(wrapped['external'])
        self.assertTrue(json.loads(wrapped['text'])['text'].startswith('original\r\n'))
        bad=tool.call(dict(operation='read',result_id=rid,path='outside'))
        self.assertEqual('error',bad.status)
        exhausted=tool.call(dict(operation='read',result_id=rid))
        self.assertIn('tool_result_query_call_limit',exhausted.text)

    def test_same_body_shares_file_but_never_overwrites_call_metadata(self):
        text='body\n'*10000
        first=self.api.present('first',ToolText(text,status='success',exit_code=0,observed_at='t1'))
        second=self.api.present('second',ToolText(text,status='error',exit_code=9,observed_at='t2'))
        self.assertEqual(1,len(list(self.store.objects.glob('*.txt'))))
        self.assertEqual('t2',second['observed_at']);self.assertEqual(9,second['exit_code'])
        self.assertEqual(text,self.full(first['result_id']))

    def test_corrupt_line_index_is_not_trusted(self):
        view=self.api.present('lines',ToolText('row\n'*20000));rid=view['result_id']
        with self.store.connect() as db:
            raw=db.execute('SELECT chunks FROM objects').fetchone()[0]
            chunks=json.loads(raw);chunks[-1][3]+=1
            db.execute('UPDATE objects SET chunks=?',(encode(chunks),))
        with self.assertRaisesRegex(ValueError,'index_invalid'):self.api.read_lines(rid,start_line=100)

    def test_oversize_query_returns_limit_error_instead_of_another_summary(self):
        rid=self.api.present('escape',ToolText('\x00'*40000))['result_id']
        tool=ResultQueryTool(self.api)
        result=tool.call(dict(operation='read',result_id=rid,limit=32768))
        self.assertEqual('tool_result_query_return_limit',json.loads(result.text)['code'])
        for operation in ([],{}):
            result=tool.call(dict(operation=operation,result_id=rid))
            self.assertEqual('error',result.status)

    def test_metadata_is_frozen_and_impossible_sqlite_ids_are_neutral_errors(self):
        facts={'failed':2};source={'path':'a','version':'v1','range':[1,2]}
        view=self.api.present('frozen',ToolText('body\n'*10000,facts=facts,source=source))
        facts['failed']=0;source['version']='v2'
        self.assertEqual(2,view['facts']['failed']);self.assertEqual('v1',view['source']['version'])
        tool=ResultQueryTool(self.api)
        for rid in ('r9999999999999999999','r01','r0','r'+'1'*1000):
            reply=tool.call(dict(operation='read',result_id=rid))
            self.assertEqual('error',reply.status)

    def test_broken_query_database_is_a_fact_result_not_a_traceback(self):
        rid=self.api.present('db',ToolText('body\n'*10000))['result_id']
        self.store.db.write_bytes(b'broken database')
        response=ResultQueryTool(self.api).call(dict(operation='read',result_id=rid))
        self.assertEqual('error',response.status)
        self.assertEqual('tool_result_query_failed',json.loads(response.text)['code'])

    def test_oversize_stack_skips_whole_text_split_but_keeps_exact_original(self):
        api=RuntimeResults(self.store,policy=ResultPolicy(enabled=True,max_transform_bytes=100))
        text='frame\n'*10000
        with patch('wsc.tool_results.strategies.collapse',side_effect=AssertionError('whole-text transform ran')):
            view=api.present('huge-stack',ToolText(text,kind='stack'))
        self.assertTrue(view['external']);self.assertIn('display_scan_byte_limit',view['notes'])
        self.assertEqual(text,self.full(view['result_id']))

    def test_new_object_is_verified_after_link_before_summary_is_published(self):
        link=os.link
        def damaged(source,target):
            link(source,target)
            with Path(target).open('r+b') as f:f.write(b'X')
        text='original\n'*6000
        with patch('wsc.tool_results.storage.os.link',side_effect=damaged):
            view=self.api.present('damaged-new-object',ToolText(text))
        self.assertFalse(view['external']);self.assertEqual(text,view['text'])

    def test_duplicate_body_replay_keeps_original_reference_after_later_calls(self):
        text='same original body\n'*4000
        self.api.present('first-body',ToolText(text))
        second=self.api.present('second-body',ToolText(text))
        self.api.present('third-body',ToolText(text))
        replay=self.api.present('second-body',ToolText(text))
        self.assertEqual(second,replay)


if __name__=='__main__':main()
