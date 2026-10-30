"""Host-neutral query definition and bounded dispatch; no result re-summarization."""
from copy import deepcopy
import sqlite3
from ..contracts import encode,require,WSCError

DEFINITION={'type':'function','name':'WSCResult',
    'description':'Original externalized tool text. read uses UTF-8 byte offsets; read_lines uses 1-based line starts. find is exact literal matching. json_pointer uses RFC6901. Queries are paged original data, not summaries.',
    'inputSchema':{'type':'object','properties':{
        'operation':{'type':'string','enum':['read','read_lines','find','json_pointer']},
        'result_id':{'type':'string'},'offset':{'type':'integer','minimum':0},
        'start_line':{'type':'integer','minimum':1},'cursor':{'type':'integer','minimum':0},
        'limit':{'type':'integer','minimum':1,'maximum':32768},
        'literal':{'type':'string'},'pointer':{'type':'string'}},
        'required':['operation','result_id'],'additionalProperties':False}}


class ResultQueryTool:
    def __init__(self,api,*,max_calls=64,max_return_bytes=32768):
        require(type(max_calls) is int and max_calls>0 and type(max_return_bytes) is int and max_return_bytes>=1024,'tool_result_query_limits_invalid')
        self.api,self.max_calls,self.max_return_bytes,self.calls=api,max_calls,max_return_bytes,0

    def definition(self):return deepcopy(DEFINITION)

    def query(self,args):
        require(self.calls<self.max_calls,'tool_result_query_call_limit');self.calls+=1
        require(type(args) is dict,'tool_result_query_arguments_invalid')
        operation=args.get('operation');rid=args.get('result_id')
        fields={'read':{'offset','limit'},'read_lines':{'start_line','limit'},
                'find':{'literal','cursor','limit'},'json_pointer':{'pointer'}}
        require(type(operation) is str and operation in fields and not set(args)-fields[operation]-{'operation','result_id'},'tool_result_query_arguments_invalid')
        kwargs={k:v for k,v in args.items() if k not in {'operation','result_id'}}
        if operation in {'find','json_pointer'}:require(('literal' if operation=='find' else 'pointer') in kwargs,'tool_result_query_arguments_invalid')
        value=getattr(self.api,operation)(rid,**kwargs)
        require(len(encode(value).encode())<=self.max_return_bytes,'tool_result_query_return_limit')
        return value

    def call(self,args):
        from . import ToolText
        try:value=self.query(args);status='success'
        except WSCError as error:value=dict(status='error',code=str(error),recovery=True);status='error'
        except (OSError,ValueError,RecursionError,sqlite3.Error):value=dict(status='error',code='tool_result_query_failed',recovery=True);status='error'
        return ToolText(encode(value),status=status,recovery=True)
