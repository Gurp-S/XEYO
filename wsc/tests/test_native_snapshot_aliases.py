from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from wsc import WSC,Store,Selection,Event
from wsc.source_access import SnapshotSourceAccess
from wsc.source_reference_view import MODE
from native_indexed_checkpoint import IndexedCheckpointAdapter,expand_working_state
from native_snapshot_aliases import validate_recovery_aliases


class SnapshotAliasChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def render(self,name,policy,selected):
        root=self.root/name;root.mkdir()
        core=WSC(Store(root/'state.db',session_id='fixture',workspace=str(root)),access=lambda *a:True)
        core.ingest([Event('a','message',dict(type='message',role='user',content=[dict(type='input_text',text='task')]),role='user',text='task'),
                     Event('b','observation',{},text='old value'),Event('c','observation',{},text='new value')])
        snapshot=core.capture()
        view=core.prepare(snapshot,Selection(source_ids=tuple(selected)),producer='alias-ab',source_projection=MODE)
        operation=core.stage(view,directory=root/'export',adapter=IndexedCheckpointAdapter(source_alias_policy=policy))
        package=core.package(operation)
        reader=SnapshotSourceAccess(core.store,snapshot,access=core.access)
        for item in package['items']:
            for block in item.get('content',[]):
                try:header=json.loads(block.get('text','').splitlines()[0])
                except (ValueError,IndexError):continue
                if isinstance(header,dict) and header.get('format')=='wsc.indexed_sections/1':return header,reader,package
        self.fail('indexed header missing')

    def test_same_source_alias_is_stable_across_different_selections(self):
        a,_,_=self.render('one','snapshot_event_seq_v1',['c'])
        b,_,_=self.render('two','snapshot_event_seq_v1',['b','c'])
        self.assertEqual('c',a['source_aliases']['s3']['source_id'])
        self.assertEqual('c',b['source_aliases']['s3']['source_id'])

    def test_old_dense_ids_reproduce_failure_and_wrong_source(self):
        header,reader,package=self.render('old','legacy_dense_v1',['b','c'])
        self.assertEqual('b',header['source_aliases']['s0']['source_id'])
        with self.assertRaisesRegex(ValueError,'source_not_bound'):reader.read('s0')
        self.assertEqual('c',header['source_aliases']['s1']['source_id'])
        self.assertEqual('a',reader.read('s1')['original_source_id'])
        with self.assertRaisesRegex(ValueError,'alias_mismatch'):validate_recovery_aliases(package,reader)

    def test_every_new_displayed_handle_recovers_its_exact_source(self):
        header,reader,package=self.render('new','snapshot_event_seq_v1',['b','c'])
        validate_recovery_aliases(package,reader)
        for alias,value in header['source_aliases'].items():
            self.assertEqual(value['source_id'],reader.read(alias)['original_source_id'])

    def test_existing_legacy_export_still_expands_without_rewriting(self):
        _,_,package=self.render('legacy','legacy_dense_v1',['b','c'])
        metadata=json.loads(Path(package['adapter']['projection_evidence']['file_path']).read_text(encoding='utf-8'))
        text=next(block['text'] for item in package['items'] for block in item.get('content',[])
                  if block.get('text','').startswith('{"archive":'))
        restored=expand_working_state(text,metadata)
        self.assertEqual(['b','c'],[row['source']['source_id'] for row in restored['historical_excerpts']])


if __name__=='__main__':unittest.main()
