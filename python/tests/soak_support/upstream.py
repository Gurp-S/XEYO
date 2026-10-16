"""Concurrent scripted OpenAI endpoint driven by request history, not global order."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import time

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import uvicorn

app = FastAPI()
directory = Path('.')


def text(message):
    content = message.get('content', '')
    return content if isinstance(content, str) else ' '.join(str(b.get('text', '')) for b in content if isinstance(b, dict))


def call(name, args, ident):
    return {'index': 0, 'id': ident, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


@app.get('/health')
def health():
    return {'ok': True, 'pid': os.getpid()}


@app.post('/v1/chat/completions')
async def completion(request: Request):
    body = await request.json()
    messages = body.get('messages', [])
    names = {t.get('function', {}).get('name') for t in body.get('tools', [])}
    joined = '\n'.join(text(m) for m in messages)
    workers = re.findall(r'XEYO_WORKER ([a-zA-Z0-9_-]+) (\d+) ([\d.]+)', joined)
    parents = [(n, re.search(r'XEYO_SOAK ([a-zA-Z0-9_-]+) (\d+) ([\d.]+)', text(m))) for n, m in enumerate(messages) if m.get('role') == 'user']
    parents = [(n, match) for n, match in parents if match]
    publishes = [(n, re.search(r'XEYO_PUBLISH ([\w-]+) ([\w-]+) ([\w-]+)', text(m))) for n, m in enumerate(messages) if m.get('role') == 'user']
    publishes = [(n, m) for n, m in publishes if m]
    response, delay = {}, 0
    key = 'auxiliary'
    if 'Agent' not in names and workers and names:
        token, slot, seconds = workers[-1]
        key = f'{token}/{slot}'
        ids = {m.get('tool_call_id') for m in messages if m.get('role') == 'tool'}
        if f'read-{token}-{slot}' not in ids:
            delay = float(seconds)
            response = {'calls': [call('Read', {'file_path': 'f.txt'}, f'read-{token}-{slot}')]}
        elif token.startswith('write') and f'write-{token}-{slot}' not in ids:
            response = {'calls': [call('Write', {'file_path': 'f.txt', 'content': f'private {token}/{slot}\n'}, f'write-{token}-{slot}')]}
        elif f'up-{token}-{slot}' not in ids:
            response = {'calls': [call('agent_send', {'agent_id': 'parent', 'message_id': f'up-{token}-{slot}', 'text': f'UP-{token}-{slot}'}, f'up-{token}-{slot}')]}
        else:
            response = {'text': f'WORKER-DONE-{token}-{slot} ' + 'abcdefghijklmnop ' * 5}
    elif publishes and names and (not parents or publishes[-1][0] > parents[-1][0]):
        offset, match = publishes[-1]
        token, aid, attempt = match.groups()
        ids = {m.get('tool_call_id') for m in messages[offset:] if m.get('role') == 'tool'}
        response = {'text': f'PUBLISH-DONE-{token}'} if f'publish-{token}' in ids else {
            'calls': [call('agent_apply', {'agent_id': aid, 'attempt_id': attempt}, f'publish-{token}')]}
        key = token
    elif parents and names:
        offset, match = parents[-1]
        token, count, seconds = match.groups()
        key = token
        current = messages[offset:]
        ids = {m.get('tool_call_id') for m in current if m.get('role') == 'tool'}
        handles = []
        for m in current:
            if m.get('role') == 'tool' and str(m.get('tool_call_id', '')).startswith(f'spawn-{token}-'):
                try:
                    raw = text(m)
                    receipt, _ = json.JSONDecoder().raw_decode(raw[raw.index('{"agent_id"'):])
                    if receipt.get('agent_id') and receipt.get('attempt_id'):
                        handles.append(receipt)
                except ValueError:
                    pass
        if not any(str(i).startswith(f'spawn-{token}-') for i in ids):
            response = {'calls': [call('Agent', {'task_id': f'slot{n}', 'desc': f'XEYO_WORKER {token} {n} {seconds}', 'background': True,
                **({'scope': ['f.txt']} if token.startswith('write') else {})}, f'spawn-{token}-{n}') for n in range(int(count))]}
        elif handles and not any(str(i).startswith(f'wait-{token}-') for i in ids):
            response = {'calls': [call('agent_control', {'action': 'wait', 'agent_id': h['agent_id'], 'attempt_id': h['attempt_id'], 'timeout_s': 60}, f'wait-{token}-{n}') for n, h in enumerate(handles)]}
        else:
            response = {'text': f'PARENT-DONE-{token} ' + 'abcdefghijklmnop ' * 12}
    else:
        response = {'text': 'test auxiliary'}
    record = {'time': time.time(), 'key': key, 'tools': sorted(n for n in names if n),
              'calls': [c['function']['name'] for c in response.get('calls', [])],
              'mail': sorted(set(re.findall(r'(?:MAIL|UP)-[a-zA-Z0-9_-]+', joined)))}
    with (directory / 'model.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record) + '\n')
    async def frames():
        def frame(delta, finish=None):
            return 'data: ' + json.dumps({'id': 'local-fixture', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}) + '\n\n'
        yield frame({'role': 'assistant'})
        if delay:
            await asyncio.sleep(delay)
        for n, item in enumerate(response.get('calls', [])):
            yield frame({'tool_calls': [{**item, 'index': n}]})
        content = response.get('text', '')
        for n in range(0, len(content), 8):
            yield frame({'content': content[n:n+8]})
            await asyncio.sleep(.025)
        yield frame({}, 'tool_calls' if response.get('calls') else 'stop')
        yield 'data: [DONE]\n\n'
    return StreamingResponse(frames(), media_type='text/event-stream')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory
    directory.mkdir(parents=True, exist_ok=True)
    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')
