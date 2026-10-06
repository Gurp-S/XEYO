"""Execution boundaries retain facts across cancellation, approval and rewind."""
import asyncio
import importlib
import json

import pytest

from engine.abort import AbortController
from engine.terminal_settlement import settle_tool_exit
from engine.tool_coordinator import ToolCoordinator
from memory.working import WorkingSnapshot, reset_rollback_state
from msgtypes.message import ToolUse, assistant_text_message, tool_result_message, user_message
from session.message_store import MessageStore
from tools.base_tool import ToolResult


@pytest.mark.asyncio
async def test_approved_execution_keeps_timeout_and_skips_second_approval(monkeypatch):
    class Registry:
        async def run(self, use, abort, *, coordinator, skip_ask=False):
            assert skip_ask
            await asyncio.Event().wait()
    monkeypatch.setenv('XEYO_TOOL_TIMEOUT_S', '.01')
    result = await ToolCoordinator(Registry()).run_authorized(ToolUse('u', 'probe', {}), AbortController())
    assert result.is_error and result.error_kind == 'TIMEOUT'
    assert result.metadata['tool_call_state'] == 'failed'


@pytest.mark.asyncio
async def test_join_preserves_actual_result_returned_during_cleanup():
    started = asyncio.Event()
    async def work():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return ToolResult('actual observation')
    use = ToolUse('read', 'Read', {})
    store = MessageStore([assistant_text_message('', [use])])
    task = asyncio.create_task(work())
    await started.wait()
    events = await settle_tool_exit(store, [use], {'read':task}, {}, reason='aborted')
    assert events[0].output == 'actual observation'
    assert not events[0].is_error
    assert len([m for m in store.items if m.role == 'tool']) == 1


def test_cancelled_receipt_cannot_commit_a_file_change():
    from synaptic.graph import build_graph
    from synaptic.filestate import build_file_states
    read = ToolUse('read', 'Read', {'file_path':'example.py'})
    write = ToolUse('write', 'Write', {'file_path':'example.py','content':'changed'})
    store = MessageStore([assistant_text_message('', [read]),
        tool_result_message('read', 'Read', 'original'), assistant_text_message('', [write]),
        tool_result_message('write', 'Write', 'cancelled', is_error=False, status='cancelled')])
    rows = store.as_api_messages()
    assert not build_file_states(build_graph(rows), rows)['example.py'].stale
    from synaptic.textutil import content_hash, tool_result_blocks
    assert build_file_states(build_graph(rows), rows)['example.py'].observed_hash == content_hash('original')
    assert len(tool_result_blocks(rows[-1])) == 1
    assert rows[-1]['content'][0]['is_error'] is True
    assert 'status' not in rows[-1]['content'][0]  # vendor protocol is unchanged


def test_shared_rewind_reset_discards_old_cooldown_without_changing_identity():
    snap = WorkingSnapshot(session_id='timeline', c2_gap_shots=20, compact_cursor=10)
    reset_rollback_state(snap)
    assert snap.c2_gap_shots == snap.compact_cursor == 0
    assert snap.session_id == 'timeline'


@pytest.mark.asyncio
async def test_failed_append_reports_failure_and_recovers_on_explicit_flush(tmp_path, monkeypatch):
    recorder = importlib.import_module('session.record_transcript')
    assert recorder.flush_pending_sync()
    original = recorder._write_batch
    calls = []
    def fail(batch):
        calls.append(1)
        raise OSError('temporary append failure')
    path = tmp_path/'recover.jsonl'
    known = set()
    message = user_message('retained fact')
    monkeypatch.setattr(recorder, '_write_batch', fail)
    try:
        await recorder.record_transcript([message], session_id='recover', path=path, known_ids=known)
        assert not recorder.flush_pending_sync()
        with pytest.raises(OSError):
            recorder.flush_transcript()
        assert len(calls) <= 3  # no automatic retry loop
    finally:
        monkeypatch.setattr(recorder, '_write_batch', original)
        assert recorder.flush_pending_sync()
    assert [row['id'] for row in recorder.load_transcript(path)] == [message.id]
    assert await recorder.record_transcript([message], session_id='recover', path=path, known_ids=known) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('partial', [False, True])
async def test_partial_append_retry_preserves_complete_rows_once(tmp_path, monkeypatch, partial):
    recorder = importlib.import_module('session.record_transcript')
    assert recorder.flush_pending_sync()
    original = recorder._write_batch
    path = tmp_path/'partial.jsonl'
    messages = [user_message('first'),user_message('second')]
    def fail(batch):
        lines = [line for _,_,line in batch]
        path.write_text(lines[0] + (lines[1][:24] if partial else lines[1]), encoding='utf-8')
        raise OSError('partial append or fsync failure')
    monkeypatch.setattr(recorder, '_write_batch', fail)
    try:
        await recorder.record_transcript(messages, session_id='partial', path=path, known_ids=set())
        with recorder._cv:
            assert recorder._cv.wait_for(lambda:bool(recorder._failed), timeout=3)
    finally:
        monkeypatch.setattr(recorder, '_write_batch', original)
        assert recorder.flush_pending_sync()
    assert [row['id'] for row in recorder.load_transcript(path)] == [m.id for m in messages]


@pytest.mark.asyncio
async def test_mixed_paths_retry_does_not_duplicate_already_written_session(tmp_path, monkeypatch):
    recorder = importlib.import_module('session.record_transcript')
    assert recorder.flush_pending_sync()
    original = recorder._write_batch
    a, b = tmp_path/'a.jsonl',tmp_path/'b.jsonl'
    first, second = user_message('a'),user_message('b')
    # Submit both paths in one batch before the writer can take the queue.
    def fail(batch):
        if batch[0][1] == str(a):
            a.write_text(batch[0][2], encoding='utf-8')
        raise OSError('second path failed')
    monkeypatch.setattr(recorder, '_write_batch', fail)
    try:
        with recorder._cv:
            await recorder.record_transcript([first],session_id='a',path=a,known_ids=set())
            await recorder.record_transcript([second],session_id='b',path=b,known_ids=set())
        with recorder._cv:
            assert recorder._cv.wait_for(lambda:bool(recorder._failed),timeout=3)
    finally:
        monkeypatch.setattr(recorder, '_write_batch', original)
        assert recorder.flush_pending_sync()
    assert [r['id'] for r in recorder.load_transcript(a)] == [first.id]
    assert [r['id'] for r in recorder.load_transcript(b)] == [second.id]


@pytest.mark.asyncio
async def test_failed_session_does_not_prevent_another_session_from_writing(tmp_path, monkeypatch):
    recorder = importlib.import_module('session.record_transcript')
    assert recorder.flush_pending_sync()
    original = recorder._write_batch
    bad, good = tmp_path/'bad.jsonl',tmp_path/'good.jsonl'
    messages = [user_message('bad'), user_message('good')]
    def fail_one(batch):
        if batch[0][1] == str(bad):
            raise OSError('one path unavailable')
        original(batch)
    monkeypatch.setattr(recorder, '_write_batch', fail_one)
    try:
        with recorder._cv:
            await recorder.record_transcript([messages[0]],session_id='bad',path=bad,known_ids=set())
            await recorder.record_transcript([messages[1]],session_id='good',path=good,known_ids=set())
        assert not recorder.flush_pending_sync()
        assert [r['id'] for r in recorder.load_transcript(good)] == [messages[1].id]
    finally:
        monkeypatch.setattr(recorder, '_write_batch', original)
        assert recorder.flush_pending_sync()
    assert [r['id'] for r in recorder.load_transcript(bad)] == [messages[0].id]
