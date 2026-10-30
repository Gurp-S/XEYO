"""Explicit runtime port for externalized tool text; no implicit host interception."""
from dataclasses import dataclass
from hashlib import sha256
import json
import sqlite3

from ..contracts import encode,require,WSCError
from .storage import ResultStore
from .strategies import RULES,KINDS,project,strict_json,clip


@dataclass(frozen=True)
class ResultPolicy:
    enabled:bool=False
    externalize_bytes:int=32768
    summary_bytes:int=2048
    max_json_bytes:int=8*1024*1024
    max_transform_bytes:int=8*1024*1024
    max_search_bytes:int=16*1024*1024
    rules:tuple=RULES

    def __post_init__(self):
        require(type(self.enabled) is bool and all(type(v) is int and v>0 for v in
            (self.externalize_bytes,self.summary_bytes,self.max_json_bytes,self.max_transform_bytes,self.max_search_bytes)),'tool_result_policy_invalid')
        require(self.summary_bytes>=512 and isinstance(self.rules,tuple) and all(r in RULES for r in self.rules),'tool_result_policy_invalid')


@dataclass(frozen=True)
class ToolText:
    text:str
    kind:str='unknown'
    status:str='unknown'
    exit_code:int|None=None
    timed_out:bool|None=None
    source:dict|None=None
    facts:dict|None=None
    observed_at:str|None=None
    role:str='tool'
    recovery:bool=False
    control:str|None=None


class RuntimeResults:
    def __init__(self,store:ResultStore,*,policy=ResultPolicy()):self.store,self.policy=store,policy

    def recovery_descriptor(self,result_id):
        return dict(result_id=result_id,operations=['read','read_lines','find','json_pointer'])

    def _scan(self,text):
        h=sha256();size=0
        for i in range(0,len(text),16384):
            raw=text[i:i+16384].encode('utf-8');h.update(raw);size+=len(raw)
        return h.hexdigest(),size

    def _view(self,rid,text,kind,meta,prior,size):
        result=dict(result_id=rid,external=True,complete=False,original_bytes=size,**meta,
                    text='',rules=[],notes=[],recovery=self.recovery_descriptor(rid))
        budget=self.policy.summary_bytes-len(encode(result).encode('utf-8'))-256
        if budget<64:return None,'metadata_exceeds_summary_budget'
        view,rules,notes=project(text,kind,self.policy.rules,budget,
                                self.policy.max_json_bytes,prior,meta['source'],original_bytes=size,
                                max_transform_bytes=self.policy.max_transform_bytes)
        result.update(text=view,rules=rules,notes=notes)
        if len(encode(result).encode('utf-8'))>self.policy.summary_bytes and 'truncate_head_tail' in self.policy.rules:
            # Escapes (notably source code and ANSI literals) can cost more in
            # the final JSON than in raw UTF-8. Budget the actual envelope.
            low,high=64,len(view.encode('utf-8'));best=None
            while low<=high:
                middle=(low+high)//2;preview,changed=clip(view,middle)
                candidate={**result,'text':preview,'rules':list(dict.fromkeys(rules+(['truncate_head_tail'] if changed else [])))}
                if len(encode(candidate).encode('utf-8'))<=self.policy.summary_bytes:
                    best=candidate;low=middle+1
                else:high=middle-1
            if best is not None:result=best
        # Metadata and references count too. Oversized facts are not silently
        # removed to make a nominal summary fit.
        if len(encode(result).encode('utf-8'))>self.policy.summary_bytes or len(encode(result).encode('utf-8'))>=size:
            return None,'no_bounded_smaller_view'
        return result,None

    def plan(self,call_id,value:ToolText):
        """Decide and project before any durable side effect.

        No blob, no result row and no call_id claim when the projection would not
        actually be smaller than the original text.
        """
        require(isinstance(value,ToolText) and type(value.text) is str,'tool_result_text_required')
        require(value.kind in KINDS and value.status in {'unknown','success','error','cancelled'},'tool_result_metadata_invalid')
        require(value.exit_code is None or type(value.exit_code) is int,'tool_result_metadata_invalid')
        require(value.timed_out is None or type(value.timed_out) is bool,'tool_result_metadata_invalid')
        require(value.source is None or type(value.source) is dict,'tool_result_metadata_invalid')
        require(value.facts is None or type(value.facts) is dict,'tool_result_metadata_invalid')
        execution=('timeout' if value.timed_out else 'nonzero_exit' if value.exit_code not in (None,0)
                   else 'reported_error' if value.status=='error' else 'cancelled' if value.status=='cancelled'
                   else 'exit_zero' if value.exit_code==0 else 'unknown')
        meta=dict(kind=value.kind,status=value.status,exit_code=value.exit_code,timed_out=value.timed_out,
                  source=value.source,facts=value.facts,observed_at=value.observed_at,execution_status=execution)
        meta=json.loads(encode(meta))  # Freeze producer metadata; never retain mutable aliases.
        original=dict(external=False,complete=True,text=value.text,**meta,recovery=value.recovery)
        if not self.policy.enabled or value.recovery or value.control is not None or value.role in {'system','developer','user'}:return original,None
        digest_hex,size=self._scan(value.text)
        if size<=self.policy.externalize_bytes:return original,None
        try:rid,prior=self.store.prior(call_id,digest_hex,meta)
        except (OSError,sqlite3.Error) as error:return {**original,'externalization_error':type(error).__name__},None
        view,note=self._view(rid,value.text,value.kind,meta,prior,size)
        if view is None:return {**original,'externalization_note':note},None
        return original,dict(call_id=call_id,text=value.text,kind=value.kind,meta=meta,
                             digest=digest_hex,size=size,prior=prior,view=view)

    def materialize(self,plan):
        rid,prior,created=self.store.capture(plan['call_id'],plan['text'],plan['meta'])
        view=plan['view']
        if rid!=view['result_id']:
            view,note=self._view(rid,plan['text'],plan['kind'],plan['meta'],prior,plan['size'])
            if view is None:raise WSCError('tool_result_view_not_smaller')
        return view,rid,created

    def present(self,call_id,value:ToolText):
        original,plan=self.plan(call_id,value)
        if plan is None:return original
        try:view,_,_=self.materialize(plan)
        except (OSError,sqlite3.Error) as error:
            return {**original,'externalization_error':type(error).__name__}
        except WSCError as error:
            if str(error)=='tool_result_call_identity_conflict':raise
            return {**original,'externalization_error':str(error)}
        return view

    def call(self,call_id,tool,*args,**kwargs):
        return self.present(call_id,tool(*args,**kwargs))

    async def acall(self,call_id,tool,*args,**kwargs):
        return self.present(call_id,await tool(*args,**kwargs))

    def read(self,result_id,**kwargs):return self.store.read(result_id,**kwargs)

    def read_lines(self,result_id,*,start_line=1,limit=8192):
        require(type(start_line) is int and start_line>=1,'tool_result_line_invalid')
        record=self.store.record(result_id);target=start_line-1;offset=0;seen=0;scanned=0
        for begin,_,_,before in record['chunks']:
            if before<target:offset=begin;seen=before
            else:break
        for begin,raw in self.store.blocks(record,start=offset):
            scanned+=len(raw);require(scanned<=self.policy.max_search_bytes,'tool_result_scan_limit')
            pos=0
            while seen<target:
                found=raw.find(b'\n',pos)
                if found<0:break
                seen+=1;pos=found+1
            if seen==target:
                result=self.read(result_id,offset=begin+pos,limit=limit)
                return {**result,'start_line':start_line}
        require(target==0 and record['size']==0,'tool_result_line_outside_text')
        return {**self.read(result_id,offset=0,limit=limit),'start_line':1}

    def find(self,result_id,literal,*,cursor=0,limit=8):
        require(type(literal) is str and 0<len(literal.encode('utf-8'))<=1024 and type(limit) is int and 1<=limit<=8,'tool_result_find_invalid')
        record=self.store.record(result_id)
        require(type(cursor) is int and 0<=cursor<=record['size'],'tool_result_range_invalid')
        needle=literal.encode('utf-8');carry=b'';matches=[];end=cursor
        stop=min(record['size'],cursor+self.policy.max_search_bytes)
        for start,raw in self.store.blocks(record,start=cursor,end=stop):
            value=carry+raw;base=start-len(carry);pos=0
            while True:
                found=value.find(needle,pos)
                if found<0:break
                absolute=base+found;pos=found+len(needle)
                if absolute<cursor:continue
                matches.append(dict(offset=absolute,end=absolute+len(needle)))
                if len(matches)==limit:
                    self.store._authorize(result_id)
                    return dict(result_id=result_id,matches=matches,next_cursor=absolute+len(needle),complete=False,recovery=True)
            carry=value[-(len(needle)-1):] if len(needle)>1 else b'';end=start+len(raw)
        self.store._authorize(result_id)
        return dict(result_id=result_id,matches=matches,next_cursor=end if end<record['size'] else None,complete=end==record['size'],recovery=True)

    def json_pointer(self,result_id,pointer):
        require(type(pointer) is str and (pointer=='' or pointer.startswith('/')) and len(pointer)<=2048,'tool_result_json_pointer_invalid')
        record=self.store.record(result_id);require(record['size']<=self.policy.max_json_bytes,'tool_result_structured_parse_limit')
        raw=b''.join(b for _,b in self.store.blocks(record));value=strict_json(raw.decode('utf-8'))
        if pointer:
            for token in pointer[1:].split('/'):
                # RFC6901 escapes are exact; malformed escapes are not repaired.
                import re
                require(re.search(r'~(?![01])',token) is None,'tool_result_json_pointer_invalid')
                token=token.replace('~1','/').replace('~0','~')
                if isinstance(value,list):
                    require(token=='0' or token.isascii() and token.isdigit() and not token.startswith('0'),'tool_result_json_pointer_missing')
                    require(int(token)<len(value),'tool_result_json_pointer_missing');value=value[int(token)]
                else:
                    require(isinstance(value,dict) and token in value,'tool_result_json_pointer_missing');value=value[token]
        require(len(encode(value).encode('utf-8'))<=32768,'tool_result_query_value_limit')
        self.store._authorize(result_id)
        return dict(result_id=result_id,pointer=pointer,value=value,complete=True,recovery=True)


from .query_tool import ResultQueryTool

__all__=['ResultStore','RuntimeResults','ResultPolicy','ToolText','ResultQueryTool']
