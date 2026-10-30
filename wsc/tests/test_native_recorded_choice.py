from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from wsc.contracts import encode
from native_recorded_choice import reuse,POLICY


class RecordedChoiceChecks(unittest.TestCase):
    def put(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(encode(value),encoding='utf-8')
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.g=self.root/'C-selector/generation';self.c=self.root/'coordinator-private/C'
        self.event=dict(id='source',seq=1,kind='observation',text='source text',payload={},observed_at=None)
        self.raw=self.root/'source.json';self.put(self.raw,self.event)
        manifest=dict(cold_sources={'s1':dict(source_id='source',observed_at=None,path=str(self.raw),sha256=sha256(self.raw.read_bytes()).hexdigest())})
        self.put(self.g/'resource-manifest.json',manifest);self.manifest_sha=sha256((self.g/'resource-manifest.json').read_bytes()).hexdigest()
        self.draft=dict(source_ids=['s1'],understanding_refs=[],new_understandings=[dict(id=None,expected_revision=None,text='judgment',kind='hypothesis',
            sources=['s1'],scope={'source_manifest_sha256':self.manifest_sha})],clues=[],span_refs=[],retained_excerpt_keys=[])
        self.put(self.g/'wire-bindings.json',dict(aliases={'s1':'s1','source':'s1'},manifest_sha256=self.manifest_sha))
        self.put(self.g/'span-handle-bindings.json',{})
        self.rollout=self.c/'selection/rollout.jsonl';self.rollout.parent.mkdir(parents=True);self.rollout.write_bytes(b'unit-only-fixture\n')
        self.record=dict(id='stored-record',revision=1,previous=None,producer=POLICY['id'],text='judgment',kind='hypothesis',sources=['source'],scope={'source_manifest_sha256':self.manifest_sha})
        self.write_draft();self.write_records()
        self.core=SimpleNamespace(material=lambda snapshot:dict(events=[deepcopy(self.event)],understandings=[]))
    def tearDown(self):self.temp.cleanup()
    def write_draft(self):
        self.put(self.g/'model-draft.json',self.draft);self.put(self.g/'compiled-draft.json',self.draft)
        self.put(self.c/'selection/phase-outcome.json',dict(completed=True,usage_complete=True,failure=None,finals=[dict(text=encode(self.draft))],
            rollout_sha256=sha256(self.rollout.read_bytes()).hexdigest(),receipts={'all_usage':{}}))
    def write_records(self):
        path=self.root/'records.json';self.put(path,[self.record])
        self.put(self.c/'publication.json',dict(package=dict(understanding_index=str(path),understanding_index_sha256=sha256(path.read_bytes()).hexdigest())))
    def test_reuse_preserves_record_identity_and_scope(self):
        selection,proof=reuse(self.core,object(),self.root)
        self.assertEqual('stored-record',selection.new_understandings[0].id)
        self.assertEqual(self.record['scope'],selection.new_understandings[0].scope)
        self.assertEqual(0,proof['model_calls'])
    def test_changed_source_bytes_are_rejected(self):
        self.raw.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'source_bytes_changed'):reuse(self.core,object(),self.root)
    def test_scope_is_not_rewritten_to_match_manifest(self):
        self.draft['new_understandings'][0]['scope']['source_manifest_sha256']='other';self.write_draft()
        with self.assertRaisesRegex(ValueError,'scope_not_exact'):reuse(self.core,object(),self.root)
    def test_later_revision_is_not_reset_to_revision_one(self):
        self.record['revision']=2;self.write_records()
        with self.assertRaisesRegex(ValueError,'revision_unsupported'):reuse(self.core,object(),self.root)


if __name__=='__main__':unittest.main()
