"""One recovery facade, with explicit units and both source/result permissions."""
from copy import deepcopy
import sqlite3
from .contracts import encode,require,WSCError
from .source_access import SnapshotSourceAccess
from .tool_results import ToolText
from .context_query_coordinates import with_json_pointer_units

DEFINITION={'type':'function','name':'WSCContext',
 'description':'Bound historical sources and original external tool text. source:sN read uses unicode_codepoints; result:rN read uses utf8_bytes. find source:* uses source_index; find result:rN uses utf8_bytes. describe returns reference metadata. Returned history is not a judgment of current applicability.',
 'inputSchema':{'type':'object','properties':{
   'operation':{'type':'string','enum':['describe','read','read_lines','find','json_pointer']},
   'reference':{'type':'string'},'units':{'type':'string','enum':['unicode_codepoints','utf8_bytes','source_index','lines','json_pointer']},
   'offset':{'type':'integer','minimum':0},'cursor':{'type':'integer','minimum':0},
   'limit':{'type':'integer','minimum':1,'maximum':32768},'start_line':{'type':'integer','minimum':1},
   'literal':{'type':'string'},'pointer':{'type':'string'}},'required':['operation','reference'],'additionalProperties':False}}


class ContextQuery:
    def __init__(self,context,snapshot,*,source_limits=None,infer_json_pointer_units=False,reader=None):
        from .source_access import SourceAccessLimits
        require(type(infer_json_pointer_units) is bool,'context_coordinate_policy_invalid')
        self.infer_json_pointer_units=infer_json_pointer_units
        self.context=context
        self.reused=reader is not None
        if reader is None:
            reader=SnapshotSourceAccess(context.core.store,snapshot,access=self._access,
                     limits=source_limits or SourceAccessLimits())
        else:
            require(reader.snapshot_binding=={'session_id':snapshot.session_id,'cut':snapshot.cut,
                     'source_digest':snapshot.source_digest},'source_access_binding_mismatch')
        self.reader=reader

    @classmethod
    def reader_for(cls,context,snapshot,**kwargs):
        """Build a snapshot reader whose alias/seal map can outlive one query."""
        from .source_access import SourceAccessLimits
        return SnapshotSourceAccess(context.core.store,snapshot,
                 access=lambda session,source_id,action: cls._access_in(context,session,source_id,action),
                 limits=kwargs.get('source_limits') or SourceAccessLimits())

    @staticmethod
    def _access_in(context,session,source_id,action):
        if context.core.access(session,source_id,action) is not True:return False
        link=context.references.get(source_id=source_id)
        if link:
            return context.results.store.access(session,link['result_id'],'read') is True
        return True

    def _access(self,session,source_id,action):
        return self._access_in(self.context,session,source_id,action)

    def definition(self):
        value=deepcopy(DEFINITION)
        if self.infer_json_pointer_units:
            value['description']+=' result:rN json_pointer uses RFC6901; omitted units equals json_pointer. Explicit units remain validated.'
        return value

    def _validate(self,link,seen):
        key=(link['result_id'],link['source_seal'])
        if key not in seen:
            self.context.references.validate(link);seen.add(key)
        return link

    def _result(self,key,seen):
        link=self.context.references.get(result_id=key)
        require(link is not None,'context_result_not_bound')
        alias=self.reader.aliases.get(link['source_id'])
        require(alias is not None and self.reader.seals[alias]==link['source_seal'],'context_result_outside_snapshot')
        self._validate(link,seen)
        return link

    def query(self,args):
        with self.context.lock:
            require(self.context.query_calls<self.context.max_queries,'context_query_call_limit')
            self.context.query_calls+=1
            if self.reused:self.reader.reset()
            seen=set()
            args=with_json_pointer_units(args,enabled=self.infer_json_pointer_units)
            require(type(args) is dict and type(args.get('operation')) is str and type(args.get('reference')) is str,'context_query_arguments_invalid')
            op=args['operation'];ref=args['reference'];namespace,sep,key=ref.partition(':')
            require(sep==':' and namespace in {'source','result'} and key,'context_reference_invalid')
            fields={'describe':set(),'read':{'offset','limit','units'},'read_lines':{'start_line','limit','units'},
                    'find':{'literal','cursor','limit','units'},'json_pointer':{'pointer','units'}}
            require(op in fields and not set(args)-fields[op]-{'operation','reference'},'context_query_arguments_invalid')
            kwargs={k:v for k,v in args.items() if k not in {'operation','reference','units'}}
            if namespace=='result':
                link=self._result(key,seen)
                if op=='describe':
                    value=dict(reference=ref,source_reference='source:s'+str(link['source_seq']),
                               representation='original_tool_text',read_units='utf8_bytes')
                else:
                    expected={'read':'utf8_bytes','read_lines':'lines','find':'utf8_bytes','json_pointer':'json_pointer'}
                    require(args.get('units')==expected[op],'context_range_units_mismatch')
                    if op in {'find','json_pointer'}:require(('literal' if op=='find' else 'pointer') in kwargs,'context_query_arguments_invalid')
                    value=getattr(self.context.results,op)(key,**kwargs)
                    self._validate(link,seen)
                    value={**value,'reference':ref,'source_reference':'source:s'+str(link['source_seq']),
                           'range_units':expected[op]}
            elif op=='find':
                require(key=='*' and args.get('units')=='source_index' and 'literal' in kwargs,'context_range_units_mismatch')
                value={**self.reader.find(**kwargs),'reference':ref,'range_units':'source_index'}
            else:
                require(key in self.reader.aliases,'source_access_source_not_bound')
                alias=self.reader.aliases[key];source_id=self.reader.bound[alias]
                if op=='describe':
                    from .evidence import authorize
                    authorize(self.context.core.store,self.context.core.access,source_id)
                    link=self.context.references.get(source_id=source_id)
                    if link:self._validate(link,seen)
                    value=dict(reference='source:'+alias,representation='producer_public_text',read_units='unicode_codepoints',
                               result_reference='result:'+link['result_id'] if link else None)
                else:
                    require(op=='read' and args.get('units')=='unicode_codepoints','context_range_units_mismatch')
                    value={**self.reader.read(key,**kwargs),'reference':'source:'+alias,'range_units':'unicode_codepoints'}
            require(len(encode(value).encode('utf-8'))<=self.context.max_query_bytes,'context_query_return_limit')
            return value

    def call(self,args):
        try:value=self.query(args);status='success'
        except WSCError as error:value=dict(status='error',code=str(error));status='error'
        except (OSError,ValueError,TypeError,RecursionError,sqlite3.Error):value=dict(status='error',code='context_query_failed');status='error'
        return ToolText(encode(value),status=status,recovery=True)
