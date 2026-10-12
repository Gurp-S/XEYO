"""A bounded, dedicated model declaration request; no task tools execute here."""
from copy import copy, deepcopy
import json

from memory.wsc_timing import request_measure

OUTPUT_TOKENS = 2048
MAX_RESPONSE_BYTES = 48_000
# A cold handoff may traverse directory -> source -> evidence before committing.
# These ceilings are independent of the authoritative per-call budget admission.
MAX_REQUESTS = 6
# Up to 16 bound context sources and 16 verification identities can be
# declared. Allow directory traversal and source/evidence reads for both sets.
MAX_READ_CALLS = 64
# A frame can use the entire remaining read allowance; no smaller batch cap.
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


def source_schema(schema, sources, catalog=None, *, scope_protocol=False):
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
    # Citation provenance is mandatory even when the optional phase protocol
    # supplies an additional active-context list. The two have distinct roles.
    constrained["input_schema"]["properties"]["checkpoint"]["required"] = ["context_message_ids"]
    from memory.wsc_handoff_fact_disposition import basis as fact_basis, schema as disposition_schema
    prior_facts = fact_basis(sources)
    from memory.wsc_handoff_bindings import basis
    prior = basis(sources)
    if scope_protocol or prior_facts is not None or (prior or {}).get('phase_state') is not None:
        from synaptic.task_phase import schema as phase_schema
        constrained["input_schema"]["properties"]["checkpoint"]["properties"]["phase_state"] = phase_schema()
        if prior_facts is not None:
            constrained["input_schema"]["properties"]["fact_disposition"] = disposition_schema()
            constrained["description"] += " Previous declared task-wide facts=" + json.dumps(prior_facts, ensure_ascii=False)
        constrained["input_schema"]["allOf"] = [{"if": {"properties": {"todos": {"contains": {
            "properties": {"status": {"enum": ["pending", "in_progress"]}}, "required": ["status"]}}}},
            "then": {"properties": {"checkpoint": {"required": ["phase_state"]}}}}]
    if prior is not None:
        constrained["input_schema"]["properties"]["context_disposition"] = {
            "type": "object", "description": "Explicit disposition of previously committed context identities omitted from this active declaration.",
            "properties": {"base_checkpoint_message_id": {"type": "string"},
                "retired_context_message_ids": {"type": "array", "maxItems": 16, "items": {"type": "string"}}},
            "required": ["base_checkpoint_message_id", "retired_context_message_ids"], "additionalProperties": False}
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


async def generate(model, messages, sources, schema, abort, *, account, admit_next=None, admit_read=None, scope_protocol=False, recent_text_sources=False):
    client = limited_client(model)
    request = deepcopy(messages)
    from memory.wsc_handoff_coverage import Coverage, PresentedHandoff
    coverage = Coverage(sources)
    workset = {"sources": []}
    recent = {"sources": []}
    pending_source_results = []
    # Provider converters omit side IDs; publish the identity map explicitly in
    # this dedicated request, without changing any main request/frozen prefix.
    from memory.wsc_handoff_catalog import Catalog, NAME as CATALOG_NAME, schema as catalog_schema
    catalog = Catalog(sources)
    schema, identities = source_schema(schema, sources, catalog, scope_protocol=scope_protocol)
    request.append({"role": "user", "content": REQUEST + "\n来源身份=" + json.dumps(identities, ensure_ascii=False)
                    + "\n来源总数=" + str(len(sources))})
    from memory.wsc_handoff_bindings import basis
    prior = basis(sources)
    if prior is not None:
        request[-1]["content"] += "\n已提交上下文绑定=" + json.dumps(prior, ensure_ascii=False)
    from memory.wsc_handoff_recall import NAME, schema as recall_schema, read
    from synaptic.textutil import tool_use_blocks
    tools = [schema, recall_schema(), catalog_schema()]
    if prior is not None:
        from memory.wsc_handoff_workset import materialize
        base_content = request[-1]["content"]
        capacity = getattr(model, "context_limit", None)
        def admit_workset(records, deferred):
            value = {"sources": records, "deferred_message_ids": deferred}
            request[-1]["content"] = base_content + "\n已绑定任务来源原文=" + json.dumps(value, ensure_ascii=False)
            measured = request_measure(request, tools, context_limit=capacity, model=client)
            return measured.input_tokens + OUTPUT_TOKENS <= capacity
        workset = materialize(sources, admit=admit_workset if capacity else None)
        request[-1]["content"] = base_content + "\n已绑定任务来源原文=" + json.dumps(workset, ensure_ascii=False)
    if recent_text_sources:
        from memory.wsc_handoff_recent import materialize as recent_materialize
        recent_base = request[-1]["content"]
        capacity = getattr(model, "context_limit", None)
        def admit_recent(records, deferred):
            request[-1]["content"] = recent_base + "\n近期原文证据（未声明为当前权威）=" + json.dumps(
                {"sources": records, "deferred_message_ids": deferred}, ensure_ascii=False)
            measured = request_measure(request, tools, context_limit=capacity, model=client)
            return measured.input_tokens + OUTPUT_TOKENS <= capacity
        recent = recent_materialize(sources, admit=admit_recent if capacity else None)
        request[-1]["content"] = recent_base + "\n近期原文证据（未声明为当前权威）=" + json.dumps(recent, ensure_ascii=False)
    from memory.wsc_counted_input import CountedInput
    counted_client = CountedInput(client, abort)
    seen = {block.get("id") for row in sources for block in tool_use_blocks(row)}
    recalled_bytes = 0
    read_calls = 0
    for attempt in range(MAX_REQUESTS):
        if abort.aborted:
            raise ValueError("handoff_cancelled")
        from session.late_result_guard import request_conflict
        sequence_error = request_conflict(request)
        if sequence_error is not None:
            raise ValueError(sequence_error)
        await counted_client.prime(request, tools)
        measurement = request_measure(request, tools, context_limit=getattr(model, "context_limit", None), model=counted_client)
        capacity = getattr(model, "context_limit", None)
        if capacity and measurement.input_tokens + OUTPUT_TOKENS > capacity:
            raise ValueError("handoff_request_exceeds_capacity")
        if attempt and admit_next is not None:
            admit_next()
        uses, size = [], 0
        client.last_usage = None
        # Only admitted requests count as presentation. A tool result prepared
        # locally but never sent cannot prove the model received its contents.
        if attempt == 0:
            for record in workset["sources"] + recent["sources"]:
                coverage.full(record["message_id"])
            for source in sources:
                identity = str(source.get("message_id") or source.get("id") or "")
                text = coverage.texts.get(identity)
                if text is not None and any(row.get("role") == source.get("role")
                                             and row.get("content") == text for row in messages):
                    coverage.full(identity)
        for value in pending_source_results:
            coverage.source_result(value)
        pending_source_results.clear()
        stream = client.stream(request, tools, abort)
        try:
            async for chunk in stream:
                size += len((chunk.text or "").encode("utf-8"))
                if chunk.kind == "tool_use" and chunk.tool_use:
                    uses.append(chunk.tool_use)
                    size += len(json.dumps(chunk.tool_use.input, ensure_ascii=False).encode("utf-8"))
                if size > MAX_RESPONSE_BYTES or len(uses) > MAX_READ_CALLS:
                    raise ValueError("handoff_response_limit")
        finally:
            await stream.aclose()
            account(getattr(client, "last_usage", None))
        if not uses:
            raise ValueError("handoff_declaration_missing")
        batch_ids = set()
        for use in uses:
            if not isinstance(use.id, str) or not use.id or use.id in seen or use.id in batch_ids:
                raise ValueError("handoff_call_identity_conflict")
            batch_ids.add(use.id)
        seen.update(batch_ids)
        if any(use.name == "TodoWrite" for use in uses):
            if len(uses) != 1:
                raise ValueError("handoff_mixed_declaration")
            use = uses[0]
            from memory.wsc_handoff_facts import validate_facts
            from memory.wsc_handoff_validation import validate
            try:
                from memory.wsc_handoff_feedback import invalid_arguments
                argument_error = invalid_arguments(use.input)
                if argument_error is not None:
                    from memory.wsc_handoff_validation import StateError
                    raise StateError(argument_error['error'], **{
                        key: value for key, value in argument_error.items() if key != 'error'})
                validate_facts(use.input, sources, require_citations=True)
                validate(use.input, sources, require_phase=scope_protocol)
            except ValueError as exc:
                if (str(exc) not in {"handoff_invalid_json", "handoff_fact_quote_not_in_source", "handoff_fact_citation_required",
                                     "handoff_fact_source_not_unique_or_bound",
                                     "handoff_invalid_state", "handoff_invalid_fields",
                                     "handoff_phase_state_required", "handoff_phase_source_invalid", "handoff_phase_transition_source_missing",
                                     "handoff_fact_applicability_event_missing",
                                     "handoff_progress_source_missing",
                                     "handoff_bound_context_disposition_missing", "handoff_context_disposition_mismatch",
                                     "handoff_context_disposition_stale_base", "handoff_context_disposition_invalid"}
                        and not str(exc).startswith("handoff_task_fact_")
                        or attempt == MAX_REQUESTS - 1):
                    raise
                # This is an isolated rejected declaration, not a committed
                # TodoWrite receipt. The transaction sees only valid output.
                from memory.wsc_handoff_feedback import rejected_frame
                request.extend(rejected_frame([use], getattr(exc, "detail", {"error": str(exc)})))
                continue
            return PresentedHandoff(use.id, use.name, use.input,
                                    coverage.record(use.input["checkpoint"].get("context_message_ids", [])))
        if any(use.name not in {NAME, CATALOG_NAME} for use in uses):
            raise ValueError("handoff_invalid_call")
        if attempt == MAX_REQUESTS - 1:
            raise ValueError("handoff_recall_request_limit")
        if read_calls + len(uses) > MAX_READ_CALLS:
            raise ValueError("handoff_recall_request_limit")
        results = []
        for use in uses:
            if admit_read is not None:
                admit_read()
            read_calls += 1
            error = False
            try:
                value = read(use.input, sources) if use.name == NAME else catalog.read(use.input)
            except ValueError as exc:
                if str(exc) not in {"handoff_source_invalid_arguments", "handoff_source_not_unique",
                                    "handoff_catalog_invalid_arguments", "handoff_catalog_record_too_large"}:
                    raise
                error = True
                value = {"error": str(exc), "tool": use.name, "argument_keys": sorted(use.input) if isinstance(use.input, dict) else None}
            if use.name == NAME and not error:
                pending_source_results.append(value)
            payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            recalled_bytes += len(payload.encode("utf-8"))
            if recalled_bytes > MAX_RECALL_BYTES:
                raise ValueError("handoff_recall_byte_limit")
            results.append({"role": "tool", "tool_call_id": use.id,
                "name": use.name, "content": [{"type": "tool_result", "tool_use_id": use.id,
                "content": payload, "is_error": error}]})
        request.append({"role": "assistant", "content": [{"type": "tool_use", "id": use.id,
            "name": use.name, "input": use.input} for use in uses]})
        request.extend(results)
