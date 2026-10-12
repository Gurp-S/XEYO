"""Real delivered-report -> model declaration -> two folds and disk recovery.

The report is a captured model answer, not operator-written completion text.
All state publication and compaction occurs in a new offline copy.
"""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re

from evals.wsc_drift_budget import Budget
from evals.wsc_unfolded_source_ab import environment


async def run(session, delivered, output, key_file, artifact_cwd):
    from engine.abort import AbortController
    from evals.client import chat
    from memory.wsc_handoff_generation import generate
    from memory.wsc_handoff_transaction import commit
    from memory.runtime import force_compact, project_for_model
    from memory.working import WorkingSnapshot, flush, hydrate
    from memory import wsc_projection
    from model.chunks import ModelChunk
    from model.deepseek import DeepSeekModelClient
    from msgtypes.message import Message, ToolUse
    from session.compression_source import compression_messages
    from session.hydrate import messages_from_rows
    from session.message_store import MessageStore
    from session.record_transcript import load_transcript, record_transcript_sync
    from session.surface import fold_surface_rows
    from session.transcript_blobs import resolve_transcript_rows
    from synaptic.todo_snapshot import latest_todo_snapshot
    from tools.tool_registry import ToolRegistry
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool

    original, delivered_bytes = session.read_bytes(), delivered.read_bytes()
    answer_record = json.loads(delivered_bytes)
    answer = answer_record["requests"][-1]["response"]["choices"][0]["message"].get("content")
    if not answer or answer != answer_record["answer"]:
        raise ValueError("cycle_delivered_answer_mismatch")
    keys = re.findall(r"sk-[A-Za-z0-9_-]{16,}", key_file.read_text(encoding="utf-8-sig"))
    if len(keys) != 1: raise ValueError("key_file_format_ambiguous")
    key, budget, captures = keys[0], Budget(total=0.25), []
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with environment(output):
        os.environ["XEYO_WSC"] = "1"
        os.environ["DEEPSEEK_API_KEY"] = key
        rows = resolve_transcript_rows(fold_surface_rows(load_transcript(session)), session)
        store = MessageStore(messages_from_rows(rows))
        working = WorkingSnapshot(session_id="report-cycle")
        source = lambda: compression_messages(store, working)
        before = deepcopy(source())
        first = force_compact(source(), working, cwd=output)
        first_cursor = working.compact_cursor
        store.append(Message(role="assistant", id="delivered-report", content=answer))
        initial = project_for_model(source(), working, cwd=output)
        append_prefix_stable = initial[0] == first[0]
        provider = DeepSeekModelClient(api_key=key, base_url="https://api.deepseek.com", model="deepseek-flash", thinking="disabled")
        class Model:
            context_limit = 1_000_000
            last_usage = None
            def for_handoff(self, max_tokens): return self
            def context_input(self, messages, tools):
                body = provider._build_body(messages, tools, stream=False)
                return {"messages": body["messages"], "tools": body.get("tools", [])}
            async def stream(self, messages, tools, abort):
                body = provider._build_body(messages, tools, stream=False)
                encoded = json.dumps(body, ensure_ascii=False)
                if key in encoded or re.search(r"sk-[A-Za-z0-9_-]{24,}", encoded):
                    raise ValueError("probe_sensitive_source")
                entry = budget.admit(body, 2048)
                wire = await asyncio.to_thread(chat, messages, tools=tools, model="deepseek-flash", thinking="disabled",
                    max_tokens=2048, temperature=0, timeout=50, retries=0, capture_wire=True)
                self.last_usage = wire["response"].get("usage")
                budget.settle(entry, self.last_usage)
                captures.append(wire)
                message = wire["response"]["choices"][0]["message"]
                for call in message.get("tool_calls") or []:
                    fn = call["function"]
                    yield ModelChunk(kind="tool_use", tool_use=ToolUse(call["id"], fn["name"], json.loads(fn["arguments"])))
        tools = ToolRegistry(cwd=str(output))
        tools.register(TodoWriteTool(cwd=str(artifact_cwd.resolve())))
        path, known = output / "transcript.jsonl", set()
        def persist():
            record_transcript_sync(store.items, session_id=working.session_id, path=path, known_ids=known)
        persist()
        prefix = path.read_bytes()
        async def declaration(captured):
            return await generate(Model(), initial, captured, TodoWriteTool().schema(), AbortController(),
                                  account=lambda usage: None, scope_protocol=True, recent_text_sources=True)
        error, receipt = None, None
        try:
            receipt = await commit(source=source, generate=declaration, store=store, tools=tools,
                                   abort=AbortController(), persist=persist)
        except Exception as exc:
            error = type(exc).__name__ if key in str(exc) else str(exc)
        snapshot = latest_todo_snapshot(source())
        cycles = []
        if receipt:
            second = force_compact(source(), working, cwd=output)
            flush(working.session_id, working)
            wsc_projection._STATE.clear()
            restored_working = hydrate(working.session_id, source_layout=working.compression_source_layout)
            restored_rows = resolve_transcript_rows(fold_surface_rows(load_transcript(path)), path)
            restored_store = MessageStore(messages_from_rows(restored_rows))
            recovered = compression_messages(restored_store, restored_working)
            emitted = project_for_model(recovered, restored_working, cwd=output)
            cycles.append({"channel": "native", "first_cursor": first_cursor, "second_cursor": working.compact_cursor,
                "cursor_advanced": working.compact_cursor > first_cursor,
                "disk_recovery_head_equal": emitted[0] == second[0],
                "checkpoint_recovered": latest_todo_snapshot(recovered).checkpoint == snapshot.checkpoint})
            (output / "second-head.txt").write_text(str(second[0]["content"]), encoding="utf-8")
            (output / "recovered-head.txt").write_text(str(emitted[0]["content"]), encoding="utf-8")
        report = {"scope": __doc__, "source_session": str(session.resolve()),
            "original_sha256": hashlib.sha256(original).hexdigest(), "source_unchanged": session.read_bytes() == original,
            "delivered_record_unchanged": delivered.read_bytes() == delivered_bytes,
            "source_prefix_unchanged": source()[:len(before)] == before,
            "transcript_prefix_unchanged": path.read_bytes().startswith(prefix),
            "append_prefix_stable": append_prefix_stable, "commit": receipt, "error": error,
            "requests": captures, "cost_upper": budget.spent_upper, "budget_entries": budget.entries,
            "latest_records": list(snapshot.records), "latest_checkpoint": snapshot.checkpoint, "cycles": cycles,
            "acceptance": "Requires semantic inspection; task status is declared, not execution proof."}
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: report[k] for k in ("commit", "error", "cost_upper", "cycles", "source_unchanged")}), flush=True)
        return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--session", type=Path, required=True)
    p.add_argument("--delivered", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--key-file", type=Path, required=True)
    p.add_argument("--artifact-cwd", type=Path, required=True)
    args = p.parse_args()
    asyncio.run(run(args.session, args.delivered, args.output, args.key_file, args.artifact_cwd))
