import asyncio
import pytest


@pytest.mark.asyncio
async def test_synthetic_disconnect_during_checkpoint_still_starts_turn(tmp_path, monkeypatch):
    from engine import turn_runner
    from server.app import app
    from server.synthetic_round import note_request_env, submit_synthetic
    from server.deps import _pool
    monkeypatch.setenv('XEYO_ALLOW_FAKE_MODEL', '1')
    monkeypatch.setenv('XEYO_NO_PREWARM', '1')
    original = turn_runner.write_checkpoint
    async def delayed(function, *args, **kwargs):
        if kwargs.get('begin'):
            await asyncio.sleep(.05)
        return await original(function, *args, **kwargs)
    monkeypatch.setattr(turn_runner, 'write_checkpoint', delayed)
    sid = 'admission-disconnect-test'
    note_request_env(sid, {'model': 'fake', 'provider': 'fake', 'workspace': str(tmp_path),
        'api_key': '', 'permission_mode': 'never'})
    async with app.router.lifespan_context(app):
        assert await submit_synthetic(sid, 'hello admission', surface='inbox', message_id='queued-user')
        await asyncio.sleep(.3)
        runner = turn_runner.get_turn_runner()
        public = runner.get_public(sid)
        assert public is not None, 'accepted request lost before producer admission'
        assert await runner.wait_done(sid, timeout=5)
        assert not _pool.is_busy(sid), 'accepted request leaked the busy lease'
        assert runner.get_public(sid).status == 'succeeded'
