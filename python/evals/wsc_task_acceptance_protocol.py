"""Isolated artifact-based WSC acceptance protocol; preparation is API-free.

Task truth/expected outputs live outside model inputs. Current source snapshots
contain no future events. The artifact sink checks physical scope/serialization,
never task correctness; incorrect work remains observable to the external judge.
"""
from copy import deepcopy
import asyncio
import hashlib
import json
from pathlib import Path

from engine.turn_snapshot import _atomic_write
from engine.abort import AbortController
from memory.wsc_cold_receipt_candidate import ReceiptSources
from memory.wsc_handoff_generation import generate
from model.deepseek import DeepSeekModelClient
from model.chunks import ModelChunk
from tools.todo_write_tool.todo_write_tool import TodoWriteTool

ROOT=Path('D:/lea/XenYon code/_wsc_out/wsc-task-acceptance-270')
CODEX=ROOT.parent/'wsc-expanded-208/vendor/codex'


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def sha(raw):return hashlib.sha256(raw).hexdigest()


class ArtifactSink:
    def __init__(self,root):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True);self.attempts=[]

    @staticmethod
    def schema():
        return {'name':'ArtifactWrite','description':'Saves UTF-8 content in the configured artifact_root. Returns file path, byte count and SHA-256.',
            'input_schema':{'type':'object','properties':{'file_path':{'type':'string'},'content':{'type':'string'}},
                'required':['file_path','content'],'additionalProperties':False}}

    @staticmethod
    def _publish(path, content):
        _atomic_write(path, content, durable=True)

    def call(self,args):
        # Caller executes mutations sequentially. Attempt recording precedes
        # validation; a denied/unchanged write is not silently a no-op decision.
        self.attempts.append(deepcopy(args))
        if not isinstance(args,dict) or set(args)!={'file_path','content'} or any(not isinstance(v,str) for v in args.values()):
            raise ValueError('artifact_invalid_arguments')
        requested=Path(args['file_path']);path=(requested if requested.is_absolute() else self.root/requested).resolve()
        if path==self.root or not path.is_relative_to(self.root):raise ValueError('Permission denied: outside artifact_root')
        raw=args['content'].encode('utf-8')
        if len(raw)>64000:raise ValueError('artifact_size_exceeded')
        self._publish(path,args['content'])
        assert path.read_bytes()==raw
        return {'file_path':str(path),'bytes':len(raw),'sha256':sha(raw)}


def judge(sink,expected,before_hash=None):
    path=sink.root/'result.json'
    actual_hash=sha(path.read_bytes()) if path.is_file() else None
    if expected is None:
        return {'success':not sink.attempts and actual_hash==before_hash,'no_write_required':True,
            'write_attempts':len(sink.attempts),'actual_sha256':actual_hash}
    if not path.is_file():return {'success':False,'reason':'missing_artifact','write_attempts':len(sink.attempts)}
    try:value=json.loads(path.read_text(encoding='utf-8'))
    except (ValueError,UnicodeError):value=None
    correct=isinstance(value,dict) and set(value)==set(expected) and all(
        type(value[k]) is type(v) and value[k]==v for k,v in expected.items())
    targets=[]
    for args in sink.attempts:
        if not isinstance(args,dict) or not isinstance(args.get('file_path'),str):continue
        p=Path(args['file_path']);targets.append((p if p.is_absolute() else sink.root/p).resolve())
    return {'success':correct and bool(targets) and all(p==path for p in targets),
        'artifact_correct':correct,'write_attempts':len(sink.attempts),'actual_sha256':actual_hash}


def scenarios():
    result=[]
    for name in ('config_conversion','asset_manifest'):
        events=[];current=None;version=11;file_version=1
        definition={'id':name+'-format','role':'system','content':
            'DatasetProbe：artifact_id/artifact_version标识输出资料，execution.revision标识执行流水，两种编号不共用。file_version标识同一资料的刷新版本。'}
        for n in range(1,11):
            phase='implementation' if n==1 else 'closed' if n in (5,9) else 'verification'
            refresh=n in (1,2,6,8,10)
            if refresh:
                if n!=8:version+=1
                else:file_version+=1
                artifact_id=name+'-data';xid=name+f'-execution-{211+n*13}'
                data={'artifact_id':artifact_id,'artifact_version':version,'file_version':file_version}
                if name=='config_conversion':data.update(timeout_ms=(n+3)*1000,workers=n+2)
                else:data.update(items=[{'name':'style','bytes':1200+n*17},{'name':'image','bytes':3500+n*23}])
                call=name+f'-probe-{n}'
                receipt={'id':name+f'-receipt-{n}','role':'tool','content':[{'type':'tool_result','tool_use_id':call,
                    'content':canonical(data),'is_error':False,'execution':{'id':xid,'revision':211+n*13,'complete':True,'status':'ok','late':False}}]}
                current={'data':data,'execution_id':xid,'receipt':receipt}
            action=n not in (4,5,9)
            scope='subset' if n in (7,8) else 'full'
            if name=='config_conversion':fields='timeout_s（timeout_ms/1000）'+('和workers' if scope=='full' else '')
            else:fields='total_bytes（items中bytes总和）'+('和item_count' if scope=='full' else '')
            notes={1:'旧的是否导出问题已经解决。进入implementation。本任务不发布、不操作git，仅implementation阶段不运行测试。',
                2:'进入verification，implementation阶段测试限制到期。采用新的资料版本，旧版仅作历史。',
                3:'先前执行迟到回执已经到账，当前采用的资料保持不变。',
                4:'字段定义问题已经确认并解决，本轮不新增文件，其他长期边界不变。',
                5:'本任务已经完成，当前没有文件生成工作。',
                6:'重新打开本任务，采用新资料，进入verification。长期不发布、不操作git仍成立。',
                7:'缩小本轮输出范围，其他汇总项暂停，本轮仅输出指定子集。',
                8:'当前资料发生刷新，以新的file_version为准。输出范围仍是上轮子集。',
                9:'取消本任务，本轮没有文件生成工作。',
                10:'恢复本任务，采用新资料，重新输出完整字段。长期边界不变。'}
            text=notes[n]
            if action:
                text+=f" 当前资料artifact_id={current['data']['artifact_id']}，artifact_version={version}，file_version={file_version}。将artifact_id、artifact_version、file_version、支撑此资料的execution_id以及{fields}保存为artifact_root下result.json。"
            batch=[{'id':name+f'-user-{n}','role':'user','content':text}]
            if n==1:
                delayed_data=deepcopy(data);delayed_data['artifact_version']-=1
                delayed_receipt={'id':name+'-late-receipt','role':'tool','content':[{'type':'tool_result',
                    'tool_use_id':name+'-delayed-probe','content':canonical(delayed_data),'is_error':False,
                    'execution':{'id':name+'-delayed-execution','revision':19,'complete':True,'status':'ok','late':True}}]}
                batch.insert(0,{'id':name+'-delayed-invocation','role':'assistant','content':[{'type':'tool_use',
                    'id':name+'-delayed-probe','name':'DatasetProbe','input':{'artifact_id':delayed_data['artifact_id'],
                        'artifact_version':delayed_data['artifact_version']}}]})
            if refresh:
                batch.extend([{'id':name+f'-invocation-{n}','role':'assistant','content':[{'type':'tool_use','id':call,'name':'DatasetProbe','input':{'artifact_id':data['artifact_id'],'artifact_version':version,'file_version':file_version}}]},receipt])
            if n==3:
                batch.append(deepcopy(delayed_receipt))
            expected=None
            if action:
                d=current['data'];expected={k:d[k] for k in ('artifact_id','artifact_version','file_version')};expected['execution_id']=current['execution_id']
                if name=='config_conversion':
                    expected['timeout_s']=d['timeout_ms']//1000
                    if scope=='full':expected['workers']=d['workers']
                else:
                    expected['total_bytes']=sum(item['bytes'] for item in d['items'])
                    if scope=='full':expected['item_count']=len(d['items'])
            events.append({'step':n,'phase':phase,'sources':deepcopy(batch),'request':text,'expected_artifact':expected,
                'restart_before':n==6,'source_refresh':n==8,'task_state':'resolved' if n==5 else 'cancelled' if n==9 else 'active'})
        result.append({'case':name,'source_definition':definition,'steps':events})
    return result


def visible_sources(case,step):
    return [deepcopy(case['source_definition']),*[deepcopy(r) for s in case['steps'][:step] for r in s['sources']]]


class CaptureOnly(BaseException):pass


async def native_first_request(client,messages,sources):
    """Capture the actual generator's first wire preparation, with no transport."""
    class Capture:
        context_limit=1048576
        last_usage=None
        def for_handoff(self,*,max_tokens):self.limit=max_tokens;return self
        def context_input(self,*args,**kwargs):return client.context_input(*args,**kwargs)
        def context_token_measure(self,value):return client.context_token_measure(value)
        async def stream(self,request,tools,abort):
            self.body=client._build_body(request,tools,stream=False)
            self.body.update(max_tokens=self.limit,temperature=0)
            raise CaptureOnly()
            if False:yield ModelChunk(kind='text_delta')
    model=Capture()
    try:
        await generate(model,messages,sources,TodoWriteTool().schema(),AbortController(),
            account=lambda usage:None,scope_protocol=True)
    except CaptureOnly:pass
    return model.body


def prepare():
    assert not (ROOT/'preflight-manifest.json').exists();ROOT.mkdir(exist_ok=True)
    client=DeepSeekModelClient(api_key='not-sent',model='deepseek-flash',thinking='disabled')
    prompt=(CODEX/'prompt.md').read_text(encoding='utf-8');prefix=(CODEX/'summary_prefix.md').read_bytes()
    cases=scenarios();_atomic_write(ROOT/'scenario-private.json',json.dumps(cases,ensure_ascii=False,indent=2),durable=True)
    records=[]
    for case in cases:
        name=case['case'];folder=ROOT/name;folder.mkdir();rows=visible_sources(case,1)
        raw=('\n'.join(canonical(r) for r in rows)+'\n').encode('utf-8');archive=folder/('sources-'+sha(raw)+'.jsonl');archive.write_bytes(raw)
        cold=ReceiptSources(archive,sha(raw));sink=ArtifactSink(folder/'artifacts')
        info={'source_records':rows,'archive':cold.locator(),'artifact_root':str(sink.root)}
        visible=[{'role':'user','content':canonical(info)}]
        actor=client._build_body([*visible,{'role':'user','content':case['steps'][0]['request']}],cold.schemas()+[sink.schema()],stream=False)
        actor.update(max_tokens=4096,temperature=0)
        d=asyncio.run(native_first_request(client,visible,rows))
        a1=client._build_body([*visible,{'role':'user','content':prompt}],[],stream=False);a1.update(max_tokens=d['max_tokens'],temperature=0)
        files={}
        for kind,body in [('uncompressed-actor',actor),('D-handoff-review',d),('A1-handoff-review',a1)]:
            path=folder/(kind+'-input.json');_atomic_write(path,json.dumps(body,ensure_ascii=False,indent=2),durable=True)
            files[kind]={'path':str(path),'sha256':sha(path.read_bytes())}
        records.append({'case':name,'initial_sources':len(rows),'source_sha256':sha(raw),'archive':str(archive),'inputs':files})
    plan={'cases':records,'model':'deepseek-flash','thinking':'disabled','paid_run_allowed':False,'http_retries':0,
        'generation_materials_only':True,'generation_output_review_limit':'Native D reservation; A1 matched at initial capture','actor_output_limit':4096,
        'future_events_private':True,'native_D_runtime_not_replaced':True,
        'scenario_steps':10,'compaction_generations_executed':0,'api_calls':0,
        'A1_prompt_sha256':sha(prompt.encode('utf-8')),'A1_prefix_sha256':sha(prefix),
        'nonclaim':'Synthetic task protocol prepared only. No model/task/compaction/production acceptance.',
        'code_sha256':sha(Path(__file__).read_bytes())}
    _atomic_write(ROOT/'preflight-manifest.json',json.dumps(plan,ensure_ascii=False,indent=2),durable=True)
    return plan


if __name__=='__main__':
    plan=prepare();print(canonical({'cases':len(plan['cases']),'steps_per_case':10,'inputs':6,'api_calls':0}))
