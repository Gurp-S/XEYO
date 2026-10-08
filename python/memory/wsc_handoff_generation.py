"""A bounded, dedicated model declaration request; no task tools execute here."""
from copy import copy, deepcopy
import json

from memory.wsc_timing import request_measure

OUTPUT_TOKENS = 2048
MAX_RESPONSE_BYTES = 48_000
MAX_REQUESTS = 4
MAX_RECALL_BYTES = 48_000
REQUEST = (
    "生成本次压缩前的结构化任务交接，使用 TodoWrite 完整状态声明。"
    "包含当前目标、稳定步骤ID及未完成步骤、决定、约束、规范消息ID和验收调用ID。"
    "进度是声明，执行结果以原回执为准；历史提及不等于当前目标。"
    "无当前任务时提交空清单与空目标。此请求只生成交接，不执行原任务。"
    "交接工具为 TodoWrite，输入对象包含 todos 和 checkpoint；checkpoint 是参数字段。"
    "decisions/constraints 是原任务来源的精确引用对象 {source_message_id, quote}。"
    "HandoffSource返回来源消息的精确字符范围，message_id来自来源身份表。"
    "HandoffCatalog返回分页来源目录，可按角色及原文的字面查询筛选。"
)


def source_schema(schema, sources, catalog=None):
    """Separate citation namespaces structurally; IDs are supplied facts."""
    from memory.wsc_handoff_catalog import Catalog, INITIAL_RECORDS
    catalog = catalog or Catalog(sources)
    identities = catalog.initial()
    message_ids, verification_ids = catalog.unique_ids, catalog.verification_ids
    bounded_enums = len(sources) <= INITIAL_RECORDS
    constrained = deepcopy(schema)
    constrained["description"] = "Stores a complete task declaration in one object containing todos and checkpoint. Progress is declared; verification references identify observed tool invocations."
    constrained["input_schema"]["required"] = ["todos", "checkpoint"]
    constrained["input_schema"]["additionalProperties"] = False
    properties = constrained["input_schema"]["properties"]["checkpoint"]["properties"]
    for field, values, description in (
        ("context_message_ids", message_ids, "Source message identities (message_id namespace)."),
        ("verification_call_ids", verification_ids, "Observed tool invocation identities (tool_call_ids namespace).")):
        properties[field] = {"type": "array", "maxItems": min(16, len(values)),
                             "description": description, "items": {"type": "string"}}
        if values and bounded_enums: properties[field]["items"]["enum"] = values
    from memory.wsc_handoff_facts import source_text, committed_facts
    declarations = committed_facts(sources)
    unique_ids = set(message_ids)
    fact_ids = [str(row.get("message_id") or row.get("id")) for row in sources
                if source_text(row) is not None and str(row.get("message_id") or row.get("id")) in unique_ids]
    fact_ids.extend(uid for uid in declarations if uid not in fact_ids)
    for field in ("decisions", "constraints"):
        identity_schema = {"type": "string"}
        if fact_ids and bounded_enums: identity_schema["enum"] = fact_ids
        properties[field] = {"type": "array", "maxItems": 16 if fact_ids else 0,
            "description": "Exact quotes from task text or whole values from the same field of the latest active committed_task_fields; source message identities identify provenance.",
            "items": {"type": "object", "properties": {
                "source_message_id": identity_schema, "quote": {"type": "string", "minLength": 1}},
                "required": ["source_message_id", "quote"], "additionalProperties": False}}
    return constrained, identities


def limited_client(model):
    custom = getattr(model, "for_handoff", None)
    if callable(custom):
        return custom(max_tokens=OUTPUT_TOKENS)
    from model.deepseek import DeepSeekModelClient
    from model.openai_compat import OpenAICompatClient
    from model.anthropic import AnthropicModelClient
    if not isinstance(model, (DeepSeekModelClient, OpenAICompatClient, AnthropicModelClient)):
        raise ValueError("handoff_output_limit_unavailable")
    client = copy(model)
    client._max_tokens = OUTPUT_TOKENS
    client.last_usage = None
    return client


async def generate(model, messages, sources, schema, abort, *, account, admit_next=None, admit_read=None):
    client = limited_client(model)
    request = deepcopy(messages)
    # Provider converters omit side IDs; publish the identity map explicitly in
    # this dedicated request, without changing any main request/frozen prefix.
    from memory.wsc_handoff_catalog import Catalog, NAME as CATALOG_NAME, schema as catalog_schema
    catalog = Catalog(sources)
    schema, identities = source_schema(schema, sources, catalog)
    request.append({"role": "user", "content": REQUEST + "\n来源身份=" + json.dumps(identities, ensure_ascii=False)
                    + "\n来源总数=" + str(len(sources))})
    from memory.wsc_handoff_recall import NAME, schema as recall_schema, read
    from synaptic.textutil import tool_use_blocks
    tools = [schema, recall_schema(), catalog_schema()]
    seen = {block.get("id") for row in sources for block in tool_use_blocks(row)}
    recalled_bytes = 0
    for attempt in range(MAX_REQUESTS):
        if abort.aborted:
            raise ValueError("handoff_cancelled")
        measurement = request_measure(request, tools, context_limit=getattr(model, "context_limit", None), model=client)
        capacity = getattr(model, "context_limit", None)
        if capacity and measurement.input_tokens + OUTPUT_TOKENS > capacity:
            raise ValueError("handoff_request_exceeds_capacity")
        if attempt and admit_next is not None:
            admit_next()
        uses, size = [], 0
        client.last_usage = None
        stream = client.stream(request, tools, abort)
        try:
            async for chunk in stream:
                size += len((chunk.text or "").encode("utf-8"))
                if chunk.kind == "tool_use" and chunk.tool_use:
                    uses.append(chunk.tool_use)
                    size += len(json.dumps(chunk.tool_use.input, ensure_ascii=False).encode("utf-8"))
                if size > MAX_RESPONSE_BYTES or len(uses) > 1:
                    raise ValueError("handoff_response_limit")
        finally:
            await stream.aclose()
            account(getattr(client, "last_usage", None))
        if len(uses) != 1:
            raise ValueError("handoff_declaration_missing")
        use = uses[0]
        if not isinstance(use.id, str) or not use.id or use.id in seen:
            raise ValueError("handoff_call_identity_conflict")
        seen.add(use.id)
        if use.name == "TodoWrite":
            from memory.wsc_handoff_facts import validate_facts
            validate_facts(use.input, sources, require_citations=True)
            return use
        if use.name not in {NAME, CATALOG_NAME}:
            raise ValueError("handoff_invalid_call")
        if attempt == MAX_REQUESTS - 1:
            raise ValueError("handoff_recall_request_limit")
        if admit_read is not None:
            admit_read()
        value = read(use.input, sources) if use.name == NAME else catalog.read(use.input)
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        recalled_bytes += len(payload.encode("utf-8"))
        if recalled_bytes > MAX_RECALL_BYTES:
            raise ValueError("handoff_recall_byte_limit")
        request.extend([{"role": "assistant", "content": [{"type": "tool_use", "id": use.id,
            "name": use.name, "input": use.input}]}, {"role": "tool", "tool_call_id": use.id,
            "name": use.name, "content": [{"type": "tool_result", "tool_use_id": use.id,
            "content": payload, "is_error": False}]}])
