"""Zero-HTTP exact provider-shaped frame contracts and actual native A/B."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from engine.abort import AbortController
from evals.wsc_elimination_faithful import MeteredNative
from evals.wsc_provider_frame_candidate import ProviderFrameModel, decode_reply
from memory.wsc_handoff_generation import generate
from model.deepseek import DeepSeekModelClient
from msgtypes.message import assistant_text_message
from tests.wsc.test_handoff_fact_disposition import prepared
from tools.todo_write_tool.todo_write_tool import TodoWriteTool

ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-provider-frame-contracts-273')
CLIENT = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='enabled')


def reply(tool='HandoffSource', args=' { "message_id" : "permit", "offset" : 0, "limit" : 128 } ', call='first', reason='tool_calls'):
    return {'choices': [{'finish_reason': reason, 'message': {'role': 'assistant', 'content': 'original body 中文',
            'reasoning_content': 'original thought\n中文  ', 'tool_calls': [{'id': call, 'type': 'function',
            'function': {'name': tool, 'arguments': args}}]}}], 'usage': {'prompt_tokens': 13, 'completion_tokens': 17}}


class Calls:
    def __init__(self, responses):
        self.responses = deepcopy(responses)
        self.requests = []

    async def call(self, body, label):
        self.requests.append(deepcopy(body))
        return self.responses.pop(0)


async def consume(model, messages=None):
    chunks = [chunk async for chunk in model.stream(messages or [{'role': 'user', 'content': 'fixture'}], [], AbortController())]
    return chunks


async def main():
    ROOT.mkdir(exist_ok=False)
    checks, proof = [], []

    def check(name, value):
        checks.append({'name': name, 'passed': bool(value)})

    for rejection in (False, True):
        sources, raw = prepared()
        first = reply('TodoWrite' if rejection else 'HandoffSource', '{malformed' if rejection else reply()['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
        second = reply('TodoWrite', json.dumps(raw, ensure_ascii=False), 'valid')
        old_calls, new_calls = Calls([first, second]), Calls([first, second])
        accounts = []
        for model in (MeteredNative(old_calls, 'baseline'), ProviderFrameModel(new_calls, CLIENT, 'candidate')):
            result = await generate(model, [{'role': 'user', 'content': 'fixture'}], sources, TodoWriteTool().schema(),
                                    AbortController(), account=lambda u: accounts.append(deepcopy(u)), scope_protocol=True)
            check(('rejection' if rejection else 'read') + '_' + type(model).__name__ + '_native_accepts', result.id == 'valid')
        old = next(row for row in old_calls.requests[1]['messages'] if row['role'] == 'assistant')
        new = next(row for row in new_calls.requests[1]['messages'] if row['role'] == 'assistant')
        check(('rejection' if rejection else 'read') + '_exact_original_wire_frame',
              new == first['choices'][0]['message'] and 'reasoning_content' not in old and old['content'] == '')
        check(('rejection' if rejection else 'read') + '_usage_observed', accounts == [first['usage'], second['usage']] * 2)
        proof.append({'path': 'rejection' if rejection else 'read', 'baseline_next': old, 'candidate_next': new,
                      'original': first['choices'][0]['message'], 'candidate_request': new_calls.requests[1]})
    multi = reply(args='{malformed')
    multi['choices'][0]['message']['tool_calls'].append({'id': 'second', 'type': 'function', 'function': {'name': 'HandoffCatalog', 'arguments': '{"offset":0}'}})
    calls = Calls([multi])
    model = ProviderFrameModel(calls, CLIENT, 'multi')
    chunks = await consume(model)
    uses = [c.tool_use for c in chunks if c.kind == 'tool_use']
    check('malformed_then_valid_tool_order_preserved', [u.id for u in uses] == ['first', 'second'] and uses[0].input == {'_raw': '{malformed'})
    row = assistant_text_message('', uses)
    tools = [{'name': name, 'input_schema': {'type': 'object'}} for name in ('HandoffSource', 'HandoffCatalog')]
    wire = model.body([{'role': 'assistant', 'content': row.content}], tools)['messages'][0]
    check('multi_tool_original_wire_frame_preserved', wire == multi['choices'][0]['message'])
    check('reservation_child_keeps_mode_and_shared_frames', model.for_handoff(max_tokens=888).state is model.state
          and model.for_handoff(max_tokens=888).body([], [])['max_tokens'] == 888
          and model.for_handoff(max_tokens=888).body([], [])['thinking'] == {'type': 'enabled'})
    changed = deepcopy(row.content)
    changed[0]['input'] = {'message_id': 'changed'}
    try:
        model.body([{'role': 'assistant', 'content': changed}], tools)
        mismatch = False
    except ValueError:
        mismatch = True
    check('same_id_changed_arguments_rejected', mismatch)
    truncated = reply(reason='length')
    model = ProviderFrameModel(Calls([truncated]), CLIENT, 'truncated')
    try:
        await consume(model)
        denied = False
    except Exception:
        denied = True
    check('truncation_keeps_usage_without_complete_frame', denied and model.last_usage == truncated['usage'] and not model.state['frames'])
    model = ProviderFrameModel(Calls([reply()]), CLIENT, 'partial')
    stream = model.stream([{'role': 'user', 'content': 'fixture'}], [], AbortController())
    await anext(stream)
    await stream.aclose()
    check('consumer_interruption_does_not_publish_frame', not model.state['frames'])
    scalar = reply(args='17')
    decoded = decode_reply(scalar['choices'][0]['message'])
    check('shared_parser_non_object_arguments_preserved', next(c.tool_use for c in decoded if c.kind == 'tool_use').input == {'value': 17})
    aborted = AbortController()
    aborted.abort()
    calls = Calls([reply()])
    model = ProviderFrameModel(calls, CLIENT, 'aborted')
    try:
        await anext(model.stream([], [], aborted))
        denied = False
    except ValueError:
        denied = True
    check('pre_aborted_request_not_sent', denied and not calls.requests)
    report = {'api_calls': 0, 'checks': checks, 'passed': sum(c['passed'] for c in checks), 'total': len(checks),
              'native_AB': proof, 'nonclaim': 'Provider-shaped fixtures; no actual vendor semantic quality or task success.'}
    (ROOT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    identities = []
    for path in (Path(__file__), Path('python/evals/wsc_provider_frame_candidate.py')):
        raw = path.read_bytes()
        (ROOT / path.name).write_bytes(raw)
        identities.append({'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest()})
    (ROOT / 'source-identities.json').write_text(json.dumps(identities, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in {'checks', 'native_AB'}}))
    assert report['passed'] == report['total']


if __name__ == '__main__':
    asyncio.run(main())
