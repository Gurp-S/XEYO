"""Returned usage survives failed stream cleanup in both compaction methods."""
import pytest

from engine.abort import AbortController


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['semantic', 'structured'])
@pytest.mark.parametrize('close_fails', [False, True])
async def test_usage_accounted_once_even_when_close_fails(method, close_fails):
    usage = {'prompt_tokens': 31, 'completion_tokens': 7}
    accounted, requests = [], []

    class Stream:
        def __aiter__(self): return self
        async def __anext__(self): raise StopAsyncIteration
        async def aclose(self):
            if close_fails: raise OSError('cleanup_failed')

    class Client:
        context_limit = 100000
        last_usage = None
        def for_handoff(self, max_tokens): return self
        def stream(self, messages, tools, abort):
            requests.append(messages)
            self.last_usage = usage
            return Stream()

    rows = [{'role': 'user', 'message_id': 'source', 'content': 'pending task'}]
    if method == 'semantic':
        from memory.wsc_semantic_generation import generate
        call = generate(Client(), rows, AbortController(), account=accounted.append)
        expected = 'semantic_generation_empty'
    else:
        from memory.wsc_handoff_generation import generate
        from tools.todo_write_tool.todo_write_tool import TodoWriteTool
        call = generate(Client(), rows, rows, TodoWriteTool().schema(),
                        AbortController(), account=accounted.append)
        expected = 'handoff_declaration_missing'
    with pytest.raises(OSError if close_fails else ValueError,
                       match='cleanup_failed' if close_fails else expected):
        await call
    assert accounted == [usage]
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('reported', [None, {'prompt_tokens': 19, 'completion_tokens': 2}])
async def test_cleanup_accounts_final_usage_without_inventing_missing_usage(reported):
    from types import SimpleNamespace
    from memory.wsc_stream_cleanup import close_and_account
    client, accounted = SimpleNamespace(last_usage=None), []
    class Stream:
        async def aclose(self):
            client.last_usage = reported
            raise OSError('close_failed')
    with pytest.raises(OSError, match='close_failed'):
        await close_and_account(Stream(), client, accounted.append)
    assert accounted == [reported]
