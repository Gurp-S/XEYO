"""A bounded, dedicated model declaration request; no task tools execute here."""
from copy import copy, deepcopy
import json

from memory.wsc_handoff_schema import source_schema
from memory.wsc_timing import request_measure

OUTPUT_TOKENS = 2048
MAX_RESPONSE_BYTES = 48_000
# A cold handoff may traverse directory -> source -> evidence before committing.
# These ceilings are independent of the authoritative per-call budget admission.
MAX_REQUESTS = 6
# Context citations retain their 16-item cap; verification identities share
# the checkpoint byte budget. Recall remains independently bounded.
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


def limited_client(model, max_tokens=OUTPUT_TOKENS):
    custom = getattr(model, "for_handoff", None)
    if callable(custom):
        return custom(max_tokens=max_tokens)
    from model.deepseek import DeepSeekModelClient
    from model.openai_compat import OpenAICompatClient
    from model.anthropic import AnthropicModelClient
    if not isinstance(model, (DeepSeekModelClient, OpenAICompatClient, AnthropicModelClient)):
        raise ValueError("handoff_output_limit_unavailable")
    client = copy(model)
    client._max_tokens = max_tokens
    client.last_usage = None
    return client


async def generate(model, messages, sources, schema, abort, *, account, admit_next=None, admit_read=None, scope_protocol=False, recent_text_sources=False):
    from memory.wsc_handoff_output_budget import reservation
    output_tokens = reservation(sources)
    client = limited_client(model, output_tokens)
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
    from memory.wsc_handoff_control import messages as control_messages
    request.extend(control_messages(identities, len(sources)))
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
            return measured.input_tokens + output_tokens <= capacity
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
            return measured.input_tokens + output_tokens <= capacity
        recent = recent_materialize(sources, admit=admit_recent if capacity else None)
        request[-1]["content"] = recent_base + "\n近期原文证据（未声明为当前权威）=" + json.dumps(recent, ensure_ascii=False)
    from memory.wsc_handoff_delta import materialize as delta_materialize
    delta_base = request[-1]["content"]
    capacity = getattr(model, "context_limit", None)
    def delta_content(value):
        return delta_base + "\n提交后的来源增量=" + json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    def admit_delta(value):
        request[-1]["content"] = delta_content(value)
        measured = request_measure(request, tools, context_limit=capacity, model=client)
        return measured.input_tokens + output_tokens <= capacity
    delta = delta_materialize(sources, admit=admit_delta if capacity else None)
    request[-1]["content"] = delta_base if delta is None else delta_content(delta)
    from memory.wsc_handoff_anchors import materialize as anchor_materialize
    presented_ids = {row["message_id"] for row in workset["sources"] + recent["sources"]
                     + (delta["sources"] if delta else [])}
    for source in sources:
        identity = str(source.get("message_id") or source.get("id") or "")
        text = coverage.texts.get(identity)
        if text is not None and any(row.get("role") == source.get("role") and row.get("content") == text for row in messages):
            presented_ids.add(identity)
    anchor_base = request[-1]["content"]
    def anchor_content(value):
        return anchor_base + "\n已提交事实的原始来源=" + json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    def admit_anchor(value):
        request[-1]["content"] = anchor_content(value)
        measured = request_measure(request, tools, context_limit=capacity, model=client)
        return measured.input_tokens + output_tokens <= capacity
    anchors = anchor_materialize(sources, presented_ids=presented_ids, admit=admit_anchor if capacity else None)
    request[-1]["content"] = anchor_base if anchors is None else anchor_content(anchors)
    presented_ids.update(row["message_id"] for row in (anchors or {}).get("sources", []))
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
        if capacity and measurement.input_tokens + output_tokens > capacity:
            raise ValueError("handoff_request_exceeds_capacity")
        if attempt and admit_next is not None:
            admit_next()
        from memory.wsc_handoff_frame import HandoffFrame
        frame = HandoffFrame()
        uses, size = [], 0
        client.last_usage = None
        # Only admitted requests count as presentation. A tool result prepared
        # locally but never sent cannot prove the model received its contents.
        if attempt == 0:
            for identity in presented_ids:
                coverage.full(identity)
        for value in pending_source_results:
            coverage.source_result(value)
        pending_source_results.clear()
        stream = client.stream(request, tools, abort)
        from model.output_exhaustion import OutputLimitError
        exhausted = None
        try:
            async for chunk in stream:
                frame.observe(chunk)
                size += len((chunk.text or "").encode("utf-8"))
                if chunk.kind == "tool_use" and chunk.tool_use:
                    uses.append(chunk.tool_use)
                    size += len(json.dumps(chunk.tool_use.input, ensure_ascii=False).encode("utf-8"))
                if size > MAX_RESPONSE_BYTES or len(uses) > MAX_READ_CALLS:
                    raise ValueError("handoff_response_limit")
        except OutputLimitError as exc:
            exhausted = exc
        finally:
            from memory.wsc_stream_cleanup import close_and_account
            await close_and_account(stream, client, account)
        if exhausted is not None:
            from memory.wsc_handoff_exhaustion import next_limit
            larger_output = next_limit(exhausted, output_tokens)
            if abort.aborted or larger_output is None or attempt == MAX_REQUESTS - 1:
                raise exhausted
            # No output from this incomplete frame entered request or storage.
            # Admission and usage remain owned by this one bounded loop.
            output_tokens = larger_output
            client = limited_client(model, output_tokens)
            counted_client = CountedInput(client, abort)
            continue
        if not uses:
            raise ValueError("handoff_declaration_missing")
        batch_ids = set()
        for use in uses:
            if not isinstance(use.id, str) or not use.id or use.id in seen or use.id in batch_ids:
                raise ValueError("handoff_call_identity_conflict")
            batch_ids.add(use.id)
        seen.update(batch_ids)
        from memory.wsc_handoff_batch import rejection as batch_rejection
        batch_error = batch_rejection(uses, {NAME, CATALOG_NAME})
        if batch_error is not None:
            if attempt == MAX_REQUESTS - 1:
                raise ValueError(batch_error['error'])
            from memory.wsc_handoff_feedback import rejected_frame
            request.extend(rejected_frame(uses, batch_error, assistant=frame.message(uses)))
            continue
        if any(use.name == "TodoWrite" for use in uses):
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
                from memory.wsc_handoff_scope_encoding import to_native
                native_input = to_native(use.input)
                validate_facts(native_input, sources, require_citations=True)
                validate(native_input, sources, require_phase=scope_protocol)
            except ValueError as exc:
                if (str(exc) not in {"handoff_invalid_json", "handoff_fact_quote_not_in_source", "handoff_fact_citation_required",
                                     "handoff_fact_source_not_unique_or_bound",
                                     "handoff_invalid_state", "handoff_invalid_fields", "handoff_full_state_required",
                                     "handoff_step_identity_invalid", "handoff_active_context_required",
                                     "handoff_phase_state_required", "handoff_phase_source_invalid", "handoff_phase_transition_source_missing",
                                     "handoff_fact_applicability_event_missing",
                                     "handoff_progress_source_missing",
                                     "handoff_verification_source_not_unique",
                                     "handoff_active_phase_verification_bindings_omitted",
                                     "handoff_bound_context_disposition_missing", "handoff_context_disposition_mismatch",
                                     "handoff_context_disposition_stale_base", "handoff_context_disposition_invalid"}
                        and not str(exc).startswith("handoff_task_fact_")
                        or attempt == MAX_REQUESTS - 1):
                    raise
                # This is an isolated rejected declaration, not a committed
                # TodoWrite receipt. The transaction sees only valid output.
                from memory.wsc_handoff_feedback import rejected_frame
                from memory.wsc_handoff_output_retry import expanded
                larger_output = expanded(str(exc), client.last_usage, output_tokens)
                if larger_output is not None:
                    output_tokens = larger_output
                    client = limited_client(model, output_tokens)
                    counted_client = CountedInput(client, abort)
                request.extend(rejected_frame([use], getattr(exc, "detail", {"error": str(exc)}),
                                              assistant=frame.message([use])))
                continue
            return PresentedHandoff(use.id, use.name, native_input,
                                    coverage.record([*native_input["checkpoint"].get("context_message_ids", []),
                                        *[row["message_id"] for row in (anchors or {}).get("sources", [])],
                                        *(anchors or {}).get("deferred_message_ids", [])]))
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
        request.append(frame.message(uses))
        request.extend(results)
