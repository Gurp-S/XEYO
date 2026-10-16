"""Wire-level completion and recovery contracts, including a stalled consumer."""
from __future__ import annotations

import asyncio
import json

import pytest

from engine import turn_runner, turn_snapshot


class Pool:
	def end(self, *_):
		pass

	def interrupt(self, *_, **__):
		return True


def wire(xy):
	return ('data: ' + json.dumps({'xy': xy}) + '\n\n').encode()


async def start(runner, producer, sid='session'):
	await runner.start(session_id=sid, lease_id=1, model='fixture', goal_text='',
		user_message_id='user', producer=producer, turn_id='turn')


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
	monkeypatch.setenv('XEYO_SESSIONS_DIR', str(tmp_path))
	monkeypatch.setenv('XEYO_AUDIT_LOG', str(tmp_path / 'audit.jsonl'))


@pytest.mark.asyncio
async def test_wire_tool_call_is_available_to_crash_recovery():
	runner = turn_runner.TurnRunner(Pool())
	ready, release = asyncio.Event(), asyncio.Event()

	async def producer():
		yield 1, wire({'type': 'tool_call', 'tool_use_id': 'write-1'}), 'tool_call'
		ready.set()
		await release.wait()

	await start(runner, producer)
	try:
		await ready.wait()
		snap = turn_snapshot.hydrate('session')
		assert snap.incomplete_tool_uses == ['write-1']
	finally:
		release.set()
		await runner.wait_done('session', timeout=2)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,payload', [
	('error', {'error': {'type': 'model_error', 'message': 'fixture failure'}}),
	('task_state_changed', {'xy': {'type': 'task_state_changed', 'task_status': 'failed', 'error': 'fixture failure'}}),
])
async def test_wire_failure_never_settles_as_success(kind, payload):
	runner = turn_runner.TurnRunner(Pool())

	async def producer():
		yield 1, ('data: ' + json.dumps(payload) + '\n\n').encode(), kind
		yield 2, b'data: [DONE]\n\n', 'done'

	await start(runner, producer)
	await runner.wait_done('session', timeout=2)
	assert runner.get_public('session').status == 'failed'
	assert turn_snapshot.hydrate('session').status == 'failed'


@pytest.mark.asyncio
@pytest.mark.parametrize('remaining', [4, 7])
async def test_stalled_subscriber_receives_gap_before_done(monkeypatch, remaining):
	monkeypatch.setattr(turn_runner, '_SUBSCRIBER_QUEUE_MAX', 4)
	runner = turn_runner.TurnRunner(Pool())
	release = asyncio.Event()

	async def producer():
		yield 1, b'data: {"first":true}\n\n', 'delta'
		await release.wait()
		for i in range(2, remaining + 1):
			yield i, f'data: {{"delta":{i}}}\n\n'.encode(), 'delta'
		yield remaining + 1, b'data: [DONE]\n\n', 'done'

	await start(runner, producer)
	stream = runner.subscribe('session')
	await anext(stream)
	release.set()
	await runner.wait_done('session', timeout=2)
	received = []
	try:
		async for frame in stream:
			if frame is not None:
				received.append(frame)
				if b'[DONE]' in frame:
					break  # Actual clients stop parsing at this protocol boundary.
	finally:
		await stream.aclose()
	assert any(b'stream_gap' in frame for frame in received), received
	assert b'[DONE]' in received[-1]


@pytest.mark.asyncio
async def test_done_waits_for_producer_cleanup_and_terminal_snapshot():
	runner = turn_runner.TurnRunner(Pool())
	cleanup = asyncio.Event()

	async def producer():
		yield 1, b'data: [DONE]\n\n', 'done'
		await asyncio.sleep(0.02)
		cleanup.set()

	await start(runner, producer)
	stream = runner.subscribe('session')
	try:
		assert b'[DONE]' in await anext(stream)
		assert cleanup.is_set()
		assert turn_snapshot.hydrate('session').status == 'succeeded'
	finally:
		await runner.wait_done('session', timeout=2)
		await stream.aclose()


@pytest.mark.asyncio
async def test_terminal_snapshot_failure_is_not_acknowledged_as_success(monkeypatch):
	runner = turn_runner.TurnRunner(Pool())
	release = asyncio.Event()

	async def producer():
		await release.wait()
		yield 1, b'data: [DONE]\n\n', 'done'

	await start(runner, producer)
	def fail(*args, **kwargs):
		raise OSError('injected disk failure')
	monkeypatch.setattr(turn_snapshot, '_atomic_write', fail)
	release.set()
	await runner.wait_done('session', timeout=2)
	assert runner.get_public('session').status == 'failed'
	frames = [frame async for frame in runner.subscribe('session')]
	assert any(b'snapshot_persist_failed' in frame for frame in frames if frame)


def test_failed_durable_replace_does_not_suppress_retry_fsync(monkeypatch):
	real = turn_snapshot._atomic_write
	observed = []
	def fail_once(path, payload, *, durable):
		observed.append(durable)
		if len(observed) == 1:
			raise OSError('injected replacement failure')
		real(path, payload, durable=durable)
	monkeypatch.setattr(turn_snapshot, '_atomic_write', fail_once)
	snap = turn_snapshot.TurnSnapshot(session_id='session', turn_id='turn', status='running')
	turn_snapshot.flush(snap)
	turn_snapshot.flush(snap)
	assert observed == [True, True]


def test_terminal_snapshots_release_fsync_bookkeeping():
	for i in range(100):
		turn_snapshot.flush(turn_snapshot.TurnSnapshot(session_id=f'session-{i}', turn_id='turn'))
	assert not any('session-' in key for key in turn_snapshot._last_fsync_at)


@pytest.mark.asyncio
async def test_tool_resolution_is_checkpointed_without_waiting_for_eight_deltas():
	runner = turn_runner.TurnRunner(Pool())
	ready, release = asyncio.Event(), asyncio.Event()
	async def producer():
		yield 1, wire({'tool_use_id':'write-1'}), 'tool_call'
		yield 2, wire({'tool_use_id':'write-1'}), 'tool_result'
		ready.set(); await release.wait()
	await start(runner, producer)
	try:
		await ready.wait()
		assert turn_snapshot.hydrate('session').last_event_id == 2
		assert turn_snapshot.hydrate('session').incomplete_tool_uses == []
	finally:
		release.set(); await runner.wait_done('session', timeout=2)


@pytest.mark.asyncio
async def test_delayed_stop_checkpoint_cannot_replace_a_newer_turn(monkeypatch):
	import threading
	runner = turn_runner.TurnRunner(Pool())
	release, next_release = asyncio.Event(), asyncio.Event()
	async def producer():
		await release.wait()
		if False: yield
	await start(runner, producer)
	entered, finish_write = threading.Event(), threading.Event()
	real = turn_runner.flush_turn
	def delayed(snap, **kwargs):
		if snap.status == 'stopping':
			entered.set(); assert finish_write.wait(5)
		return real(snap, **kwargs)
	monkeypatch.setattr(turn_runner, 'flush_turn', delayed)
	stop = asyncio.create_task(asyncio.to_thread(runner.mark_stopping, 'session'))
	await asyncio.to_thread(entered.wait, 3)
	try:
		release.set(); await runner.wait_done('session', timeout=2)
		async def next_producer():
			await next_release.wait()
			if False: yield
		await runner.start(session_id='session',lease_id=2,model='fixture',goal_text='',
			user_message_id='next',producer=next_producer,turn_id='next-turn')
		finish_write.set(); await stop
		assert turn_snapshot.hydrate('session').turn_id == 'next-turn'
	finally:
		finish_write.set(); next_release.set(); await stop
		await runner.wait_done('session',timeout=2)


@pytest.mark.asyncio
async def test_completed_disk_and_memory_cursors_agree():
	runner = turn_runner.TurnRunner(Pool())
	async def producer():
		yield 1, b'data: {"text":"complete"}\n\n', 'delta'
		yield 2, b'data: [DONE]\n\n', 'done'
	await start(runner,producer)
	await runner.wait_done('session',timeout=2)
	assert runner.get_public('session').last_event_id == turn_snapshot.hydrate('session').last_event_id == 2


@pytest.mark.asyncio
async def test_cancel_during_checkpoint_joins_writer_and_generator_cleanup(monkeypatch):
	import threading
	import time
	runner = turn_runner.TurnRunner(Pool())
	entered, finished = threading.Event(), threading.Event()
	cleaned = asyncio.Event()
	real = turn_snapshot._atomic_write
	def slow(path, data, **kwargs):
		if json.loads(data)['last_event_id'] == 1:
			entered.set(); time.sleep(.04); finished.set()
		return real(path, data, **kwargs)
	monkeypatch.setattr(turn_snapshot, '_atomic_write', slow)
	async def producer():
		try:
			yield 1, wire({'tool_use_id':'read-1'}), 'tool_call'
			await asyncio.sleep(10)
		finally:
			await asyncio.sleep(.01)
			cleaned.set()
	await start(runner,producer)
	assert await asyncio.to_thread(entered.wait,2)
	runner._turns['session'].task.cancel()
	await runner.wait_done('session',timeout=2)
	assert finished.is_set() and cleaned.is_set()
	assert turn_snapshot.hydrate('session').status == 'stopped'


@pytest.mark.asyncio
@pytest.mark.parametrize('turn_bound', [False, True])
async def test_stop_during_terminal_checkpoint_cannot_reopen_completed_turn(monkeypatch, turn_bound):
	import threading
	runner = turn_runner.TurnRunner(Pool())
	entered, release = threading.Event(), threading.Event()
	real = turn_runner.flush_turn
	def delayed(snap, **kwargs):
		if snap.status == 'succeeded':
			entered.set(); assert release.wait(5)
		return real(snap, **kwargs)
	monkeypatch.setattr(turn_runner, 'flush_turn', delayed)
	async def producer():
		yield 1, b'data: [DONE]\n\n', 'done'
	errors = []
	def stop_at_checkpoint():
		try:
			assert entered.wait(3)
			if turn_bound:
				from server.turn_control import interrupt_turn, TurnMismatch
				from server.inbox_registry import InboxRegistry
				with pytest.raises(TurnMismatch):
					interrupt_turn(runner, runner._pool, InboxRegistry(), 'session', 'turn')
			else:
				runner.mark_stopping('session')
		except BaseException as exc:
			errors.append(exc)
		finally:
			release.set()
	stopper = threading.Thread(target=stop_at_checkpoint)
	stopper.start()
	try:
		await start(runner, producer)
		await runner.wait_done('session', timeout=4)
	finally:
		release.set()
		await asyncio.to_thread(stopper.join, 4)
	assert not errors
	assert turn_snapshot.hydrate('session').status == runner.get_public('session').status == 'succeeded'


@pytest.mark.asyncio
async def test_repeated_cancellation_still_joins_checkpoint_writer():
	import threading
	from engine.turn_checkpoint import write_checkpoint
	entered, release = threading.Event(), threading.Event()
	def write():
		entered.set(); assert release.wait(3)
	work = asyncio.create_task(write_checkpoint(write))
	assert await asyncio.to_thread(entered.wait, 2)
	try:
		work.cancel(); await asyncio.sleep(.01)
		work.cancel(); await asyncio.sleep(.01)
		assert not work.done(), 'a cancelled write must finish before its owner exits'
	finally:
		release.set()
		with pytest.raises(asyncio.CancelledError):
			await work
