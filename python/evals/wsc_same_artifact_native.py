"""Offline same-artifact projection control on the two archived real sources.

No model calls. Thin/native differ only in installed head; A1 retained users
is a separate policy baseline. Behavioral scores remain unknown until run.
"""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path

from engine.abort import AbortController
from evals import wsc_semantic_format_pilot as p
from evals.wsc_elimination_chain import retain_users
from evals.wsc_production_continuation import ProductionTask, PublishedRead
from evals.wsc_semantic_projection_pair import CommonPublishedRead
from evals.wsc_unfolded_source_ab import environment
from memory import wsc_semantic_compaction as semantic
from memory.token import token_len
from memory.wsc_semantic_originals import from_store
from model.chunks import ModelChunk
from msgtypes.message import ToolUse
from prompt.assembler import PromptAssembler

ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-same-artifact-native-327')


class Fixed:
    context_limit = 1048576
    last_usage = None

    def __init__(self, text): self.text = text
    def for_handoff(self, max_tokens): return self
    async def stream(self, messages, tools, abort):
        yield ModelChunk(kind='text_delta', text=self.text)


async def main():
    assert not ROOT.exists(), 'immutable run directory'
    ROOT.mkdir()
    old = p.load(ROOT.parent/'wsc-glm-real-sources-324/run-report.json')
    plan = {'scope': __doc__, 'paid_calls': 0, 'cases': [],
            'token_basis': 'ceil(UTF-8 bytes / 4), not provider tokenizer or billing',
            'consumer_requests_per_arm': 6, 'output_limit': 4096,
            'http_retries': 0, 'behavior_status': 'pending_provider_availability',
            'reviews': ['Identical saved summary, exact tail, tools and retrieval capability for thin/native.',
                        'Native prepare/publish/restart and actual Read; original envelopes remain distinct.',
                        'A1 retained-user policy is separately labeled; offline invariants are not semantic scores.']}
    with environment(ROOT):
        os.environ.update(XEYO_WSC='1', XEYO_WSC_HEAD_STORE='1', XEYO_WSC_MEDIA_ARCHIVE='1')
        for name in p.e.CASES:
            case = p.load(ROOT.parent/'wsc-semantic-format-307'/name/'case-private.json')
            saved = next(row for row in old['calls'] if row['label'] == name+'-A1-gen-provider-1')
            reply = saved['response']['choices'][0]
            assert reply['finish_reason'] == 'stop'
            text = reply['message']['content']
            task = ProductionTask(ROOT/name, case['rows'], session='same-artifact-327-'+name)
            task.persist()
            candidate = await semantic.prepare(model=Fixed(text), messages=case['common_messages'],
                source=task.source, working=task.working, abort=AbortController(), account=lambda _:None,
                persist=task.persist, cwd=task.root, original_source=lambda:from_store(task.store))
            native = semantic.publish(candidate, task.source(), task.working, cwd=task.root)
            assert native == task.project() == task.restart().project()
            from memory.wsc_head_store import path_for
            head = p.load(path_for(task.working.session_id))
            result = await PublishedRead(task, head).execute(ToolUse('native-read', 'Read',
                {'file_path': head['view_path'], 'offset': 1, 'limit': 1}), AbortController())
            assert not result.is_error
            paths = [case['archive'], *head['publication']['objects']]
            reader = CommonPublishedRead(paths)
            metadata = {'role':'user','content':p.e.canonical({'exact_evidence':{
                'archive':case['archive'],'source_sha256':case['raw_sha256'],
                'records':len(case['rows']),'archive_line_base':1}})}
            thin = deepcopy(native); thin[0] = {'role':'assistant','content':text}
            baseline = retain_users([], task.source(), text)
            projections = {'thin_same_artifact':thin,'native_same_artifact':native,'A1_user_policy':baseline}
            record = {'case':name, 'summary_sha256':p.sha(text), 'generation_model':'glm-5.3-flash',
                'source_call':saved['label'], 'source_sha256':case['raw_sha256'],
                'source_rows':len(task.source()),'restart_equal':True,'native_Read':True,
                'same_tail':thin[1:]==native[1:],'paths':paths,'arms':{}}
            for arm, hot in projections.items():
                messages = PromptAssembler().build(case['template']['system']['content'],
                    [*hot, metadata, case['template']['query']])
                model = p.ProviderFrameModel(None, p.e.CLIENT, name+'-'+arm, 4096)
                body = model.body(messages, reader.schemas())
                from evals.wsc_semantic_production_trial import validate_wire
                # Native tokenizer can be unavailable. This local preparation
                # uses a conservative estimate without changing production.
                measure = p.e.CLIENT.context_token_measure
                try:
                    p.e.CLIENT.context_token_measure = lambda source:(len(p.e.canonical(source).encode())+8192,'utf8_upper')
                    validate_wire(body)
                finally:
                    p.e.CLIENT.context_token_measure = measure
                file = ROOT/name/(arm+'-input.json'); p.e.write(file,body)
                p.e.write(ROOT/name/(arm+'-messages.json'),messages)
                record['arms'][arm] = {'input_file':str(file),'request_sha256':p.sha(file.read_bytes()),
                    'head_tokens_estimate':token_len(hot[0]['content']) if arm!='A1_user_policy' else token_len(text),
                    'hot_tokens_estimate':token_len(p.e.canonical(hot)),
                    'request_tokens_estimate':token_len(p.e.canonical(body)),
                    'task_success':None,'effective_recovery':None}
            plan['cases'].append(record)
    p.e.write(ROOT/'preflight-manifest.json',plan)
    print(json.dumps({'cases':len(plan['cases']),'requests_prepared':6,'paid_calls':0,
                      'result':str(ROOT/'preflight-manifest.json')}))


if __name__ == '__main__': asyncio.run(main())
