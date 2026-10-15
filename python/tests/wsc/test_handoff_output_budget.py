"""Output reserve grows with declarations, stays bounded and enters admission."""
from copy import deepcopy
from types import SimpleNamespace
import pytest

from memory.wsc_handoff_output_budget import reservation, MIN_TOKENS, MAX_TOKENS
from tests.wsc.test_task_continuity import receipt, task


def test_unobserved_and_small_declarations_keep_existing_floor():
    assert reservation([]) == MIN_TOKENS
    assert reservation(receipt('state', [task(text='short')])) == MIN_TOKENS


def test_payload_growth_is_content_based_monotonic_and_bounded():
    values = []
    for length in (100, 2000, 5000, 12000):
        rows = receipt('state', [task(text='x' * length)])
        before = deepcopy(rows)
        values.append(reservation(rows))
        assert rows == before
    assert values == sorted(values)
    assert values[0] == MIN_TOKENS and values[-1] == MAX_TOKENS
    assert values[1] > MIN_TOKENS


def test_utf8_payload_allowance_is_not_character_count():
    ascii_rows = receipt('state', [task(text='a' * 1000)])
    unicode_rows = receipt('state', [task(text='中' * 1000)])
    assert reservation(unicode_rows) > reservation(ascii_rows)


@pytest.mark.asyncio
async def test_larger_output_reserve_is_applied_before_model_request(monkeypatch):
    from engine.abort import AbortController
    from memory import wsc_handoff_generation as generation
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    rows = receipt('state', [task(text='x' * 5000)])
    requested, streamed = [], []
    class Model:
        context_limit = 1024 + MIN_TOKENS + 1
        last_usage = None
        def for_handoff(self, max_tokens):
            requested.append(max_tokens)
            return self
        async def stream(self, messages, tools, abort):
            streamed.append(True)
            if False: yield None
    monkeypatch.setattr(generation, 'request_measure', lambda *args, **kwargs: SimpleNamespace(input_tokens=1024))
    with pytest.raises(ValueError, match='handoff_request_exceeds_capacity'):
        await generation.generate(Model(), [], rows, TodoWriteTool().schema(), AbortController(), account=lambda usage: None)
    assert requested == [reservation(rows)] and not streamed
