"""Phase-1 durable tool-result writes.

One authoritative transaction commits the event row, the reference binding, the
delivery receipt and the intent state. The result store's rows and blobs are a
rebuildable index: a crash may leave an unreferenced blob, never a committed
event whose original text is missing.
"""
from datetime import datetime,timezone
import json
import sqlite3

from . import events as event_log
from .redaction import redact
from .contracts import Event,WSCError,digest,encode,require
from .tool_results import ToolText

STATES=('prepared','blob_staged','committed','recovery_required','aborted')
OPEN=('prepared','blob_staged','recovery_required')
SCHEMA=(
    'CREATE TABLE IF NOT EXISTS wsc_context_intents_v1('
    'op_id TEXT PRIMARY KEY,call_id TEXT NOT NULL,state TEXT NOT NULL,text_sha256 TEXT NOT NULL,'
    'text_bytes INTEGER NOT NULL,meta TEXT NOT NULL,event TEXT NOT NULL,result_id TEXT,view TEXT,'
    'created_at TEXT NOT NULL,updated_at TEXT NOT NULL,note TEXT)',
    'CREATE INDEX IF NOT EXISTS wsc_context_intents_open ON wsc_context_intents_v1(state,created_at)',
    'CREATE INDEX IF NOT EXISTS wsc_context_intents_call ON wsc_context_intents_v1(call_id)',
)


def _now():return datetime.now(timezone.utc).isoformat(timespec='microseconds')


class DurableResults:
    def __init__(self,core,results,references,*,fault=None):
        self.core,self.results,self.references=core,results,references
        self.fault=fault or (lambda point:None)
        with core.store.transaction() as db:
            for statement in SCHEMA:db.execute(statement)

    def _row(self,db,op_id):
        row=db.execute('SELECT * FROM wsc_context_intents_v1 WHERE op_id=?',(op_id,)).fetchone()
        require(row is not None,'context_intent_missing')
        return dict(row)

    def _mark(self,op_id,state,*,result_id=None,view=None,note=None):
        require(state in STATES,'context_intent_state_invalid')
        with self.core.store.transaction() as db:
            row=self._row(db,op_id)
            require(row['state']!=state or state=='recovery_required','context_intent_state_conflict')
            db.execute('UPDATE wsc_context_intents_v1 SET state=?,updated_at=?,'
                       'result_id=COALESCE(?,result_id),view=COALESCE(?,view),note=? WHERE op_id=?',
                       (state,_now(),result_id,view,note,op_id))

    def pending(self,*,limit=32):
        with self.core.store.connect() as db:
            return [dict(r) for r in db.execute(
                'SELECT * FROM wsc_context_intents_v1 WHERE state IN (?,?,?) '
                'ORDER BY created_at,op_id LIMIT ?',(*OPEN,limit))]

    def open_count(self):
        with self.core.store.connect() as db:
            return db.execute('SELECT COUNT(*) FROM wsc_context_intents_v1 WHERE state IN (?,?,?)',
                              OPEN).fetchone()[0]

    def present(self,event,value):
        original,plan=self.results.plan(event.call_id,value)
        if plan is None:
            self._commit(event,original,None)
            return original
        op_id='op-'+digest(dict(event=event.id,sha=plan['digest']))
        with self.core.store.transaction() as db:
            row=db.execute('SELECT * FROM wsc_context_intents_v1 WHERE op_id=?',(op_id,)).fetchone()
            if row is None:
                db.execute('INSERT INTO wsc_context_intents_v1('
                           'op_id,call_id,state,text_sha256,text_bytes,meta,event,result_id,view,'
                           'created_at,updated_at,note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                           (op_id,event.call_id,'prepared',plan['digest'],plan['size'],
                            encode(plan['meta']),encode(vars(event)),None,None,_now(),_now(),None))
            else:
                require(row['text_sha256']==plan['digest'],'context_intent_identity_conflict')
                if row['state']=='committed':return json.loads(row['view'])
                if row['state']=='aborted':  # explicit retry after a proven abort
                    db.execute("UPDATE wsc_context_intents_v1 SET state='prepared',updated_at=?,"
                               "note=NULL WHERE op_id=?",(_now(),op_id))
                require(row['state'] in OPEN or row['state']=='aborted','context_intent_state_conflict')
        self.fault('before_blob')
        try:view,rid,_=self.results.materialize(plan)
        except WSCError as error:
            if str(error)=='tool_result_view_not_smaller':
                self._mark(op_id,'aborted',note='view_not_smaller')
                return {**original,'externalization_note':'no_bounded_smaller_view'}
            raise
        except (OSError,sqlite3.Error) as error:
            self._mark(op_id,'aborted',note=type(error).__name__)
            return {**original,'externalization_error':type(error).__name__}
        self.fault('after_blob')
        self._mark(op_id,'blob_staged',result_id=rid)
        self.fault('before_commit')
        self._commit(event,view,rid,op_id=op_id)
        self.fault('after_commit')
        return view

    def _commit(self,event,view,result_id,*,op_id=None):
        with self.core.store.transaction() as db:
            if op_id is not None:require(self._row(db,op_id)['state'] in OPEN,'context_intent_state_conflict')
            event_log.ingest(db,[event])
            if result_id is not None:self.references.bind_in(db,event.id,result_id,view)
            stored=json.loads(encode(view))
            if not view.get('external'):
                stored.pop('text',None);stored['text_reference']='original_source_text'
            data=encode(stored)
            old=db.execute('SELECT data FROM wsc_context_delivery_v1 WHERE source_id=?',(event.id,)).fetchone()
            require(old is None or old[0]==data,'context_delivery_identity_conflict')
            if old is None:db.execute('INSERT INTO wsc_context_delivery_v1 VALUES (?,?,?)',
                                      (event.id,data,digest(stored)))
            if op_id is not None:
                db.execute("UPDATE wsc_context_intents_v1 SET state='committed',updated_at=?,"
                           "result_id=?,view=?,note=NULL WHERE op_id=?",
                           (_now(),result_id,encode(view),op_id))
        self.fault('after_commit_tx')

    def recover(self,*,limit=32):
        report=dict(scanned=0,committed=0,aborted=0,blocked=0,details=[])
        for row in self.pending(limit=limit):
            report['scanned']+=1
            outcome=self._recover_one(row);report[outcome]+=1
            report['details'].append(dict(op_id=row['op_id'],prior_state=row['state'],outcome=outcome))
        report['blobs']=self._collect_orphan_blobs()
        return report

    def _collect_orphan_blobs(self):
        """Recovery is the only moment the open-intent set is authoritative."""
        from . import blob_gc
        rows=self.pending(limit=1000000)
        keep=blob_gc.live_hashes(self.results.store,
                                 call_ids=[row['call_id'] for row in rows],
                                 result_ids=[row['result_id'] for row in rows])
        try:
            return blob_gc.collect(self.results.store,keep_hashes=keep,dry_run=False)
        except (WSCError,OSError) as error:
            # Reclaiming surplus is never allowed to block recovery itself.
            return dict(orphans=[],removed=[],error=str(error))

    def _record(self,row):
        rid=row['result_id'] or self.results.store.find(row['call_id'])
        return None if rid is None else self.results.store.record(rid)

    def _view_for(self,row,record,text):
        if row['view']:return json.loads(row['view'])
        meta=json.loads(row['meta'])
        value=ToolText(text=text,kind=meta['kind'],status=meta['status'],exit_code=meta['exit_code'],
                       timed_out=meta['timed_out'],source=meta['source'],facts=meta['facts'],
                       observed_at=meta['observed_at'])
        _,plan=self.results.plan(row['call_id'],value)
        require(plan is not None,'context_intent_view_unavailable')
        require(plan['view']['result_id']==record['id'],'context_intent_view_mismatch')
        return plan['view']

    def _recover_one(self,row):
        op_id=row['op_id'];record=self._record(row)
        if record is None:
            self._mark(op_id,'aborted',note='blob_unavailable');return 'aborted'
        if record['hash']!=row['text_sha256']:
            self._mark(op_id,'recovery_required',note='blob_hash_mismatch');return 'blocked'
        try:
            text=self.results.store.text(record)
            data=json.loads(row['event']);data['text']=text
            self._commit(Event(**data),self._view_for(row,record,text),record['id'],op_id=op_id)
        except WSCError as error:
            self._mark(op_id,'recovery_required',note=redact(str(error)));return 'blocked'
        return 'committed'
