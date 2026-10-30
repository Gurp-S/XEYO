"""Opt-in host lifecycle: capture, presentation, checkpoints and one recovery port."""
from threading import RLock
import json

from .contracts import Event,Limits,digest,encode,require
from .control_grading import apply_control
from .evidence import source_row,authorize
from .context_references import ContextReferences
from .durable_ops import DurableResults
from .context_query import ContextQuery
from . import integrity
from .context_projection import MODE
from .tool_results import RuntimeResults,ResultPolicy,ToolText


class ContextResults(RuntimeResults):
    def recovery_descriptor(self,result_id):
        return dict(tool='WSCContext',reference='result:'+result_id,
                    operations=['read','read_lines','find','json_pointer'])


class ContextRuntime:
    def __init__(self,core,result_store,*,policy=ResultPolicy(),max_queries=64,max_query_bytes=32768,
                 durable_results=False,fault=None,query_policy='per_query_v1',reader_cache=4,integrity_policy='off'):
        require(type(max_queries) is int and max_queries>0 and type(max_query_bytes) is int and max_query_bytes>=1024,'context_limits_invalid')
        require(query_policy in {'per_query_v1','reader_reuse_v1'},'context_query_policy_invalid')
        require(type(reader_cache) is int and reader_cache>0,'context_limits_invalid')
        require(integrity_policy in {'off','chain_v1'},'context_integrity_policy_invalid')
        self.core=core;self.results=ContextResults(result_store,policy=policy)
        self.references=ContextReferences(core,self.results);self.lock=RLock()
        self.max_queries,self.max_query_bytes,self.query_calls=max_queries,max_query_bytes,0
        self.query_policy,self.reader_cache,self._readers=query_policy,reader_cache,{}
        self.integrity_policy=integrity_policy
        with core.store.transaction() as db:
            if integrity_policy=='chain_v1':integrity.install(db);integrity.install_receipts(db)
            db.execute('CREATE TABLE IF NOT EXISTS wsc_context_delivery_v1(source_id TEXT PRIMARY KEY REFERENCES events(id),data TEXT NOT NULL,seal TEXT NOT NULL)')
        self.durable_ops=DurableResults(core,self.results,self.references,fault=fault) if durable_results else None
        if self.durable_ops is not None and self.durable_ops.open_count():self.durable_ops.recover()

    def recover(self,*,limit=32):
        """Finish or close intents left open by a crash; never invents content."""
        if self.durable_ops is None:return dict(scanned=0,committed=0,aborted=0,blocked=0,details=[])
        return self.durable_ops.recover(limit=limit)

    def observe(self,events):return self.core.ingest(events)

    def record_tool_result(self,event,value):
        require(isinstance(event,Event) and event.kind=='result' and isinstance(value,ToolText),'context_tool_result_invalid')
        require(event.text==value.text,'context_original_text_mismatch')
        with self.lock:
            value=apply_control(value,vars(event))
            if self.durable_ops is not None:return self.durable_ops.present(event,value)
            view=self.results.present(event.call_id,value)
            self.core.ingest([event])
            if view.get('external'):self.references.bind(event.id,view['result_id'],view)
            stored=json.loads(encode(view))
            if not view.get('external'):
                stored.pop('text');stored['text_reference']='original_source_text'
            data=encode(stored)
            with self.core.store.transaction() as db:
                old=db.execute('SELECT data FROM wsc_context_delivery_v1 WHERE source_id=?',(event.id,)).fetchone()
                require(old is None or old[0]==data,'context_delivery_identity_conflict')
                if old is None:db.execute('INSERT INTO wsc_context_delivery_v1 VALUES (?,?,?)',(event.id,data,digest(stored)))
            return view

    def delivery(self,source_id):
        with self.core.store.connect() as db:
            row=db.execute('SELECT data,seal FROM wsc_context_delivery_v1 WHERE source_id=?',(source_id,)).fetchone()
            if row is None:return None
            value=json.loads(row[0]);require(digest(value)==row[1],'context_delivery_integrity_mismatch')
            if value.get('text_reference'):
                source=source_row(db,source_id);authorize(self.core.store,self.core.access,source_id)
                value.pop('text_reference');value['text']=source['text']
            else:
                link=self.references.get(source_id=source_id)
                require(link is not None and link['visible_view']==value,'context_delivery_binding_changed')
                self.references.validate(link)
            return value

    def presented(self,request_id,source_ids,*,receiver):
        # Host receipts are explicit. Returning a tool result does not imply it
        # has entered a model request.
        return self.core.presented(request_id,tuple(source_ids),receiver=receiver)

    def capture(self,**kwargs):return self.core.capture(**kwargs)

    def query_tool(self,snapshot,**kwargs):
        if self.query_policy!='reader_reuse_v1':return ContextQuery(self,snapshot,**kwargs)
        key=(snapshot.session_id,snapshot.workspace,snapshot.cut,snapshot.source_digest)
        reader=self._readers.pop(key,None)
        if reader is None:reader=ContextQuery.reader_for(self,snapshot,**kwargs)
        self._readers[key]=reader
        while len(self._readers)>self.reader_cache:self._readers.pop(next(iter(self._readers)))
        return ContextQuery(self,snapshot,reader=reader,**kwargs)

    def material(self,snapshot):
        value=self.core.material(snapshot)
        for row in value['events']:
            delivered=self.delivery(row['id']) if row['kind']=='result' else None
            if delivered and delivered.get('external'):
                row['text']=encode(delivered);row['text_representation']='runtime_projection'
                row['original_reference']='source:s'+str(row['seq'])
        value['projection']='context_runtime_material_v1'
        return value

    def prepare(self,snapshot,selection,*,producer,limits=Limits()):
        return self.core.prepare(snapshot,selection,producer=producer,limits=limits,source_projection=MODE)

    def stage(self,view_id,*,directory,adapter,archive_directory=None):
        # The adapter is the caller's: a core module that imported one would
        # invert the dependency direction the contract test enforces.
        require(adapter is not None,'context_stage_adapter_required')
        return self.core.stage(view_id,directory=directory,archive_directory=archive_directory,
                               adapter=adapter)

    def validate_package(self,package):
        require(package.get('adapter',{}).get('context_store_binding')==self.references.store_binding,'context_package_binding_mismatch')
        for source_id in package['evidence']:
            link=self.references.get(source_id=source_id)
            if link:
                record=self.references.validate(link)
                for _ in self.results.store.blocks(record):pass

    def install(self,operation_id,host):
        from .publication import operation
        with self.core.store.connect() as db:state=operation(db,operation_id)['state']
        if state=='ready':
            try:self.validate_package(self.core.package(operation_id))
            except Exception:
                # A concurrently settled host commit is a historical fact, not
                # a new candidate requiring current source/file permission.
                with self.core.store.connect() as db:terminal=operation(db,operation_id)['state'] in {'confirmed','rejected'}
                if not terminal:raise
        return self.core.install(operation_id,host)

    def reconcile(self,operation_id,host):return self.core.reconcile(operation_id,host)
