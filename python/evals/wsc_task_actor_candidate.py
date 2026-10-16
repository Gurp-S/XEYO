"""Eval-only event-boundary actor persistence and strict/semantic task grading."""
from copy import deepcopy
import json
import math

from engine.abort import AbortController
from evals.wsc_provider_frame_candidate import decode_reply, identity, parsed_tools
from evals.wsc_task_acceptance_protocol import judge
from msgtypes.message import assistant_text_message


def new_state(messages):
    return {'pending_messages': deepcopy(messages), 'activity': [], 'completed': False,
            'phase': 'ready', 'requests_attempted': 0, 'pending_tool': None,
            'remaining_tool_ids': [], 'write_attempts': [], 'provider_frames': [], 'provider_counter': 0}


def adopt_paid_frames(model, calls):
    """Calls must be a caller-verified branch of immutable paid receipts."""
    for call in calls:
        choice = call['response']['choices'][0]
        if choice['finish_reason'] not in ('stop', 'tool_calls'):
            raise ValueError('actor_paid_frame_incomplete')
        raw = deepcopy(choice['message'])
        uses = raw.get('tool_calls') or []
        key = identity(uses)
        if uses:
            entry = {'raw': raw, 'parsed': parsed_tools(decode_reply(raw))}
            if key in model.state['frames'] and model.state['frames'][key] != entry:
                raise ValueError('actor_paid_frame_identity_conflict')
            model.state['frames'][key] = entry
    model.state['counter'] = len(calls)


def restore(model, state, sink):
    if state['pending_tool'] is not None or state.get('remaining_tool_ids') or state['phase'] in ('tool_pending', 'tool_outcome_unknown'):
        raise ValueError('actor_tool_outcome_unknown')
    if state.get('completed'):
        raise ValueError('actor_already_completed')
    for frame in state.get('provider_frames', []):
        raw = frame['raw']
        key = identity(raw.get('tool_calls') or [])
        if list(key) != frame['call_ids'] or frame['parsed'] != parsed_tools(decode_reply(raw)):
            raise ValueError('actor_provider_checkpoint_invalid')
        entry = {'raw': deepcopy(raw), 'parsed': deepcopy(frame['parsed'])}
        if key in model.state['frames'] and model.state['frames'][key] != entry:
            raise ValueError('actor_provider_checkpoint_conflict')
        model.state['frames'][key] = entry
    model.state['counter'] = state.get('provider_counter', 0)
    sink.attempts = deepcopy(state.get('write_attempts', []))


async def run(model, state, tools, sink, cold, *, additional_requests, checkpoint):
    if state['pending_tool'] is not None or state.get('remaining_tool_ids') or state['phase'] in ('tool_pending', 'tool_outcome_unknown'):
        raise ValueError('actor_tool_outcome_unknown')
    if state['completed']:
        raise ValueError('actor_already_completed')

    def publish():
        state['write_attempts'] = deepcopy(sink.attempts)
        state['provider_frames'] = [{'call_ids': list(key), **deepcopy(value)}
                                    for key, value in model.state['frames'].items()]
        state['provider_counter'] = model.state['counter']
        checkpoint(deepcopy(state))

    for _ in range(additional_requests):
        state.update(phase='model_pending', requests_attempted=state['requests_attempted'] + 1)
        publish()
        try:
            chunks = [c async for c in model.stream(state['pending_messages'], tools, AbortController())]
        except BaseException:
            state['phase'] = 'model_failed'
            publish()
            raise
        uses = [c.tool_use for c in chunks if c.kind == 'tool_use']
        text = ''.join(c.text for c in chunks if c.kind == 'text_delta')
        thought = ''.join(c.text for c in chunks if c.kind == 'reasoning_delta')
        message = assistant_text_message(text, uses, reasoning=thought)
        state['pending_messages'].append({'role': message.role, 'content': message.content})
        if not uses:
            state.update(completed=True, answer=text, phase='completed')
            publish()
            return
        state['phase'] = 'tool_pending'
        state['remaining_tool_ids'] = [use.id for use in uses]
        publish()
        for use in uses:
            state['pending_tool'] = {'call_id': use.id, 'tool': use.name, 'input': deepcopy(use.input)}
            publish()
            error = False
            try:
                from evals.wsc_native_actor_result import execute, legacy_message
                value, error, receipt = await execute(use, sink, cold)
            except (ValueError, KeyError, TypeError, OSError) as exc:
                value, error = {'error': str(exc)}, True
                receipt = legacy_message(use, value, error)
            except BaseException:
                state['phase'] = 'tool_outcome_unknown'
                publish()
                raise
            state['activity'].append({'call_id': use.id, 'tool': use.name, 'input': deepcopy(use.input),
                                      'result': deepcopy(value), 'is_error': error})
            state['pending_messages'].append(receipt)
            state['remaining_tool_ids'].pop(0)
            state.update(pending_tool=None, phase='tool_pending' if state['remaining_tool_ids'] else 'ready')
            publish()
    state['phase'] = 'request_cap'
    publish()


def grade(sink, expected, before_hash=None):
    strict = judge(sink, expected, before_hash)
    result = {'strict_format': strict, 'task_success': strict['success']}
    if expected is None or strict['success']:
        return result
    path = sink.root / 'result.json'
    if not path.is_file():
        return result
    try:
        actual = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError):
        return result
    def equal(value, wanted):
        if type(wanted) in (int, float):
            return type(value) in (int, float) and value == wanted and (type(value) is int or math.isfinite(value))
        return type(value) is type(wanted) and value == wanted
    if isinstance(actual, dict) and set(actual) == set(expected) and all(equal(actual[k], v) for k, v in expected.items()):
        numeric_equivalent = {k: v for k, v in expected.items()}
        numeric_equivalent.update({k: actual[k] for k, v in expected.items() if type(v) in (int, float)})
        result['task_success'] = judge(sink, numeric_equivalent, before_hash)['success']
        result['numeric_representation_only'] = result['task_success']
    return result
