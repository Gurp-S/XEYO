import asyncio
import json
import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import Request
from engine.turn_runner import TurnRunner


class Pool:
    def end(self, *args, **kwargs):
        pass


async def start(runner, tid):
    async def producer():
        yield 1, ('data: '+json.dumps({'text': tid})+'\n\n').encode(), 'delta'
        yield 2, b'data: [DONE]\n\n', 'done'
    await runner.start(session_id='s', lease_id=1, model='test', goal_text='', user_message_id='', producer=producer, turn_id=tid)
    await runner.wait_done('s', timeout=2)


@pytest.mark.asyncio
async def test_http_replay_rejects_another_turn(monkeypatch):
    from server.routers import sessions
    runner = TurnRunner(Pool())
    monkeypatch.setattr('engine.turn_runner.get_turn_runner', lambda: runner)
    await start(runner, 'new')
    app = FastAPI(); app.include_router(sessions.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        bad = await client.get('/v1/sessions/s/turns/current/events?cursor=1&expected_turn_id=old')
        assert bad.status_code == 409
        assert 'turn_mismatch' in bad.text
        good = await client.get('/v1/sessions/s/turns/current/events?cursor=0&expected_turn_id=new')
        assert good.status_code == 200 and '"text": "new"' in good.text


@pytest.mark.asyncio
async def test_turn_replaced_between_headers_and_subscription(monkeypatch):
    from server.routers.sessions import session_turn_events
    runner = TurnRunner(Pool())
    monkeypatch.setattr('engine.turn_runner.get_turn_runner', lambda: runner)
    await start(runner, 'old')
    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}
    request = Request({'type': 'http', 'method': 'GET', 'path': '/', 'headers': []}, receive)
    response = await session_turn_events('s', request, cursor=0, expected_turn_id='old')
    await start(runner, 'new')
    content = b''.join([frame async for frame in response.body_iterator])
    assert b'turn_mismatch' in content
    assert b'"text": "new"' not in content


@pytest.mark.asyncio
async def test_lost_replay_buffer_reports_gap_and_recovery_is_rejected():
    from engine.turn_snapshot import TurnSnapshot, flush
    flush(TurnSnapshot(session_id='s', turn_id='finished', status='succeeded', last_event_id=8))
    runner = TurnRunner(Pool())
    content = b''.join([frame async for frame in runner.subscribe('s', cursor=3, expected_turn_id='finished')])
    assert b'stream_gap' in content and b'[DONE]' in content
    flush(TurnSnapshot(session_id='s', turn_id='crashed', status='recovery_required', last_event_id=8))
    content = b''.join([frame async for frame in runner.subscribe('s', expected_turn_id='crashed')])
    assert b'recovery_required' in content and b'[DONE]' not in content
