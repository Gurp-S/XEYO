"""Real Flash Compact invocation through the product query loop at low occupancy."""
import argparse
import asyncio
import importlib
import json
import os
from pathlib import Path
import re
import sys
from unittest.mock import patch

from evals.wsc_drift_budget import Budget
from evals.wsc_flash_drift import seed
from evals.wsc_unfolded_source_ab import environment


async def run(output, key_file):
    keys = re.findall(r"sk-[A-Za-z0-9_-]{16,}", Path(key_file).read_text(encoding="utf-8-sig"))
    if len(keys) != 1:
        raise ValueError("key_file_format_ambiguous")
    key = keys[0]
    os.environ["DEEPSEEK_API_KEY"] = key
    os.environ["DEEPSEEK_BASE_URL"] = "https://api.deepseek.com"
    from evals.client import chat
    from engine.abort import AbortController
    from engine.budget import BudgetTracker
    from engine.query_loop import query_loop
    from memory.working import WorkingSnapshot
    from model.chunks import ModelChunk
    from model.deepseek import DeepSeekModelClient
    from msgtypes.message import Message, ToolUse
    from prompt.assembler import PromptAssembler
    from session.message_store import MessageStore
    from tools.compact_tool import CompactTool
    from tools.tool_registry import ToolRegistry
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    from session.record_transcript import record_transcript_sync
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    with environment(output):
        os.environ["XEYO_WSC"] = "1"
        rows, _ = seed()
        rows[2]["content"] = "当前规范原文，request_code=7391"
        rows += [{"role": "assistant", "content": "已观察归档记录 " + str(i) + " abcdefghijklmnop" * 30} for i in range(18)]
        rows += [{"role": "user", "content": "测试流程：先调用Compact，然后继续当前任务，用JSON返回objective_id、step_id、decision、verification_id、verification_status。这是我的明确压缩请求。"}]
        store = native_store(rows)
        working = WorkingSnapshot(session_id="flash-compact-chain")
        registry = ToolRegistry(cwd=str(output))
        registry.register(CompactTool())
        registry.register(TodoWriteTool(cwd=str(output)))
        budget = Budget(total=0.15)
        captures, returned_calls = [], []
        client = DeepSeekModelClient(api_key=key, base_url="https://api.deepseek.com", model="deepseek-flash", thinking="disabled")

        class Model:
            context_limit = 1_000_000
            last_usage = {}
            purpose = "main"
            max_output = 500
            def for_handoff(self, max_tokens):
                bounded = Model()
                bounded.max_output = max_tokens
                bounded.purpose = "handoff"
                return bounded
            def context_input(self, messages, tools):
                body = client._build_body(messages, tools, stream=False)
                (output / "prepared-input.json").write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")
                return {"messages": body["messages"], "tools": body.get("tools", [])}

            async def stream(self, messages, tools, abort):
                body = client._build_body(messages, tools, stream=False)
                entry = budget.admit(body, self.max_output)
                cursor = working.compact_cursor
                admission = dict(working.wsc_timing_state.get("last_request_admission", {}))
                wire = await asyncio.to_thread(chat, messages, model="deepseek-flash", tools=tools,
                    max_tokens=self.max_output, thinking="disabled", temperature=0, timeout=50, retries=0, capture_wire=True)
                budget.settle(entry, wire["response"].get("usage"))
                self.last_usage = wire["response"].get("usage") or {}
                if key in json.dumps(wire):
                    raise RuntimeError("secret_in_capture")
                captures.append({"purpose": self.purpose, "cursor_before_send": cursor, "admission": admission, "wire": wire,
                                 "prepared_messages": messages})
                response = wire["response"]["choices"][0]["message"]
                if response.get("content"):
                    yield ModelChunk(kind="text_delta", text=response["content"])
                for call in response.get("tool_calls") or []:
                    fn = call["function"]
                    returned_calls.append({"id": call["id"], "name": fn["name"]})
                    yield ModelChunk(kind="tool_use", tool_use=ToolUse(id=call["id"], name=fn["name"], input=json.loads(fn["arguments"])))

        # Isolate filesystem/environment observations, not compression or tools.
        # The real query_loop/project/prepare/registry/receipt path remains in use.
        known_ids = set()
        with patch("engine.first_sniff.maybe_first_sniff_text", return_value=""), \
             patch("prompt.t_now_strategy.resolve_t_now_strategy", return_value="system_channel"), \
             patch.object(importlib.import_module("engine.query_loop"), "_attach_turn_context", side_effect=lambda messages, **kwargs: messages):
            async for _ in query_loop(store=store, model=Model(), tools=registry, prompt=PromptAssembler(),
                                      system_prompt="isolated fixture", abort=AbortController(),
                                      budget=BudgetTracker(max_turns=4), working=working,
                                      persist_handoff=lambda: record_transcript_sync(store.items,
                                          session_id=working.session_id, path=output / "transcript.jsonl", known_ids=known_ids)):
                pass
        final = captures[-1]["wire"]["response"]["choices"][0]["message"].get("content", "") if captures else ""
        answer = extract_answer(final)
        expected = {"objective_id": "BILL-27", "step_id": "verify", "decision": "decimal_half_even",
                    "verification_id": "v-new", "verification_status": "error"}
        main_captures = [capture for capture in captures if capture["purpose"] == "main"]
        first = main_captures[0] if main_captures else {}
        compact_ids = [c["id"] for c in returned_calls if c["name"] == "Compact"]
        checks = {"first_request_below_80": bool(first) and first["admission"]["before"]["input_tokens"] < 800000,
                  "first_request_not_folded": bool(first) and first["cursor_before_send"] == 0,
                  "real_model_called_compact": bool(compact_ids),
                  "success_receipt_handled": working.wsc_timing_state.get("handled_request") in compact_ids,
                  "second_request_after_real_fold": len(main_captures) >= 2 and main_captures[1]["cursor_before_send"] > 0,
                  "real_handoff_before_fold": any(c["purpose"] == "handoff" and c["cursor_before_send"] == 0 for c in captures),
                  "real_handoff_commit": bool(working.wsc_timing_state.get("last_handoff_commit")),
                  "no_capacity_forcing": all(c["admission"]["automatic_attempts"] == 0 for c in main_captures),
                  **{name: (answer.get(name) in {"error", "failed"} if name == "verification_status"
                            else answer.get(name) == value) for name, value in expected.items()}}
        report = {"scope": "real Compact tool/receipt/product-query-loop at short-task occupancy; no threshold changes",
                  "checks": checks, "answer": answer, "returned_calls": returned_calls,
                  "scoring": "Exactly one JSON object; verification failure accepts error or failed (no enum specified in user task). Raw response retained.",
                  "working_timing": working.wsc_timing_state, "requests": captures,
                  "cost": {"peak_cny_upper": budget.spent_upper, "requests": budget.entries}}
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"checks": checks, "peak_cny_upper": budget.spent_upper,
                          "input_tokens": [c["admission"]["before"]["input_tokens"] for c in captures],
                          "cursors": [c["cursor_before_send"] for c in captures]}, ensure_ascii=False))
        return report


def extract_answer(text):
    """Accept prose around JSON, reject ambiguous multiple answer objects."""
    answers = []
    decoder = json.JSONDecoder()
    position = 0
    while position < len(text):
        start = text.find("{", position)
        if start < 0:
            break
        try:
            value, length = decoder.raw_decode(text[start:])
        except ValueError:
            position = start + 1
            continue
        if isinstance(value, dict):
            answers.append(value)
        position = start + length
    return answers[0] if len(answers) == 1 else {}


def native_store(rows):
    """Use the native runtime receipt role, rather than provider wire syntax."""
    from msgtypes.message import Message
    from session.message_store import MessageStore
    messages = []
    for row in rows:
        content = row["content"]
        receipt = next((b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"), None) if isinstance(content, list) else None
        kwargs = {"id": row["id"]} if "id" in row else {}
        if receipt:
            kwargs["tool_call_id"] = receipt["tool_use_id"]
        messages.append(Message(role="tool" if receipt else row["role"], content=content, **kwargs))
    return MessageStore(messages)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--key-file", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.output, args.key_file))
