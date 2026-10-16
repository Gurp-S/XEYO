"""Actual HTTP parent cancellation and worktree publication acceptance probes."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time
import httpx
from tests.soak_support.lab import Lab
from tests.soak_support.soak import Load


async def run(lab):
    load = Load(lab, 0)
    async with httpx.AsyncClient(base_url=lab.base, timeout=120) as client:
        load.client = client
        async def begin(n):
            sid = (await load.request('POST', '/v1/sessions', json={'workspace': str(lab.workspace)}))['session_id']
            token = f'cancel{n}'
            task = asyncio.create_task(load.stream(sid, token, 20))
            cards = await load.until(lambda: load.cards(sid, token), lambda a: len(a) == 4)
            turn = await load.request('GET', f'/v1/sessions/{sid}/task')
            return sid, turn['turn_id'], cards, task
        entries = await asyncio.gather(*(begin(n) for n in range(8)))
        started = time.monotonic()
        await asyncio.gather(*(load.request('POST', '/v1/interrupt', json={'session_id': sid, 'expected_turn_id': tid}) for sid, tid, _, _ in entries))
        await asyncio.gather(*(e[3] for e in entries), return_exceptions=True)
        for sid, _, cards, _ in entries:
            status = await load.request('GET', f'/v1/sessions/{sid}/task')
            assert not status['busy'] and status['status'] == 'stopped', status
            current = (await load.request('GET', f'/v1/sessions/{sid}/agents'))['agents']
            assert all(a['runtimeState'] == 'cancelled' for a in current), current
        stop_seconds = round(time.monotonic()-started, 3)
        assert stop_seconds < 8, stop_seconds
        assert (await client.get('/health')).status_code == 200
        index = lab.workspace/'.git/index'
        before = hashlib.sha256(index.read_bytes()).hexdigest()
        async def write(n):
            sid = (await load.request('POST', '/v1/sessions', json={'workspace': str(lab.workspace)}))['session_id']
            token = f'write{n}'
            await load.stream(sid, token, 1)
            cards = await load.cards(sid, token)
            assert len(cards) == 4 and all(a['runtimeState'] == 'completed' for a in cards), cards
            for a in cards:
                assert (Path(a['isolation']['worktree'])/'f.txt').read_text() == f'private {token}/{a["taskId"][4:]}\n'
            return sid, cards
        writes = await asyncio.gather(*(write(n) for n in range(3)))
        paths = [a['isolation']['worktree'] for _, cards in writes for a in cards]
        assert len(set(paths)) == 12
        assert (lab.workspace/'f.txt').read_text() == 'fixture base\n'
        assert hashlib.sha256(index.read_bytes()).hexdigest() == before
        sid, cards = writes[0]
        a = cards[0]
        body = dict(model='local', provider='local', base_url=lab.model_base, session_id=sid,
            workspace=str(lab.workspace), stream=True, permission_mode='never',
            messages=[dict(role='user', content=f'XEYO_PUBLISH apply {a["agentId"]} {a["attemptId"]}')])
        response = await client.post('/v1/chat/completions', json=body)
        assert response.status_code == 200
        results = []
        for line in response.text.splitlines():
            if line.startswith('data: {'):
                xy = json.loads(line[6:]).get('xy', {})
                if xy.get('type') == 'tool_result' and xy.get('name') == 'agent_apply':
                    results.append(xy)
        assert len(results) == 1 and not results[0]['is_error'], results
        assert (lab.workspace/'f.txt').read_text() == (Path(a['isolation']['worktree'])/'f.txt').read_text()
        assert hashlib.sha256(index.read_bytes()).hexdigest() == before
        return {'status': 'passed', 'parent_stops': 8, 'cancelled_agents': 32, 'stop_elapsed_s': stop_seconds,
                'write_sessions': 3, 'worktrees': paths, 'explicit_publications': 1, 'parent_index_preserved': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--directory', required=True)
    args = parser.parse_args()
    lab = Lab(args.directory)
    try:
        lab.start()
        result = asyncio.run(run(lab))
        (lab.directory/'result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        lab.close()
