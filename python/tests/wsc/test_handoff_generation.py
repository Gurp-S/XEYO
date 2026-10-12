import pytest

from memory.wsc_handoff_generation import limited_client, generate, OUTPUT_TOKENS
from tools.todo_write_tool.todo_write_tool import TodoWriteTool


def test_argument_diagnostics_never_unwrap_valid_json_or_change_other_inputs():
    from copy import deepcopy
    from memory.wsc_handoff_feedback import invalid_arguments
    for value in ({'_raw': '{"todos": []}'}, {'_raw': 1},
                  {'_raw': 'broken', 'checkpoint': {}}, ['broken']):
        before = deepcopy(value)
        assert invalid_arguments(value) is None and value == before


@pytest.mark.asyncio
async def test_repeated_malformed_arguments_stop_at_existing_limit_without_declaration():
    from copy import deepcopy
    from engine.abort import AbortController
    from memory.wsc_handoff_generation import MAX_REQUESTS
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    sources = [{'role': 'user', 'message_id': 'spec', 'content': '当前规范'}]
    original, usages = deepcopy(sources), []
    class Client:
        last_usage = None
        async def stream(self, messages, tools, abort):
            self.last_usage = {'prompt_tokens': 20, 'completion_tokens': 10}
            yield ModelChunk(kind='tool_use', tool_use=ToolUse(
                f'bad-{len(usages)}', 'TodoWrite', {'_raw': '{"todos": []}, extra'}))
    class Model:
        context_limit = 100000
        def for_handoff(self, max_tokens): return Client()
    with pytest.raises(ValueError, match='^handoff_invalid_json$'):
        await generate(Model(), sources, sources, TodoWriteTool().schema(),
            AbortController(), account=usages.append)
    assert len(usages) == MAX_REQUESTS and sources == original


@pytest.mark.asyncio
async def test_provider_malformed_arguments_receive_isolated_rejection_without_raw_repair():
    from copy import deepcopy
    import json
    from engine.abort import AbortController
    from model._openai_common import finish_tool_bufs
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    sources = [{'role': 'user', 'message_id': 'spec', 'content': '当前规范'}]
    before = deepcopy(sources)
    malformed = '{"todos": []}, "checkpoint": {}'
    frames, usages = [], []
    class Client:
        last_usage = None
        async def stream(self, messages, tools, abort):
            attempt = len(frames)
            frames.append(deepcopy(messages))
            self.last_usage = {'prompt_tokens': 20, 'completion_tokens': 10}
            if attempt == 0:
                chunks = finish_tool_bufs({0: {'id': 'bad', 'name': 'TodoWrite', 'arguments': malformed}})
                assert chunks[0].tool_use.input == {'_raw': malformed}
                yield chunks[0]
            else:
                use = messages[-2]['content'][0]
                rejection = messages[-1]['content'][0]
                assert use['input'] == {'_raw': malformed} and rejection['tool_use_id'] == 'bad'
                assert rejection['is_error']
                error = json.loads(rejection['content'])
                assert error == {'error': 'handoff_invalid_json', 'message': 'Extra data',
                    'line': 1, 'column': 14, 'position': 13}
                yield ModelChunk(kind='tool_use', tool_use=ToolUse('valid', 'TodoWrite', {
                    'todos': [], 'checkpoint': {'objective': '', 'context_message_ids': []}}))
    class Model:
        context_limit = 100000
        def for_handoff(self, max_tokens): return Client()
    result = await generate(Model(), sources, sources, TodoWriteTool().schema(),
        AbortController(), account=usages.append)
    assert result.id == 'valid' and len(frames) == len(usages) == 2 and sources == before


def test_atomic_handoff_schema_separates_message_and_invocation_namespaces():
    from copy import deepcopy
    from memory.wsc_handoff_generation import source_schema
    from tests.wsc._fixtures import msg_asst_use, msg_tool
    sources = [dict(msg_asst_use("verify-call", "Bash", {}), message_id="call-message"),
               dict(msg_tool("verify-call", "Bash", "failed", is_error=True), message_id="result-message"),
               {"role": "user", "message_id": "spec", "content": "规范"}]
    schema = TodoWriteTool().schema()
    before = deepcopy(schema)
    constrained, identities = source_schema(schema, sources)
    props = constrained["input_schema"]["properties"]["checkpoint"]["properties"]
    assert props["context_message_ids"]["items"]["enum"] == ["call-message", "result-message", "spec"]
    assert props["verification_call_ids"]["items"]["enum"] == ["verify-call"]
    assert identities[1]["tool_result_call_ids"] == ["verify-call"]
    assert constrained["input_schema"]["required"] == ["todos", "checkpoint"]
    assert constrained["input_schema"]["properties"]["checkpoint"]["required"] == ["context_message_ids"]
    assert schema == before


@pytest.mark.parametrize("kind", ["deepseek", "openai", "anthropic"])
def test_handoff_output_cap_is_in_actual_provider_body_without_mutating_main_client(kind):
    from model.deepseek import DeepSeekModelClient
    from model.openai_compat import OpenAICompatClient
    from model.anthropic import AnthropicModelClient
    clients = {"deepseek": DeepSeekModelClient, "openai": OpenAICompatClient, "anthropic": AnthropicModelClient}
    client = clients[kind](api_key="fixture-key", model="fixture", base_url="https://fixture.invalid")
    before = client._build_body([{"role": "user", "content": "fixture"}], [], stream=False)
    bounded = limited_client(client)
    after = bounded._build_body([{"role": "user", "content": "fixture"}], [], stream=False)
    assert after["max_tokens"] == OUTPUT_TOKENS
    assert client._build_body([{"role": "user", "content": "fixture"}], [], stream=False) == before
    assert bounded is not client


@pytest.mark.asyncio
async def test_generation_without_declaration_is_accounted_once_and_never_committed():
    from engine.abort import AbortController
    from model.chunks import ModelChunk
    usage = []
    class Client:
        last_usage = None
        async def stream(self, messages, tools, abort):
            self.last_usage = {"prompt_tokens": 12, "completion_tokens": 3}
            yield ModelChunk(kind="text_delta", text="无法声明当前任务")
    class Model:
        context_limit = 100000
        def for_handoff(self, max_tokens): return Client()
    with pytest.raises(ValueError, match="handoff_declaration_missing"):
        await generate(Model(), [{"role": "user", "content": "规范"}],
            [{"role": "user", "message_id": "spec", "content": "规范"}],
            TodoWriteTool().schema(),
            AbortController(), account=usage.append)
    assert usage == [{"prompt_tokens": 12, "completion_tokens": 3}]


@pytest.mark.asyncio
@pytest.mark.parametrize("repair", [True, False])
@pytest.mark.parametrize("failure", ["quote", "unbound"])
async def test_rejected_quote_can_be_corrected_in_isolated_bounded_generation(repair, failure):
    from engine.abort import AbortController
    from memory.wsc_handoff_generation import MAX_REQUESTS
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from copy import deepcopy
    sources = [{"role": "user", "message_id": "spec", "content": "金额使用整数分"}]
    original = deepcopy(sources)
    usage, attempts = [], []
    error_code = "handoff_fact_quote_not_in_source" if failure == "quote" else "handoff_fact_source_not_unique_or_bound"
    class Client:
        last_usage = None
        async def stream(self, messages, tools, abort):
            attempt = len(attempts)
            attempts.append(deepcopy(messages))
            self.last_usage = {"prompt_tokens": 12, "completion_tokens": 3}
            if attempt:
                receipt = messages[-1]["content"][0]
                import json
                assert receipt["is_error"] and json.loads(receipt["content"]) == {
                    "error": error_code, "field": "constraints", "index": 0, "source_message_id": "spec"}
            quote = "金额使用整数分" if failure == "unbound" or repair and attempt else "凭空生成的约束"
            contexts = [] if failure == "unbound" and not (repair and attempt) else ["spec"]
            yield ModelChunk(kind="tool_use", tool_use=ToolUse(f"declaration-{attempt}", "TodoWrite", {
                "todos": [], "checkpoint": {"objective": "验收金额", "context_message_ids": contexts,
                    "constraints": [{"source_message_id": "spec", "quote": quote}]}}))
    class Model:
        context_limit = 100000
        def for_handoff(self, max_tokens): return Client()
    async def invoke():
        return await generate(Model(), [{"role": "user", "content": "验收金额"}], sources,
            TodoWriteTool().schema(), AbortController(), account=usage.append)
    if repair:
        assert (await invoke()).id == "declaration-1"
        assert len(usage) == 2
    else:
        with pytest.raises(ValueError, match=error_code): await invoke()
        assert len(usage) == MAX_REQUESTS
    assert sources == original


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["HandoffSource", "HandoffCatalog"])
async def test_read_argument_failure_is_neutral_paired_and_repairable_without_state_change(name):
    from copy import deepcopy
    import json
    from engine.abort import AbortController
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    source = [{"id": "spec", "role": "user", "content": "当前规范"}]
    before = deepcopy(source)
    requests, reads = [], []
    class Model:
        context_limit = 100000
        last_usage = None
        def for_handoff(self, max_tokens): return self
        async def stream(self, messages, tools, abort):
            index = len(requests)
            requests.append(deepcopy(messages))
            if index == 0:
                args = {"message_id": "spec", "limit": 5} if name == "HandoffSource" else {"start": 0, "limit": 0}
            elif index == 1:
                feedback = messages[-1]["content"][0]
                assert feedback["is_error"] is True and json.loads(feedback["content"])["tool"] == name
                assert source == before
                args = {"message_id": "spec", "limit": 5, "offset": 0} if name == "HandoffSource" else {"start": 0, "limit": 1}
            else:
                assert messages[-1]["content"][0]["is_error"] is False
                yield ModelChunk(kind="tool_use", tool_use=ToolUse("declare", "TodoWrite", {
                    "todos": [], "checkpoint": {"objective": "", "context_message_ids": ["spec"]}}))
                return
            yield ModelChunk(kind="tool_use", tool_use=ToolUse(f"read-{index}", name, args))
    result = await generate(Model(), source, source, TodoWriteTool().schema(), AbortController(),
                            account=lambda usage: None, admit_read=lambda: reads.append(True))
    assert result.id == "declare" and len(requests) == 3 and len(reads) == 2
    assert source == before


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_field", ["checkpoint", "root"])
async def test_invalid_declaration_shape_is_repaired_without_committing_rejected_call(invalid_field):
    from copy import deepcopy
    import json
    from engine.abort import AbortController
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse

    sources = [{"role": "user", "message_id": "spec", "content": "当前规范"}]
    before = deepcopy(sources)
    requests, usages = [], []

    class Client:
        last_usage = None

        async def stream(self, messages, tools, abort):
            attempt = len(requests)
            requests.append(deepcopy(messages))
            self.last_usage = {"prompt_tokens": 20, "completion_tokens": 10}
            raw = {"todos": [], "checkpoint": {"objective": "", "context_message_ids": []}}
            if attempt == 0:
                target = raw["checkpoint"] if invalid_field == "checkpoint" else raw
                target["unexpected"] = "not a task fact"
            else:
                error = json.loads(messages[-1]["content"][0]["content"])
                assert error["field"] == invalid_field
                assert error["extra_fields"] == ["unexpected"]
                assert messages[-1]["content"][0]["is_error"] is True
            yield ModelChunk(kind="tool_use", tool_use=ToolUse(f"shape-{attempt}", "TodoWrite", raw))

    class Model:
        context_limit = 100000

        def for_handoff(self, max_tokens):
            return Client()

    result = await generate(Model(), sources, sources, TodoWriteTool().schema(),
                            AbortController(), account=usages.append)
    assert result.id == "shape-1"
    assert len(requests) == len(usages) == 2
    assert sources == before
    assert "unexpected" not in result.input and "unexpected" not in result.input["checkpoint"]


@pytest.mark.asyncio
@pytest.mark.parametrize("batches", [(4,), (12,), (64,), (65,), (40, 25)])
async def test_read_frames_use_remaining_total_allowance_without_smaller_batch_cap(batches):
    from copy import deepcopy
    from engine.abort import AbortController
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from memory.wsc_handoff_generation import MAX_READ_CALLS

    sources = [{"role": "user", "id": "spec", "content": "规范"}]
    original = deepcopy(sources)
    attempts, admitted_reads = [], []
    class Client:
        last_usage = None
        async def stream(self, messages, schemas, abort):
            attempts.append(deepcopy(messages))
            frame = len(attempts) - 1
            if frame < len(batches):
                for i in range(batches[frame]):
                    yield ModelChunk(kind="tool_use", tool_use=ToolUse(f"read-{frame}-{i}", "HandoffSource",
                        {"message_id": "spec", "offset": 0, "limit": 2}))
            else:
                receipts = messages[-batches[-1]:]
                assert all(row["role"] == "tool" and not row["content"][0]["is_error"] for row in receipts)
                yield ModelChunk(kind="tool_use", tool_use=ToolUse("accepted-state", "TodoWrite",
                    {"todos": [], "checkpoint": {"objective": "", "context_message_ids": ["spec"]}}))
    class Model:
        context_limit = 100000
        def for_handoff(self, max_tokens): return Client()
    async def invoke():
        return await generate(Model(), [{"role": "user", "content": "继续"}], sources,
            TodoWriteTool().schema(), AbortController(), account=lambda usage: None,
            admit_read=lambda: admitted_reads.append(True))
    if sum(batches) <= MAX_READ_CALLS:
        result = await invoke()
        assert result.id == "accepted-state" and len(admitted_reads) == sum(batches)
        assert len(attempts) == len(batches) + 1 and result.presentation["sources"][0]["complete"] is True
    else:
        error = "handoff_response_limit" if batches == (65,) else "handoff_recall_request_limit"
        with pytest.raises(ValueError, match=error):
            await invoke()
        assert len(admitted_reads) == (0 if batches == (65,) else 40)
    assert sources == original
