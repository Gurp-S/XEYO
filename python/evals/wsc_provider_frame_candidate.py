"""Metered evaluation transport with exact completed provider-frame replay.

Only this adapter's own assistant tool frames are recoverable. No placeholder
reasoning, prompt changes, candidate repair, retries, or production imports.
"""
from copy import deepcopy
import json

from model._openai_common import consume_sse_line_with_usage, finish_tool_bufs
from model.context_input import from_body
from model.stream_end import validate_stream_end


def decode_reply(reply):
    delta = deepcopy(reply)
    for index, call in enumerate(delta.get('tool_calls') or []):
        call['index'] = index
    buffers = {}
    _, chunks = consume_sse_line_with_usage(
        'data:' + json.dumps({'choices': [{'delta': delta}]}), buffers)
    chunks.extend(finish_tool_bufs(buffers))
    # Early JSON closure and end-of-frame malformed arguments may otherwise
    # reorder calls. Match original provider order, independently of validity.
    tools = {chunk.tool_use.id: chunk for chunk in chunks if chunk.kind == 'tool_use'}
    ordered = [chunk for chunk in chunks if chunk.kind != 'tool_use']
    ordered.extend(tools[call['id']] for call in reply.get('tool_calls') or [])
    return ordered


def identity(calls):
    return tuple(call['id'] for call in calls)


def parsed_tools(chunks):
    return [{'id': c.tool_use.id, 'name': c.tool_use.name, 'input': c.tool_use.input}
            for c in chunks if c.kind == 'tool_use']


class ProviderFrameModel:
    context_limit = 1048576

    def __init__(self, calls, client, label, limit=4096, *, state=None):
        self.calls, self.client, self.label, self.limit = calls, client, label, limit
        self.state = {'frames': {}, 'counter': 0, 'usage': None} if state is None else state

    @property
    def last_usage(self):
        return self.state['usage']

    @last_usage.setter
    def last_usage(self, value):
        self.state['usage'] = value

    def for_handoff(self, *, max_tokens):
        return ProviderFrameModel(self.calls, self.client, self.label, max_tokens, state=self.state)

    def body(self, messages, tools):
        body = self.client._build_body(messages, tools, stream=False)
        for row in body['messages']:
            calls = row.get('tool_calls') if row.get('role') == 'assistant' else None
            key = identity(calls) if calls else ()
            saved = self.state['frames'].get(key)
            if saved is None:
                continue
            actual = [{'id': call['id'], 'name': call['function']['name'],
                       'input': json.loads(call['function']['arguments'])} for call in calls]
            if actual != saved['parsed']:
                raise ValueError('handoff_provider_frame_arguments_changed')
            for field in ('content', 'reasoning_content'):
                if row.get(field) and row[field] != saved['raw'].get(field):
                    raise ValueError('handoff_provider_frame_content_changed')
            row.clear()
            row.update(deepcopy(saved['raw']))
        body.update(max_tokens=self.limit, temperature=0)
        return body

    def context_input(self, messages, tools):
        return from_body(self.body(messages, tools))

    def context_token_measure(self, source):
        return self.client.context_token_measure(source)

    async def stream(self, messages, tools, abort):
        if abort.aborted:
            raise ValueError('handoff_cancelled')
        body = self.body(messages, tools)
        self.state['counter'] += 1
        response = await self.calls.call(body, self.label + f'-provider-{self.state["counter"]}')
        self.last_usage = response.get('usage')
        choice = response['choices'][0]
        reply = deepcopy(choice['message'])
        validate_stream_end({'finish_reason': choice.get('finish_reason'), 'has_output': True})
        if abort.aborted:
            raise ValueError('handoff_cancelled')
        chunks = decode_reply(reply)
        calls = reply.get('tool_calls') or []
        key = identity(calls)
        if calls and (len(set(key)) != len(key) or key in self.state['frames']):
            raise ValueError('handoff_provider_frame_identity_conflict')
        for chunk in chunks:
            yield chunk
        if calls and not abort.aborted:
            self.state['frames'][key] = {'raw': reply, 'parsed': parsed_tools(chunks)}
