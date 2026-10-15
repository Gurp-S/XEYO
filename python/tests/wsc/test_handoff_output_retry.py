"""Candidate expands only observed exhaustion and rechecks full admission."""
from copy import deepcopy
import pytest
from memory.wsc_handoff_output_retry import ENV, expanded


def test_verified_recovery_defaults_on_and_explicit_zero_restores_control(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert expanded('handoff_invalid_json', {'completion_tokens': 2048}, 2048) == 4096
    monkeypatch.setenv(ENV, '0')
    assert expanded('handoff_invalid_json', {'completion_tokens': 2048}, 2048) is None


@pytest.mark.parametrize('enabled', [False, True])
def test_output_exhaustion_candidate_is_opt_in(monkeypatch, enabled):
    monkeypatch.setenv(ENV, str(int(enabled)))
    assert expanded('handoff_invalid_json', {'completion_tokens': 2048}, 2048) == (4096 if enabled else None)
    for usage in (None, {}, {'completion_tokens': 2047}, {'completion_tokens': '2048'}):
        assert expanded('handoff_invalid_json', usage, 2048) is None
    assert expanded('handoff_invalid_state', {'completion_tokens': 2048}, 2048) is None
    assert expanded('handoff_invalid_json', {'completion_tokens': 8192}, 8192) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('small_capacity', [False, True])
async def test_same_rejected_declaration_obeys_output_and_capacity_bounds(monkeypatch, enabled, small_capacity):
    from types import SimpleNamespace
    from engine.abort import AbortController
    from memory import wsc_handoff_generation as generation
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    from tests.wsc.test_handoff_fact_disposition import prepared
    rows, raw = prepared()
    from memory.wsc_handoff_output_budget import reservation
    initial_output = reservation(rows)
    original = deepcopy(rows)
    monkeypatch.setenv(ENV, str(int(enabled)))
    monkeypatch.setattr(generation, 'request_measure', lambda *args, **kwargs: SimpleNamespace(input_tokens=100))
    caps, calls = [], []
    class Model:
        context_limit = 100 + initial_output + 1 if small_capacity else 100000
        last_usage = None
        output = initial_output
        def for_handoff(self, max_tokens):
            self.output = max_tokens
            caps.append(max_tokens)
            return self
        async def stream(self, messages, schemas, abort):
            calls.append(self.output)
            if self.output < initial_output * 2:
                self.last_usage = {'completion_tokens': self.output}
                candidate = {'_raw': '{"todos":['}
            else:
                self.last_usage = {'completion_tokens': 700}
                candidate = deepcopy(raw)
            yield ModelChunk(kind='tool_use', tool_use=ToolUse(f'declare-{len(calls)}', 'TodoWrite', candidate))
    invocation = generation.generate(Model(), [], rows, TodoWriteTool().schema(), AbortController(), account=lambda usage: None)
    if enabled and not small_capacity:
        result = await invocation
        assert result.input == raw and calls == [initial_output, initial_output * 2]
    else:
        with pytest.raises(ValueError, match='handoff_request_exceeds_capacity' if enabled else 'handoff_invalid_json'):
            await invocation
        assert len(calls) == (1 if enabled else generation.MAX_REQUESTS)
    assert caps[0] == initial_output and rows == original
