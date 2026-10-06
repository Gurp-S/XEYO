"""Terminal exits preserve actual execution and stop subsequent expenditure."""
import asyncio
import uuid

import pytest

from engine.budget import BudgetTracker
from engine.query_engine import QueryEngine
from engine.terminal_settlement import settle_tool_exit
from model.chunks import ModelChunk
from msgtypes.events import PermissionPendingEvent, StoppedEvent, ToolResultEvent, UsageEvent
from msgtypes.message import ToolUse, assistant_text_message, tool_result_message
from permissions.policy import set_permission_mode
from session.message_store import MessageStore
from tools.base_tool import ToolResult
from tools.echo import EchoTool
from tools.file_write_tool.file_write_tool import FileWriteTool
from tools.tool_registry import ToolRegistry


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    for key in ('HOME', 'MEMORY_DIR', 'SESSIONS_DIR', 'SNAPSHOTS_DIR', 'USAGE_DIR', 'JOURNAL_DIR'):
        monkeypatch.setenv('XEYO_' + key, str(tmp_path / key.lower()))
    monkeypatch.setenv('XEYO_EARLY_READONLY_TOOLS', '1')
    return tmp_path


class _Model:
    last_usage = None

    def __init__(self, uses=(), wait=None):
        self.uses, self.wait, self.calls, self.inputs = uses, wait, 0, []

    async def stream(self, messages, tools, abort):
        self.calls += 1
        self.inputs.append(messages)
        yield ModelChunk(kind='text_delta', text='Received answer.')
        yield ModelChunk(kind='reasoning_block', block={'type': 'thinking', 'text': 'Observed fact', 'signature': 'opaque-signature'})
        if self.calls == 1:
            for use in self.uses:
                yield ModelChunk(kind='tool_use', tool_use=use)
            if self.wait is not None:
                await asyncio.wait_for(self.wait.wait(), 2)
            await asyncio.sleep(.02)
        self.last_usage = {'prompt_tokens': 100, 'completion_tokens': 10, 'usd': 1.0}


def make_engine(tmp_path, model, registry, limit=None):
    set_permission_mode('never')
    registry.set_cwd(str(tmp_path))
    return QueryEngine({'cwd': str(tmp_path), 'session_id': uuid.uuid4().hex,
        'tools': registry, 'model_client': model, 'provider': 'fake', 'model': 'offline',
        'max_budget_usd': limit, 'max_turns': 10})


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['text', 'read_completed', 'read_pending', 'write_not_started'])
async def test_budget_exit_preserves_output_and_completed_reads(isolated, case):
    registry = ToolRegistry()
    uses, wait, tool = [], None, None
    class Read(EchoTool):
        def __init__(self):
            self.started, self.done = asyncio.Event(), asyncio.Event()
            self.task = None
        async def execute(self, input, abort):
            self.task = asyncio.current_task()
            self.started.set()
            if case == 'read_pending':
                await asyncio.Event().wait()
            result = await super().execute(input, abort)
            self.done.set()
            return result
    if case.startswith('read_'):
        tool = Read()
        registry.register(tool)
        uses = [ToolUse(id='read', name='echo', input={'text': 'Actual read fact'})]
        wait = tool.done if case == 'read_completed' else tool.started
    if case == 'write_not_started':
        registry.register(FileWriteTool(cwd=str(isolated)))
        uses = [ToolUse(id='write', name='Write', input={'file_path': str(isolated / 'never.txt'), 'content': 'never'})]
    engine = make_engine(isolated, _Model(uses, wait), registry, .5)
    events = [event async for event in engine.submit('Read current state.')]
    history = engine.mutable_messages
    anchor = next(message for message in history if message.role == 'assistant')
    assert anchor.interrupted
    assert 'Received answer.' in str(anchor.content)
    assert {'type': 'thinking', 'text': 'Observed fact', 'signature': 'opaque-signature'} in anchor.content
    assert engine._session.budget.used_usd == 1.0
    assert len([event for event in events if isinstance(event, UsageEvent)]) == 1
    assert [event.reason for event in events if isinstance(event, StoppedEvent)] == ['budget_usd']
    results = [event for event in events if isinstance(event, ToolResultEvent)]
    assert len(results) == len(uses)
    if uses:
        assert len([message for message in history if message.tool_call_id == uses[0].id]) == 1
        if case == 'read_pending':
            assert results[0].status == 'cancelled'
            assert not results[0].is_error  # UI cancellation semantics
            assert history[-1].content[0]['is_error']  # no successful observation
        else:
            assert results[0].is_error == (case != 'read_completed')
    if case == 'read_completed':
        assert results[0].output == 'Actual read fact'
    if tool is not None:
        assert tool.task.done()
    assert not (isolated / 'never.txt').exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['abort', 'scheduler_error', 'authorized_error'])
async def test_batch_exit_keeps_real_completed_write_and_next_turn_fact(isolated, monkeypatch, failure):
    class ControlledWrite(FileWriteTool):
        def __init__(self):
            super().__init__(cwd=str(isolated))
            self.waiting, self.release = asyncio.Event(), asyncio.Event()
        async def execute(self, input, abort):
            if input['file_path'].endswith('second.txt'):
                if failure == 'authorized_error':
                    raise RuntimeError('injected authorized failure')
                self.waiting.set()
                await self.release.wait()
            return await super().execute(input, abort)
    tool, registry = ControlledWrite(), ToolRegistry()
    registry.register(tool)
    uses = [ToolUse(id=str(i), name='Write', input={'file_path': str(isolated / name), 'content': 'saved fact'})
            for i, name in enumerate(('first.txt', 'second.txt'))]
    model = _Model(uses)
    engine = make_engine(isolated, model, registry)
    events = []
    async def consume():
        async for event in engine.submit('Write the two files.'):
            events.append(event)
            if failure == 'authorized_error' and isinstance(event, PermissionPendingEvent):
                from permissions.store import default_permission_store
                default_permission_store().resolve(event.request_id, True, actor='test')
    if failure == 'scheduler_error':
        from engine.tool_coordinator import ToolCoordinator
        async def broken_batch(self, calls, abort, **kwargs):
            await self.run_one(calls[0], abort, **kwargs)
            raise RuntimeError('injected scheduler failure')
        monkeypatch.setattr(ToolCoordinator, 'run_batch', broken_batch)
        with pytest.raises(RuntimeError, match='injected scheduler failure'):
            await consume()
    elif failure == 'authorized_error':
        set_permission_mode('always')
        await consume()
        failed = next(e for e in events if isinstance(e, ToolResultEvent) and e.tool_use_id == '1')
        assert failed.is_error and 'injected authorized failure' in failed.output
        set_permission_mode('never')
    else:
        task = asyncio.create_task(consume())
        await asyncio.wait_for(tool.waiting.wait(), 3)
        engine.interrupt()
        tool.release.set()
        await asyncio.wait_for(task, 3)
    assert (isolated / 'first.txt').read_text(encoding='utf-8') == 'saved fact'
    assert not (isolated / 'second.txt').exists()
    first = next(event for event in events if isinstance(event, ToolResultEvent) and event.tool_use_id == '0')
    assert not first.is_error
    rows = [message for message in engine.mutable_messages if message.tool_call_id == '0']
    assert len(rows) == 1 and first.output == rows[0].content[0]['content']
    from session.hydrate import load_session_messages
    disk = load_session_messages(engine._session.session_id)
    assert first.output == next(message for message in disk if message.tool_call_id == '0').content[0]['content']
    _ = [event async for event in engine.submit('What completed?')]
    projected = next(message for message in model.inputs[-1] if message.get('tool_call_id') == '0')
    content = projected['content']
    text = content if isinstance(content, str) else '\n'.join(block.get('content', block.get('text', '')) for block in content)
    assert first.output.split('\n')[0] in text
    if isinstance(content, list):
        assert not any(block.get('is_error') for block in content)


@pytest.mark.parametrize('cost,unknown_first,expected', [(.2, True, True), (.2, False, True),
    (.1, True, True), (.1, False, True), (.05, True, False), (.05, False, False)])
def test_unknown_cost_does_not_disable_known_lower_bound(monkeypatch, cost, unknown_first, expected):
    monkeypatch.setattr('engine.budget.pricing_mod.estimate_usd_checked', lambda **kwargs: (None, 'none'))
    monkeypatch.setattr('engine.budget.estimate_cny', lambda **kwargs: None)
    tracker = BudgetTracker(usd_limit=.1, provider='offline', model='offline')
    usages = [{'prompt_tokens': 10}, {'prompt_tokens': 10, 'usd': cost}]
    for usage in usages if unknown_first else reversed(usages):
        tracker.add_usage(usage)
    assert tracker.usd_unpriced_turns == 1
    assert tracker.used_usd == cost
    assert tracker.over_budget is expected
    assert '费用未知' in tracker.usd_gate_note


@pytest.mark.asyncio
async def test_terminal_join_drains_completed_queue_without_pending_or_duplicate_rows():
    uses = [ToolUse(id=str(i), name='echo', input={}) for i in range(3)]
    store = MessageStore([assistant_text_message('', uses), tool_result_message('0', 'echo', 'already saved')])
    queue = asyncio.Queue()
    started, cleanup_done = asyncio.Event(), asyncio.Event()
    async def worker():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            queue.put_nowait((uses[1], ToolResult(content='completed fact')))
            await asyncio.sleep(0)
            cleanup_done.set()
    task = asyncio.create_task(worker())
    await started.wait()
    events = await settle_tool_exit(store, uses, {}, {'2': ToolResult(content='pending', metadata={'permission_pending': 'rid'})},
        reason='aborted', tasks=(task,), result_q=queue)
    assert task.done() and cleanup_done.is_set()
    assert [event.tool_use_id for event in events] == ['1', '2']
    assert events[0].output == 'completed fact' and not events[0].is_error
    assert events[1].is_error and events[1].output != 'pending'
    assert len([message for message in store.items if message.role == 'tool']) == 3


@pytest.mark.asyncio
async def test_result_dedup_is_scoped_to_current_assistant_call():
    use = ToolUse(id='reused-id', name='echo', input={})
    store = MessageStore([assistant_text_message('', [use]), tool_result_message(use.id, use.name, 'old fact'),
                          assistant_text_message('', [use])])
    events = await settle_tool_exit(store, [use], {}, {use.id: ToolResult(content='new fact')}, reason='aborted')
    assert len(events) == 1 and events[0].output == 'new fact'
    assert len([message for message in store.items if message.role == 'tool']) == 2
    assert await settle_tool_exit(store, [use], {}, {}, reason='aborted') == []


@pytest.mark.asyncio
@pytest.mark.parametrize('answered', [False, True])
async def test_interrupted_question_keeps_user_answer_or_cancelled_state(isolated, answered):
    from msgtypes.events import AskUserPendingEvent
    from permissions.ask_store import default_ask_store
    from tools.ask_user_question_tool.ask_user_question_tool import AskUserQuestionTool
    registry = ToolRegistry()
    registry.register(AskUserQuestionTool())
    use = ToolUse(id='ask', name='AskUserQuestion', input={'question': 'Local question?'})
    engine = make_engine(isolated, _Model([use]), registry)
    events = []
    async for event in engine.submit('Ask for the value.'):
        events.append(event)
        if isinstance(event, AskUserPendingEvent):
            if answered:
                default_ask_store().resolve_answer(event.request_id, 'actual answer', actor='user')
            engine.interrupt()
    result = next(event for event in events if isinstance(event, ToolResultEvent))
    assert result.is_error is not answered
    if answered:
        assert result.output == 'actual answer'
    else:
        assert result.status == 'cancelled' and result.output
