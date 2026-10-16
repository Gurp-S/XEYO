"""Real TCP/SSE load and kill/restart faults; no in-process runtime monkeypatches."""
import argparse
import asyncio
import ctypes
import hashlib
import json
import os
import sqlite3
from pathlib import Path
import time

import httpx
from tests.soak_support.lab import Lab, PYTHON


def resources(pid):
    if os.name != 'nt':
        return {'pid': pid}
    from ctypes import wintypes as w
    class Memory(ctypes.Structure):
        _fields_ = [('cb', w.DWORD), ('faults', w.DWORD)] + [(n, ctypes.c_size_t) for n in
            ('peak_rss', 'rss', 'peak_pool', 'pool', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile')]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = w.HANDLE
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.GetProcessHandleCount.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        return {'pid': pid}
    try:
        m, count = Memory(), w.DWORD()
        m.cb = ctypes.sizeof(m)
        api = ctypes.WinDLL('psapi')
        api.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD]
        api.GetProcessMemoryInfo(handle, ctypes.byref(m), m.cb)
        kernel.GetProcessHandleCount(handle, ctypes.byref(count))
        return {'pid': pid, 'rss_bytes': m.rss, 'handles': count.value}
    finally:
        kernel.CloseHandle(handle)


class Load:
    def __init__(self, lab, seconds, sessions=8, workers=4):
        self.lab, self.seconds, self.sessions, self.workers = lab, seconds, sessions, workers
        self.metrics = dict(waves=0, parent_turns=0, attempts=0, send_requests=0, messages=0,
                            reattachments=0, cancelled=0, retried=0, stale_rejected=0, crashes=0)
        self.began = time.monotonic()

    def record(self, kind, **facts):
        record = dict(kind=kind, elapsed_s=round(time.monotonic()-self.began, 2), **facts)
        with (self.lab.directory/'events.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(record)+'\n')
        print(json.dumps(record), flush=True)

    async def request(self, method, path, **kwargs):
        r = await self.client.request(method, path, **kwargs)
        assert r.status_code == 200, (path, r.status_code, r.text[:1000])
        return r.json()

    async def cards(self, sid, token):
        result = await self.request('GET', f'/v1/sessions/{sid}/agents')
        return [a for a in result['agents'] if token in a['desc']]

    async def until(self, fn, check, timeout=60):
        async with asyncio.timeout(timeout):
            while True:
                result = await fn()
                if check(result):
                    return result
                await asyncio.sleep(.1)

    async def stream(self, sid, token, delay, detach=True):
        body = dict(model='local', provider='local', base_url=self.lab.model_base, session_id=sid,
            workspace=str(self.lab.workspace), stream=True, permission_mode='never',
            messages=[dict(role='user', content=f'XEYO_SOAK {token} {self.workers} {delay}')])
        cursor, turn, seen, content = 0, '', set(), ''
        method, url, kwargs = 'POST', '/v1/chat/completions', {'json': body}
        while True:
            async with self.client.stream(method, url, **kwargs) as r:
                assert r.status_code == 200, (r.status_code, await r.aread())
                async for line in r.aiter_lines():
                    if not line.startswith('data:'):
                        continue
                    raw = line[5:].strip()
                    if raw == '[DONE]':
                        assert f'PARENT-DONE-{token}' in content, content
                        return turn
                    frame = json.loads(raw)
                    xy = frame.get('xy', frame.get('xeyo', {}))
                    ident = frame.get('xeyo_event_id', xy.get('event_id', 0))
                    tid = frame.get('xeyo_turn_id', xy.get('turn_id', ''))
                    if tid:
                        assert not turn or turn == tid, (turn, tid)
                        turn = tid
                    if ident:
                        assert ident not in seen and ident > cursor, (ident, cursor)
                        seen.add(ident)
                        cursor = ident
                    if xy.get('type') == 'tool_result' and xy.get('is_error') and xy.get('name') == 'Agent':
                        raise AssertionError(xy)
                    content += frame.get('choices', [{}])[0].get('delta', {}).get('content', '') or ''
                    if detach and cursor >= 4:
                        detach = False
                        self.metrics['reattachments'] += 1
                        break
                else:
                    raise AssertionError('EOF without DONE')
            await asyncio.sleep(.15)
            method, url, kwargs = 'GET', f'/v1/sessions/{sid}/turns/current/events', {'params': {'cursor': cursor}}

    async def session(self, n, wave, crash=False):
        sid = (await self.request('POST', '/v1/sessions', json={'workspace': str(self.lab.workspace)}))['session_id']
        token = f'w{wave}s{n}'
        task = asyncio.create_task(self.stream(sid, token, 12 if crash else 4))
        self.tasks.append(task)
        cards = await self.until(lambda: self.cards(sid, token), lambda a: len(a) == self.workers)
        self.metrics['attempts'] += len(cards)
        async def mail(card):
            mid = f'MAIL-{token}-{card["taskId"]}'
            receipts = await asyncio.gather(*(self.request('POST', f'/v1/sessions/{sid}/agents/{card["agentId"]}/inbox',
                json={'text': mid, 'message_id': mid}) for _ in range(2)))
            assert receipts[0].get('messageId') == receipts[1].get('messageId') == mid, receipts
            self.metrics['send_requests'] += 2
            self.metrics['messages'] += 1
        await asyncio.gather(*(mail(a) for a in cards))
        if crash:
            return sid, token, cards, task
        cancelled = cards[0] if n % 4 == 0 else None
        if cancelled:
            await self.request('POST', f'/v1/sessions/{sid}/agents/{cancelled["agentId"]}/cancel', json={'attempt_id': cancelled['attemptId']})
            self.metrics['cancelled'] += 1
        await task
        await self.until(lambda: self.request('GET', f'/v1/sessions/{sid}/task'), lambda t: not t['busy'])
        if cancelled:
            await self.retry(sid, cancelled)
        settled = await self.until(lambda: self.cards(sid, token), lambda a: all(x['status'] != 'running' for x in a))
        assert all(a['runtimeState'] == 'completed' for a in settled), settled
        assert all(a['inboxCount'] == 0 for a in settled), settled
        self.metrics['parent_turns'] += 1
        return sid, token, settled

    async def retry(self, sid, card):
        path = f'/v1/sessions/{sid}/agents/{card["agentId"]}'
        result = await self.request('POST', path+'/retry', json={'attempt_id': card['attemptId'],
            'provider': 'local', 'model': 'local', 'base_url': self.lab.model_base})
        assert not result.get('is_error'), result
        assert result['attempt_id'] != card['attemptId'], result
        self.metrics['attempts'] += 1
        self.metrics['retried'] += 1
        r = await self.client.post(path+'/cancel', json={'attempt_id': card['attemptId']})
        assert r.status_code == 409, (r.status_code, r.text)
        self.metrics['stale_rejected'] += 1

    async def fault(self, wave):
        entries = await asyncio.gather(*(self.session(n, wave, True) for n in range(self.sessions)))
        await asyncio.to_thread(self.lab.crash)
        self.metrics['crashes'] += 1
        results = await asyncio.gather(*(e[3] for e in entries), return_exceptions=True)
        assert all(isinstance(r, Exception) for r in results), results
        await asyncio.to_thread(self.lab.restart)
        for sid, token, cards, _ in entries:
            status = await self.request('GET', f'/v1/sessions/{sid}/task')
            assert status['status'] == 'recovery_required', status
            recovered = await self.cards(sid, token)
            assert all(a['runtimeState'] == 'interrupted' for a in recovered), recovered
            # Initial model request and mail delivery can race: either the
            # durable transcript already contains it, or it remains queued.
            assert all(a['inboxCount'] in (0, 1) for a in recovered), recovered
            with sqlite3.connect(self.lab.directory/'sessions/_agent_runtime/runs.sqlite3') as db:
                for a in recovered:
                    rows = db.execute('SELECT state FROM mailbox WHERE session=? AND recipient=? AND kind=?',
                        (sid, a['agentId'], 'message')).fetchall()
                    assert len(rows) == 1, rows
            await self.request('POST', f'/v1/sessions/{sid}/recovery/abandon', json={'turn_id': status['turn_id']})
        # HTTP retry is foreground and owns the parent session busy lease.
        async def resume(entry):
            sid, token, cards, _ = entry
            for card in cards:
                await self.retry(sid, card)
            rows = await self.cards(sid, token)
            assert all(a['runtimeState'] == 'completed' and a['inboxCount'] == 0 for a in rows), rows
        await asyncio.gather(*(resume(e) for e in entries))
        self.record('crash_recovered', **self.metrics)

    async def run(self):
        self.tasks = []
        async with httpx.AsyncClient(base_url=self.lab.base, timeout=120, limits=httpx.Limits(max_connections=150)) as self.client:
            wave = 0
            while time.monotonic()-self.began < self.seconds:
                start = time.monotonic()
                self.tasks.clear()
                if wave % 15 == 7:
                    await self.fault(wave)
                else:
                    await asyncio.gather(*(self.session(n, wave) for n in range(self.sessions)))
                self.metrics['waves'] += 1
                self.record('wave', **self.metrics, **resources(self.lab.backend_pid))
                wave += 1
                await asyncio.sleep(max(0, 10-(time.monotonic()-start)))


async def main(args):
    lab = Lab(args.directory)
    load = Load(lab, args.seconds, args.sessions, args.workers)
    outcome = {'status': 'running'}
    try:
        lab.start()
        load.began = time.monotonic()
        await load.run()
        outcome['status'] = 'passed'
    except BaseException as exc:
        outcome = {'status': 'failed', 'error': repr(exc)}
        raise
    finally:
        outcome.update(elapsed_s=round(time.monotonic()-load.began, 2), **load.metrics)
        outcome['source_sha256'] = {str(p.relative_to(PYTHON)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [PYTHON/'engine/agent_runtime.py', PYTHON/'engine/turn_runner.py', PYTHON/'server/routers/sessions.py']}
        (lab.directory/'result.json').write_text(json.dumps(outcome, indent=2), encoding='utf-8')
        for task in getattr(load, 'tasks', []):
            task.cancel()
        await asyncio.gather(*getattr(load, 'tasks', []), return_exceptions=True)
        lab.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True)
    parser.add_argument('--seconds', type=float, default=1800)
    parser.add_argument('--sessions', type=int, default=8)
    parser.add_argument('--workers', type=int, default=4)
    asyncio.run(main(parser.parse_args()))
