"""Source-bound external result references. No replacement of source authority."""
from hashlib import sha256
import json

from .contracts import digest,encode,require
from .evidence import source_row,authorize
from .control_sources import is_control_source


class ContextReferences:
    def __init__(self,core,results):
        require(core.store.session_id==results.store.session,'context_session_mismatch')
        self.core,self.results=core,results
        self.store_binding=digest(dict(session=results.store.session,root=str(results.store.root)))
        owner=encode(dict(session=core.store.session_id,workspace=core.store.workspace,source_store=str(core.store.path)))
        with results.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS wsc_context_owner_v1(singleton INTEGER PRIMARY KEY CHECK(singleton=1),data TEXT NOT NULL)')
            row=db.execute('SELECT data FROM wsc_context_owner_v1 WHERE singleton=1').fetchone()
            require(row is None or row[0]==owner,'context_workspace_binding_mismatch')
            if row is None:db.execute('INSERT INTO wsc_context_owner_v1 VALUES (1,?)',(owner,))
        with core.store.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS wsc_context_results_v1('
              'source_id TEXT PRIMARY KEY REFERENCES events(id),store_binding TEXT NOT NULL,'
              'result_id TEXT NOT NULL,data TEXT NOT NULL,seal TEXT NOT NULL,UNIQUE(store_binding,result_id))')

    def bind(self,source_id,result_id,view):
        with self.core.store.transaction() as db:
            return self.bind_in(db,source_id,result_id,view)

    def bind_in(self,db,source_id,result_id,view):
        """Binding inside a caller-owned transaction: event, binding and delivery
        commit together, so a crash cannot leave a bound reference without its
        source row."""
        record=self.results.store.record(result_id)
        require(view.get('external') is True and view.get('result_id')==result_id,'context_view_binding_mismatch')
        require(all(view.get(k)==v for k,v in record['meta'].items()),'context_result_metadata_changed')
        for _ in self.results.store.blocks(record):pass
        row=source_row(db,source_id);authorize(self.core.store,self.core.access,source_id)
        require(row['kind']=='result' and row['call_id']==record['call_id'],'context_call_binding_mismatch')
        require(not is_control_source(row),'context_control_projection_unavailable')
        text=row['text'];require(isinstance(text,str),'context_source_text_unavailable')
        h=sha256()
        for i in range(0,len(text),16384):h.update(text[i:i+16384].encode('utf-8'))
        require(h.hexdigest()==record['hash'],'context_original_text_mismatch')
        raw=db.execute('SELECT digest FROM events WHERE id=?',(source_id,)).fetchone()[0]
        value=dict(source_id=source_id,source_seq=row['seq'],source_seal=digest(row),event_digest=raw,call_id=row['call_id'],
                   result_id=result_id,store_binding=self.store_binding,object_sha256=record['hash'],
                   result_meta_digest=digest(record['meta']),visible_view=view)
        value=json.loads(encode(value));encoded=encode(value)
        old=db.execute('SELECT data FROM wsc_context_results_v1 WHERE source_id=?',(source_id,)).fetchone()
        require(old is None or old[0]==encoded,'context_reference_identity_conflict')
        if old is None:db.execute('INSERT INTO wsc_context_results_v1 VALUES (?,?,?,?,?)',
                     (source_id,self.store_binding,result_id,encoded,digest(value)))
        return value

    def get(self,*,source_id=None,result_id=None):
        require((source_id is None)!=(result_id is None),'context_reference_arguments_invalid')
        with self.core.store.connect() as db:
            if source_id is not None:
                row=db.execute('SELECT data,seal FROM wsc_context_results_v1 WHERE source_id=?',(source_id,)).fetchone()
            else:
                row=db.execute('SELECT data,seal FROM wsc_context_results_v1 WHERE store_binding=? AND result_id=?',
                               (self.store_binding,result_id)).fetchone()
        if row is None:return None
        value=json.loads(row[0]);require(digest(value)==row[1],'context_reference_integrity_mismatch')
        require(value['store_binding']==self.store_binding,'context_result_store_changed')
        return value

    def validate(self,link):
        require(link['store_binding']==self.store_binding,'context_result_store_changed')
        authorize(self.core.store,self.core.access,link['source_id'])
        # Streaming TEXT validation avoids decoding a huge source JSON on every
        # page. It still scans the source bytes; this is not a free I/O claim.
        with self.core.store.connect() as db:
            db.execute('BEGIN')
            row=db.execute('SELECT rowid AS internal_row_id,digest,kind,call_id FROM events WHERE id=?',(link['source_id'],)).fetchone()
            require(row is not None and row['digest']==link['event_digest'] and row['kind']=='result'
                    and row['call_id']==link['call_id'] and row['internal_row_id']==link['source_seq'],'context_source_binding_changed')
            h=sha256()
            with db.blobopen('events','data',row['internal_row_id'],readonly=True) as blob:
                while True:
                    block=blob.read(65536)
                    if not block:break
                    h.update(block)
            require(h.hexdigest()==link['event_digest'],'source_integrity_mismatch')
        record=self.results.store.record(link['result_id'])
        require(record['hash']==link['object_sha256'] and record['call_id']==link['call_id']
                and digest(record['meta'])==link['result_meta_digest'],'context_result_binding_changed')
        authorize(self.core.store,self.core.access,link['source_id'])
        return record
