"""Opt-in exact discovery over sealed snapshot text; live validation on hits."""
from dataclasses import dataclass
from hashlib import sha256
from time import monotonic
from .source_access import SnapshotSourceAccess,SourceAccessLimits,serialized
from .contracts import require,digest,encode,WSCError
from .evidence import authorize


@dataclass(frozen=True)
class SnapshotSearchLimits:
    max_catalog_text_bytes:int=16*1024*1024
    max_catalog_sources:int=65536
    max_scan_sources_per_call:int=8192
    max_scan_milliseconds_per_call:int=250


def bounded_utf8_size(text,ceiling):
    require(len(text)<=ceiling,'snapshot_catalog_budget_exhausted')
    size=0
    for offset in range(0,len(text),16384):
        size+=len(text[offset:offset+16384].encode('utf-8'))
        require(size<=ceiling,'snapshot_catalog_budget_exhausted')
    return size


class SnapshotLiteralAccess(SnapshotSourceAccess):
    def __init__(self,store,snapshot,*,access,limits=SourceAccessLimits(),search_limits=SnapshotSearchLimits()):
        require(all(type(v) is int and v>0 for v in vars(search_limits).values()),'snapshot_search_limits_invalid')
        require(len(snapshot.events)<=search_limits.max_catalog_sources,'snapshot_catalog_source_budget_exhausted')
        super().__init__(store,snapshot,access=access,limits=limits)
        self.search_limits=search_limits;self.catalog={};total=0
        for row in snapshot.events:
            if row['kind']=='opaque':continue
            text=row.get('text');frozen={**row,'text':text};alias='s'+str(frozen['seq'])
            require(alias in self.bound and frozen['id']==self.bound[alias] and digest(frozen)==self.seals[alias],
                'snapshot_catalog_binding_changed')
            require(text is None or isinstance(text,str),'snapshot_catalog_text_invalid')
            size=bounded_utf8_size(text,search_limits.max_catalog_text_bytes-total) if isinstance(text,str) else 0
            total+=size;self.catalog[alias]=(text,size)
        require(list(self.catalog)==self.order,'snapshot_catalog_order_changed')
        self.catalog_bytes=total;self.snapshot_sources_scanned=0;self.snapshot_text_bytes_scanned=0

    def describe(self):
        return {**super().describe(),'search_basis':'sealed_snapshot_public_text',
            'storage_validation':'Returned matches use live source validation. Negative results describe snapshot text, not current storage health.',
            'search_limits':vars(self.search_limits),
            'scan_deadline':'Cooperative between sources; permission callbacks and database operations are not preempted.',
            'max_rows_per_call_scope':'Live source validations; snapshot scan sources have a separate limit.'}

    def _search_finish(self,value):
        return self._finish({**value,'search_metrics':dict(snapshot_sources_scanned=self.snapshot_sources_scanned,
            snapshot_public_text_bytes_scanned=self.snapshot_text_bytes_scanned)})

    @serialized
    def find(self,literal,*,cursor=0,limit=8):
        self._begin()
        require(type(literal) is str and 0<len(literal)<=256,'source_access_literal_invalid')
        require(type(cursor) is int and 0<=cursor<=len(self.order) and type(limit) is int and 0<limit<=self.limits.max_matches,'source_access_cursor_invalid')
        matches=[];errors=[];index=cursor;scanned=0;verified=0
        deadline=monotonic()+self.search_limits.max_scan_milliseconds_per_call/1000
        with self.store.connect() as db:
            while index<len(self.order) and scanned<self.search_limits.max_scan_sources_per_call:
                alias=self.order[index];text,size=self.catalog[alias]
                if monotonic()>=deadline:
                    errors.append(dict(source=alias,code='snapshot_search_time_budget_exhausted'));break
                scanned+=1;self.snapshot_sources_scanned+=1
                try:
                    authorize(self.store,self.access,self.bound[alias])
                    if isinstance(text,str) and self.text_bytes_examined+size>self.limits.max_text_bytes_total:
                        errors.append(dict(source=alias,code='source_access_text_budget_exhausted'));break
                    position=-1
                    if isinstance(text,str):
                        self.text_bytes_examined+=size;self.snapshot_text_bytes_scanned+=size;position=text.find(literal)
                    authorize(self.store,self.access,self.bound[alias])
                    if position>=0:
                        if self.rows_verified>=self.limits.max_rows_total or verified>=self.limits.max_rows_per_call:
                            errors.append(dict(source=alias,code='source_access_row_budget_exhausted'));break
                        row=self._row(db,alias);verified+=1
                        # Live row seal must match the same snapshot used by the
                        # catalog. Returned text always comes from that live row.
                        start=max(0,position-128);end=min(len(row['text']),position+len(literal)+128)
                        value=row['text'][start:end]
                        item={**self._meta(alias,row),'match_start':position,'match_end':position+len(literal),
                            'text':value,'start':start,'end':end,'text_sha256':sha256(value.encode()).hexdigest()}
                        tentative=dict(status='partial',matches=matches+[item],errors=errors,complete=False,next_cursor=index+1)
                        if len(encode(tentative).encode())+1024>self.limits.max_return_bytes:
                            if not matches:errors.append(dict(source=alias,code='source_access_return_budget_exhausted'))
                            break
                        matches.append(item)
                except WSCError as error:
                    errors.append(dict(source=alias,code=str(error)));index+=1
                    if len(errors)>=8:break
                    continue
                index+=1
                if len(matches)>=limit:break
        complete=index==len(self.order) and not errors
        return self._search_finish(dict(status='ok' if complete else 'partial',matches=matches,errors=errors,complete=complete,
            next_cursor=index if index<len(self.order) else None,
            coverage={'start_cursor':cursor,'end_cursor':index,'total_sources':len(self.order)},
            search_basis='sealed_snapshot_public_text',storage_validation='returned_matches_only',
            matching='first exact literal match per source; source-order pagination, no relevance ranking'))
