"""Bounded Flash execution probe using actual fixture files and product tools.

Selected fold boundaries exercise deterministic projection; this is neither a
production timing test nor a historical before/after comparison.
"""
import argparse
import json
import os
from pathlib import Path
import re
from unittest.mock import patch

from evals.wsc_drift_budget import Budget
from evals.wsc_execution_behavior import run_arm, seed
from evals.wsc_request_projection import arm


def run(output, key_file, max_turns=10, checkpoint_mode="committed"):
    keys = re.findall(r"sk-[A-Za-z0-9_-]{16,}", Path(key_file).read_text(encoding="utf-8-sig"))
    if len(keys) != 1:
        raise ValueError("key_file_format_ambiguous")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    previous = {name: os.environ.get(name) for name in (
        "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "XEYO_WSC_TASK_CONTINUITY")}
    os.environ.update(DEEPSEEK_API_KEY=keys[0], DEEPSEEK_BASE_URL="https://api.deepseek.com")
    from evals.client import chat
    from model.deepseek import DeepSeekModelClient
    client = DeepSeekModelClient(api_key=keys[0], base_url="https://api.deepseek.com",
                                 model="deepseek-flash", thinking="disabled")
    budget = Budget(total=0.2 if checkpoint_mode == "generated" else 0.15)
    report = {"scope": "current implementation, actual file execution after selected folds; no threshold changes",
              "historical_ab": False, "live_files_modified": False, "checkpoint_mode": checkpoint_mode}

    def probe_seed(root):
        rows, records = seed(root)
        if checkpoint_mode in {"absent", "generated"}:
            # Remove exactly the initial successful state declaration, retaining
            # the same user specification, edits and verification failures.
            use = rows[-2]["content"][0]
            if use.get("type") != "tool_use" or use.get("name") != "TodoWrite":
                raise ValueError("fixture_checkpoint_boundary_changed")
            rows, records = rows[:-2], []
            if checkpoint_mode == "generated":
                import asyncio
                from engine.abort import AbortController
                from evals.wsc_flash_compact_chain import native_store
                from memory.working import WorkingSnapshot
                from memory.wsc_handoff_generation import generate
                from memory.wsc_handoff_transaction import commit
                from model.chunks import ModelChunk
                from msgtypes.message import ToolUse
                from session.compression_source import compression_messages
                from session.record_transcript import record_transcript_sync
                from synaptic.todo_snapshot import latest_todo_snapshot
                from tools.tool_registry import ToolRegistry
                from tools.todo_write_tool.todo_write_tool import TodoWriteTool
                store = native_store(rows)
                working = WorkingSnapshot(session_id="generated-handoff-fixture")
                registry = ToolRegistry(cwd=str(root))
                registry.register(TodoWriteTool(cwd=str(root)))
                source = lambda: compression_messages(store, working)
                class Limited:
                    last_usage = None
                    async def stream(self, messages, tools, abort):
                        wire = bounded_chat(messages, tools=tools, _handoff=True, capture_wire=True)
                        (root / "handoff-wire.json").write_text(json.dumps(wire, ensure_ascii=False, indent=2), encoding="utf-8")
                        self.last_usage = wire["response"].get("usage")
                        response = wire["response"]["choices"][0]["message"]
                        if response.get("content"):
                            yield ModelChunk(kind="text_delta", text=response["content"])
                        for call in response.get("tool_calls") or []:
                            fn = call["function"]
                            yield ModelChunk(kind="tool_use", tool_use=ToolUse(call["id"], fn["name"], json.loads(fn["arguments"])))
                class Model:
                    context_limit = 1_000_000
                    def for_handoff(self, max_tokens):
                        assert max_tokens == 2048
                        return Limited()
                usage = []
                async def generate_state(captured):
                    return await generate(Model(), captured, captured, registry.get("TodoWrite").schema(),
                                          AbortController(), account=usage.append)
                known = set()
                receipt = asyncio.run(commit(source=source, generate=generate_state, store=store,
                    tools=registry, abort=AbortController(), persist=lambda: record_transcript_sync(
                        store.items, session_id=working.session_id, path=root / "handoff-transcript.jsonl", known_ids=known)))
                report["generated_handoff"] = {"commit": receipt, "usage": usage, "state": latest_todo_snapshot(source()).checkpoint}
                return source(), list(latest_todo_snapshot(source()).records)
            return rows, records
        return rows, records

    def bounded_chat(messages, **kwargs):
        limit = 2048 if kwargs.pop("_handoff", False) else 700
        kwargs.update(model="deepseek-flash", max_tokens=limit, thinking="disabled", retries=0)
        body = client._build_body(messages, kwargs["tools"], stream=False)
        entry = budget.admit(body, limit)
        wire = chat(messages, **kwargs)
        budget.settle(entry, wire["response"].get("usage"))
        return wire

    try:
        with arm("1", output / "home"), patch("evals.client.chat", side_effect=bounded_chat), \
                patch("evals.wsc_execution_behavior.seed", side_effect=probe_seed):
            report["execution"] = run_arm(output / "task", "1", model="deepseek-flash", max_turns=max_turns)
    except Exception as exc:
        # Preserve partial wire/trace and reserved unknown cost, without keys.
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc).replace(keys[0], "[redacted]")
    finally:
        report["cost"] = {"peak_cny_upper": budget.spent_upper, "requests": budget.entries}
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    print(json.dumps({"acceptance": report.get("execution", {}).get("acceptance"),
                      "error": report.get("error_type"), "peak_cny_upper": budget.spent_upper}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument("--checkpoint-mode", choices=("committed", "absent", "generated"), default="committed")
    args = parser.parse_args()
    run(args.output, args.key_file, args.max_turns, args.checkpoint_mode)
