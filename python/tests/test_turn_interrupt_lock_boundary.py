import asyncio
import pytest
from engine.turn_runner import TurnRunner
from server.inbox_registry import InboxRegistry
from server.turn_control import interrupt_turn
from engine.turn_snapshot import hydrate


@pytest.mark.asyncio
async def test_interrupt_checkpoint_releases_lifecycle_locks(tmp_path):
    release = asyncio.Event()
    class Pool:
        def interrupt(self, *args, **kwargs):
            return True
        def end(self, *args, **kwargs):
            pass
    pool = Pool(); runner = TurnRunner(pool); inbox = InboxRegistry()
    async def producer():
        await release.wait()
        yield 1, b'data: [DONE]\n\n', 'done'
    await runner.start(session_id='lock-test', lease_id=1, model='local', goal_text='',
        user_message_id='', producer=producer, turn_id='owned-turn')
    original = runner._persist
    def checked(*args, **kwargs):
        # Fail deterministically instead of hanging the test process forever.
        assert not runner._tlock.locked(), 'checkpoint called while lifecycle lock is held'
        assert not inbox._lock.locked(), 'checkpoint called while inbox lock is held'
        return original(*args, **kwargs)
    runner._persist = checked
    try:
        interrupt_turn(runner, pool, inbox, 'lock-test', 'owned-turn')
        assert runner.get_public('lock-test').status == 'stopping'
        assert hydrate('lock-test').stop_reason == 'user_stop'
        assert 'lock-test' in inbox._paused
    finally:
        release.set()
        await runner.wait_done('lock-test', timeout=2)
