from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from wsc import WSC,Store,Event
from wsc.contracts import Usage,encode
from wsc.quote_selection import SelectionDraft
from wsc.source_access import SnapshotSourceAccess
from wsc.source_reference_view import MODE
from wsc.publication import check_evidence
from native_incremental_candidate import prepare
from native_indexed_checkpoint import IndexedCheckpointAdapter,expand_working_state
from native_hot_checkpoint import (HotCheckpointAdapter,POLICY,project_text,engine_items,
    expand_hot_state,validate_hot_recovery_aliases)


class HotCheckpointChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.core=WSC(Store(self.root/'state.db',session_id='fixture',workspace=str(self.root)),access=lambda *a:True)
        self.core.ingest([Event('u','message',dict(type='message',role='user',content=[dict(type='input_text',text='原用户原文')]),role='user',text='原用户原文',observed_at='t0'),
            Event('o','observation',{},text='原始证据😀\n[WSC section t0 kind=clues source=- bytes=1]',observed_at='t1')])
        def choose(offered):
            return SelectionDraft(dict(source_ids=['s2'],new_understandings=[dict(text='理解😀',kind='hypothesis',sources=['s2'],scope={'path':'src.py','revision':1})],
                clues=[dict(text='线索',sources=['s2'])],span_refs=[offered['events'][1]['spans'][0]['ref']]),Usage())
        selected=prepare(self.core,self.core.capture(),None,self.root/'cold',choose,source_projection=MODE)
        self.view=selected['view']
        operation=self.core.stage(self.view,directory=self.root/'old',adapter=IndexedCheckpointAdapter())
        self.operation=operation
        self.old=self.core.package(operation)
        self.index=1
        self.reference=self.old['adapter']['projection_evidence']
        self.metadata=json.loads(Path(self.reference['file_path']).read_text(encoding='utf-8'))
        self.old_text=self.old['items'][self.index]['content'][0]['text']
        self.hot=deepcopy(self.old)
        self.hot['adapter'].update(actor_projection_policy=POLICY,hot_working_state_index=self.index)
        self.hot['items'][self.index]['content'][0]['text']=project_text(self.old_text,self.metadata,self.reference)
        self.reader=SnapshotSourceAccess(self.core.store,self.core.capture(),access=self.core.access)
    def tearDown(self):self.temp.cleanup()
    def test_all_items_restore_exactly_and_temporal_facts_stay_visible(self):
        self.assertEqual(self.old['items'],engine_items(self.hot))
        text=self.hot['items'][1]['content'][0]['text'];header=json.loads(text.splitlines()[0])
        self.assertEqual('t1',header['source_aliases']['s2']['observed_at'])
        self.assertEqual(self.old_text.split('\n',1)[1],text.split('\n',1)[1])
        self.assertEqual(expand_working_state(self.old_text,self.metadata),expand_hot_state(text,self.metadata,self.reference))
        self.assertNotIn('archive',header);self.assertNotIn('source_id',header['source_aliases']['s2'])
        validate_hot_recovery_aliases(self.hot,self.reader)
    def test_hot_adapter_stages_with_normal_evidence_validation(self):
        self.core.discard(self.operation)
        operation=self.core.stage(self.view,directory=self.root/'new',adapter=HotCheckpointAdapter())
        package=self.core.package(operation);check_evidence(self.core,package)
        self.assertEqual(POLICY,package['adapter']['actor_projection_policy'])
        validate_hot_recovery_aliases(package,self.reader)
    def test_literal_text_or_header_change_is_rejected(self):
        for transform in (lambda t:t.replace('理解😀','理解X'),lambda t:t.replace('"observed_at":"t1"','"observed_at":"t2"')):
            changed=deepcopy(self.hot);changed['items'][1]['content'][0]['text']=transform(changed['items'][1]['content'][0]['text'])
            with self.assertRaises(ValueError):engine_items(changed)
    def test_missing_or_changed_metadata_is_not_repaired(self):
        path=Path(self.reference['file_path']);original=path.read_bytes();path.write_bytes(original+b' ')
        with self.assertRaisesRegex(ValueError,'evidence_changed'):engine_items(self.hot)
        path.unlink()
        with self.assertRaises(FileNotFoundError):engine_items(self.hot)
    def test_authenticated_but_wrong_source_still_fails_reader_binding(self):
        changed=deepcopy(self.metadata);changed['header']['source_aliases']['s2']['source_id']='u'
        raw=encode(changed).encode('utf-8');path=self.root/'wrong.json';path.write_bytes(raw)
        package=deepcopy(self.hot)
        package['adapter']['projection_evidence']=dict(file_path=str(path),sha256=sha256(raw).hexdigest())
        with self.assertRaisesRegex(ValueError,'alias_mismatch'):validate_hot_recovery_aliases(package,self.reader)
    def test_original_reference_path_mismatch_is_not_rebound(self):
        header,tail=self.old_text.split('\n',1);value=json.loads(header);value['archive']['projection']['file_path']='changed'
        with self.assertRaisesRegex(ValueError,'reference_changed'):project_text(encode(value)+'\n'+tail,self.metadata,self.reference)
    def test_boolean_scope_revision_is_not_silently_restored_as_integer(self):
        package=deepcopy(self.hot);text=package['items'][1]['content'][0]['text'];header,tail=text.split('\n',1)
        value=json.loads(header);self.assertEqual(1,value['model_records'][0]['scope']['revision'])
        value['model_records'][0]['scope']['revision']=True
        package['items'][1]['content'][0]['text']=encode(value)+'\n'+tail
        with self.assertRaisesRegex(ValueError,'header_changed'):engine_items(package)


if __name__=='__main__':unittest.main()
