import pytest

from memory.wsc_handoff_generation import limited_client, generate, OUTPUT_TOKENS
from tools.todo_write_tool.todo_write_tool import TodoWriteTool


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
