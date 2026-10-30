"""Bounded-lifetime policy preserves complete package and reconciliation."""
from pathlib import Path
from contextlib import closing
from uuid import UUID
import sys,tempfile,unittest,sqlite3,json
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from wsc import WSC,Store,Selection,Understanding,WSCError
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.resource_io import ResourceIO
from test_contracts import message,DurableTestHost


class PublicationMemoryTests(unittest.TestCase):
    def test_same_package_full_history_and_old_reader_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);adapter=CodexCheckpointAdapter();items=[message('user','事实 😀')]
            base=Store(root/'base.db',session_id='s',workspace=str(root));core=WSC(base,access=lambda *a:True)
            ids=core.ingest(adapter.import_items(items,thread_id='s'))
            for revision in range(3):core.remember(Understanding('state '+str(revision),'fact',tuple(ids),id='u',expected_revision=revision or None),producer='fixture')
            view=core.prepare(core.capture(),Selection(understanding_refs=('u@3',)),producer='fixture');packages=[]
            tail=message('assistant','unfolded tail');items.append(tail)
            core.ingest(adapter.import_items([tail],thread_id='s',start_ordinal=1))
            for label,policy in [('old',None),('new','bounded_catalog_v1')]:
                path=root/(label+'.db')
                with closing(sqlite3.connect(base.path)) as source,closing(sqlite3.connect(path)) as target:source.backup(target)
                store=Store(path,session_id='s',workspace=str(root))
                current=WSC(store,access=lambda *a:True,resource_io=ResourceIO(),publication_policy=policy)
                with patch('wsc.publication.uuid4',return_value=UUID(int=1)):
                    op=current.stage(view,directory=root/'exports',adapter=adapter)
                package=current.package(op);packages.append(package)
                self.assertEqual(2,package['through']);self.assertEqual(tail,package['items'][-1])
                records=json.loads(Path(package['understanding_index']).read_text(encoding='utf-8'))
                self.assertEqual(['u@1','u@2','u@3'],[r['ref'] for r in records])
                if policy:
                    reopened=WSC(store,access=lambda *a:True);host=DurableTestHost(root/'host.db',reopened,items);host.lose_reply=True
                    with self.assertRaises(TimeoutError):reopened.install(op,host)
                    reopened.reconcile(op,host)
                    self.assertEqual(1,host.state()['effects'])
            self.assertEqual(packages[0],packages[1])
    def test_final_binding_recheck_still_rejects_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);core=WSC(Store(root/'s.db',session_id='s',workspace=str(root)),access=lambda *a:True,publication_policy='bounded_catalog_v1')
            adapter=CodexCheckpointAdapter();core.ingest(adapter.import_items([message('user','task')],thread_id='s'))
            view=core.prepare(core.capture(),Selection(),producer='fixture')
            original=adapter.render
            def changed(*args,**kwargs):
                result=original(*args,**kwargs)
                core.ingest(adapter.import_items([message('user','new instruction')],thread_id='s',start_ordinal=1))
                return result
            with patch.object(adapter,'render',side_effect=changed):
                with self.assertRaisesRegex(WSCError,'control_changed'):core.stage(view,directory=root/'exports',adapter=adapter)
            self.assertEqual('failed',core.status()['operations'][0]['state'])


if __name__=='__main__':unittest.main()
