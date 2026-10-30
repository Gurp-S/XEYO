"""Opt-in bounded source access. Literal retrieval is not semantic ranking."""
from dataclasses import dataclass
from hashlib import sha256
from threading import RLock
from functools import wraps
from .contracts import require,digest,encode,WSCError
from .evidence import source_row,authorize


@dataclass(frozen=True)
class SourceAccessLimits:
    max_calls:int=8
    max_rows_per_call:int=256
    max_rows_total:int=512
    max_chars:int=8192
    max_matches:int=8
    max_return_bytes:int=16384
    max_row_bytes:int=1048576
    max_text_bytes_total:int=2097152


def serialized(method):
    @wraps(method)
    def call(self,*args,**kwargs):
        with self.lock:return method(self,*args,**kwargs)
    return call


class SnapshotSourceAccess:
    def __init__(self,store,snapshot,*,access,limits=SourceAccessLimits()):
        require(store.session_id==snapshot.session_id and store.workspace==snapshot.workspace,'source_access_binding_mismatch')
        require(all(type(v) is int and v>0 for v in vars(limits).values()) and limits.max_return_bytes>=1024,'source_access_limits_invalid')
        self.store,self.access,self.limits=store,access,limits
        self.snapshot_binding={'session_id':snapshot.session_id,'cut':snapshot.cut,'source_digest':snapshot.source_digest}
        self.aliases={};self.bound={};self.order=[];self.seals={}
        for row in snapshot.events:
            if row['kind']=='opaque':continue
            alias='s'+str(row['seq']);identity=row['id']
            for key in (alias,identity):
                require(key not in self.aliases or self.aliases[key]==alias,'source_access_alias_ambiguous')
                self.aliases[key]=alias
            self.bound[alias]=identity;self.order.append(alias);self.seals[alias]=digest(row)
        self.calls=0;self.rows_verified=0;self.text_bytes_examined=0
        self.ledger_key=snapshot.session_id
        self.lock=RLock()
    def reset(self):
        """Zero per-query counters so a reused reader keeps per-query budgets."""
        with self.lock:
            self._account()
            self.calls=self.rows_verified=self.text_bytes_examined=0
    def _account(self):
        """Persist a finished query's spend, outside any read transaction.

        Accounting runs after the read is over (reset is the query boundary), so
        it never upgrades or nests the reader's transaction; a failure to record
        spend cannot fail a read that already succeeded.
        """
        if not (self.calls or self.rows_verified or self.text_bytes_examined):return
        from . import query_ledger
        try:
            with self.store.transaction() as db:
                query_ledger.spend(db,self.ledger_key,calls=self.calls,
                                   rows=self.rows_verified,text_bytes=self.text_bytes_examined)
        except Exception:
            pass
    def describe(self):
        return dict(operations=['read','find'],source_aliases='s<event seq>; original IDs also accepted',
            representation='Original producer public text; interpretation and current applicability remain unverified.',
            range_units='Unicode code points, not UTF-8 byte offsets',
            find='Case-sensitive exact literal; one first match per source; source order without ranking.',
            limits=vars(self.limits),snapshot_sources=len(self.order))
    def _begin(self):
        require(self.calls<self.limits.max_calls,'source_access_call_budget_exhausted')
        self._require_persisted()
        self.calls+=1
    def _require_persisted(self):
        """A restart must not refill the cumulative budget."""
        from . import query_ledger
        try:
            with self.store.transaction() as db:
                seen=query_ledger.totals(db,self.ledger_key)
        except Exception:
            return
        require(seen['calls']<self.limits.max_calls,'source_access_call_budget_exhausted')
        require(seen['rows']<=self.limits.max_rows_total,'source_access_row_budget_exhausted')
        require(seen['text_bytes']<=self.limits.max_text_bytes_total,'source_access_text_budget_exhausted')
    def _row(self,db,alias):
        require(self.rows_verified<self.limits.max_rows_total,'source_access_row_budget_exhausted')
        identity=self.bound[alias];authorize(self.store,self.access,identity)
        length=db.execute('SELECT length(CAST(data AS BLOB)) FROM events WHERE id=?',(identity,)).fetchone()
        require(length is not None,'source_unavailable')
        require(length[0]<=self.limits.max_row_bytes,'source_access_record_budget_exhausted')
        row=source_row(db,identity)
        require(digest(row)==self.seals[alias],'source_access_snapshot_changed')
        authorize(self.store,self.access,identity)
        self.rows_verified+=1
        return row
    def _examine(self,text):
        amount=len(text.encode('utf-8'))
        require(self.text_bytes_examined+amount<=self.limits.max_text_bytes_total,'source_access_text_budget_exhausted')
        self.text_bytes_examined+=amount
    def _meta(self,alias,row):
        return dict(source=alias,original_source_id=row['id'],seq=row['seq'],kind=row['kind'],role=row['role'],
            observed_at=row['observed_at'],source_record_sha256=self.seals[alias],representation='producer_public_text')
    def _finish(self,value):
        result={**value,'metrics':dict(calls=self.calls,rows_verified=self.rows_verified,
            public_text_bytes_examined=self.text_bytes_examined,physical_disk_bytes=None)}
        require(len(encode(result).encode('utf-8'))<=self.limits.max_return_bytes,'source_access_return_budget_exhausted')
        return result
    @serialized
    def read(self,source,*,offset=0,limit=2048):
        self._begin();require(type(source) is str and source in self.aliases,'source_access_source_not_bound')
        require(type(offset) is int and offset>=0 and type(limit) is int and 0<limit<=self.limits.max_chars,'source_access_range_invalid')
        alias=self.aliases[source]
        with self.store.connect() as db:row=self._row(db,alias)
        text=row['text'];require(isinstance(text,str),'source_access_public_text_unavailable')
        require(offset<=len(text),'source_access_offset_outside_text')
        self._examine(text)
        meta=self._meta(alias,row);end=min(len(text),offset+limit)
        full_hash=sha256(text.encode('utf-8')).hexdigest()
        def result(stop):
            value=text[offset:stop]
            return {**meta,'status':'ok','text':value,'offset':offset,'end':stop,'total_chars':len(text),
                'next_offset':stop if stop<len(text) else None,'complete':offset==0 and stop==len(text),
                'text_sha256':sha256(value.encode('utf-8')).hexdigest(),'full_text_sha256':full_hash}
        # Bound UTF-8 output while retaining original character positions.
        low,high=offset,end
        while low<high:
            middle=(low+high+1)//2
            if len(encode({**result(middle),'metrics':dict(calls=self.calls,rows_verified=self.rows_verified,public_text_bytes_examined=self.text_bytes_examined,physical_disk_bytes=None)}).encode())<=self.limits.max_return_bytes:low=middle
            else:high=middle-1
        require(low>offset or offset==len(text),'source_access_return_budget_exhausted')
        return self._finish(result(low))
    @serialized
    def find(self,literal,*,cursor=0,limit=8):
        self._begin()
        require(type(literal) is str and 0<len(literal)<=256,'source_access_literal_invalid')
        require(type(cursor) is int and 0<=cursor<=len(self.order) and type(limit) is int and 0<limit<=self.limits.max_matches,'source_access_cursor_invalid')
        matches=[];errors=[];index=cursor;scanned=0
        with self.store.connect() as db:
            while index<len(self.order) and scanned<self.limits.max_rows_per_call:
                alias=self.order[index]
                if self.rows_verified>=self.limits.max_rows_total:
                    errors.append(dict(source=alias,code='source_access_row_budget_exhausted'));break
                scanned+=1
                try:
                    row=self._row(db,alias)
                    text=row['text']
                    if isinstance(text,str):
                        self._examine(text);position=text.find(literal)
                        if position>=0:
                            start=max(0,position-128);end=min(len(text),position+len(literal)+128)
                            item={**self._meta(alias,row),'match_start':position,'match_end':position+len(literal),
                                'text':text[start:end],'start':start,'end':end,
                                'text_sha256':sha256(text[start:end].encode('utf-8')).hexdigest()}
                            tentative=dict(status='partial',matches=matches+[item],errors=errors,complete=False,next_cursor=index+1)
                            # Include final metrics/coverage headroom before adding a match.
                            if len(encode(tentative).encode())+512>self.limits.max_return_bytes:
                                if not matches:errors.append(dict(source=alias,code='source_access_return_budget_exhausted'))
                                break
                            matches.append(item)
                except WSCError as error:
                    errors.append(dict(source=alias,code=str(error)));index+=1
                    if len(errors)>=8 or str(error)=='source_access_row_budget_exhausted':break
                    continue
                index+=1
                if len(matches)>=limit:break
        complete=index==len(self.order) and not errors
        return self._finish(dict(status='ok' if complete else 'partial',matches=matches,errors=errors,
            complete=complete,next_cursor=index if index<len(self.order) else None,
            coverage={'start_cursor':cursor,'end_cursor':index,'total_sources':len(self.order)},
            matching='first exact literal match per source; source-order pagination, no relevance ranking'))
