"""Failure/restart actor controls, no HTTP and no semantic gold in requests."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

from evals.wsc_artifact_bytes_candidate import ExactArtifactSink
from evals.wsc_provider_frame_candidate import ProviderFrameModel
from evals.wsc_task_actor_candidate import new_state, run, restore, grade
from evals.wsc_task_uncompressed_trial import actor as old_actor
from model.deepseek import DeepSeekModelClient

ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-actor-contracts-278')
CLIENT = DeepSeekModelClient(api_key='not-sent', model='deepseek-flash', thinking='enabled')


def response(uses=None):
    message = {'role': 'assistant', 'content': 'fixture complete', 'reasoning_content': 'fixture thought'}
    if uses:
        message['tool_calls'] = [{'id': uid, 'type': 'function', 'function': {'name': 'ArtifactWrite',
                    'arguments': json.dumps({'file_path': path, 'content': content})}} for uid, path, content in uses]
    return {'choices': [{'finish_reason': 'tool_calls' if uses else 'stop', 'message': message}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 2}}


class Calls:
    def __init__(self, values): self.values, self.requests = values, []
    async def call(self, body, label):
        self.requests.append(deepcopy(body)); value = self.values.pop(0)
        if isinstance(value, BaseException): raise value
        return value


class Cold:
    def call(self, name, args): raise ValueError('fixture_unknown_tool')


async def main():
    ROOT.mkdir(exist_ok=False); checks = []
    def check(name, value): checks.append({'name': name, 'passed': bool(value)})
    first = response([('write', 'result.json', '{"value":7}\n')])
    messages = [{'role': 'user', 'content': 'fixture task'}]
    tools = [ExactArtifactSink.schema()]
    original = ExactArtifactSink(ROOT / 'old')
    try:
        await old_actor(ProviderFrameModel(Calls([first, RuntimeError('fixture network')]), CLIENT, 'old'),
                        messages, tools, original, Cold())
        failed = False
    except RuntimeError: failed = True
    check('old_post_write_model_error_reproduced', failed and len(original.attempts) == 1)
    sink = ExactArtifactSink(ROOT / 'new'); state = new_state(messages); snapshots = []
    model = ProviderFrameModel(Calls([first, RuntimeError('fixture network')]), CLIENT, 'new')
    try:
        await run(model, state, tools, sink, Cold(), additional_requests=3, checkpoint=snapshots.append)
        failed = False
    except RuntimeError: failed = True
    saved = json.loads(json.dumps(snapshots[-1]))
    check('completed_receipt_survives_later_model_error', failed and len(saved['activity']) == 1
          and saved['phase'] == 'model_failed' and saved['pending_messages'][-1]['role'] == 'tool')
    resumed_sink = ExactArtifactSink(sink.root)
    resumed = ProviderFrameModel(Calls([response()]), CLIENT, 'resumed')
    restore(resumed, saved, resumed_sink)
    await run(resumed, saved, tools, resumed_sink, Cold(), additional_requests=1, checkpoint=snapshots.append)
    check('restart_continues_without_second_write', saved['completed'] and len(resumed_sink.attempts) == 1
          and grade(resumed_sink, {'value': 7})['task_success'])
    wire = resumed.calls.requests[0]
    check('restart_replays_original_provider_frame', next(r for r in wire['messages'] if r['role'] == 'assistant') == first['choices'][0]['message'])
    check('caller_messages_immutable', messages == [{'role': 'user', 'content': 'fixture task'}])
    model = ProviderFrameModel(Calls([first]), CLIENT, 'save_failure')
    state = new_state(messages); untouched = ExactArtifactSink(ROOT / 'save_failure')
    def failed_save(value): raise OSError('fixture checkpoint save failure')
    try:
        await run(model, state, tools, untouched, Cold(), additional_requests=1, checkpoint=failed_save)
        failed = False
    except OSError: failed = True
    check('checkpoint_failure_precedes_model_and_mutation', failed and not model.calls.requests and not untouched.attempts)
    class UnknownSink(ExactArtifactSink):
        def call(self, args): super().call(args); raise AssertionError('fixture post-write failure')
    unknown = UnknownSink(ROOT / 'unknown'); state = new_state(messages); snapshots = []
    model = ProviderFrameModel(Calls([first]), CLIENT, 'unknown')
    try:
        await run(model, state, tools, unknown, Cold(), additional_requests=1, checkpoint=snapshots.append)
        failed = False
    except AssertionError: failed = True
    check('unknown_tool_outcome_preserved_without_success_receipt', failed and snapshots[-1]['phase'] == 'tool_outcome_unknown'
          and snapshots[-1]['pending_tool']['call_id'] == 'write' and not snapshots[-1]['activity'])
    try: restore(ProviderFrameModel(Calls([]), CLIENT, 'unknown_restart'), snapshots[-1], unknown); denied = False
    except ValueError: denied = True
    check('unknown_mutation_not_automatically_replayed', denied and len(unknown.attempts) == 1)
    batch = response([('first', 'one.json', '{}'), ('second', 'result.json', '{"value":7}')])
    snapshots = []; sink = ExactArtifactSink(ROOT / 'batch'); state = new_state(messages)
    await run(ProviderFrameModel(Calls([batch]), CLIENT, 'batch'), state, tools, sink, Cold(),
              additional_requests=1, checkpoint=snapshots.append)
    middle = [s for s in snapshots if len(s['activity']) == 1]
    check('mid_batch_checkpoint_not_ready_for_model_call', middle and all(s['phase'] == 'tool_pending' for s in middle))
    for name, content, wanted in [('numeric', '{"value":7.0}', True), ('bool', '{"value":true}', False),
                                  ('text', '{"value":"7"}', False), ('wrong', '{"value":8.0}', False)]:
        sink = ExactArtifactSink(ROOT / name); sink.call({'file_path': 'result.json', 'content': content})
        g = grade(sink, {'value': 7})
        check(name + '_grade_separates_representation', g['task_success'] == wanted and not g['strict_format']['success'])
    report = {'api_calls': 0, 'checks': checks, 'passed': sum(c['passed'] for c in checks), 'total': len(checks)}
    (ROOT / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    for path in (Path(__file__), Path('python/evals/wsc_task_actor_candidate.py')):
        (ROOT / path.name).write_bytes(path.read_bytes())
    print(json.dumps({k: v for k, v in report.items() if k != 'checks'}))
    assert report['passed'] == report['total']


if __name__ == '__main__': asyncio.run(main())
