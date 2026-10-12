"""Real archived-source handoff recovery probe; no edits to the original session.

This selects an offline cold boundary. It is not the full unfurled pre-fold
request or an 85% query-loop test. The same original rows remain available to
the isolated source tools and the actual TodoWrite transaction.
"""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from evals.wsc_drift_budget import Budget


async def run(session, boundary, output, key_file, total_budget, surface, *, scope_protocol=False, recent_text_sources=False):
    from engine.abort import AbortController
    from evals.client import chat
    from evals.wsc_catalog_behavior import environment
    from memory.wsc_handoff_generation import generate
    from memory.wsc_handoff_transaction import commit
    from memory.wsc_projection import production_params
    from memory.working import WorkingSnapshot
    from memory.runtime import force_compact
    from model.chunks import ModelChunk
    from model.deepseek import DeepSeekModelClient
    from msgtypes.message import ToolUse
    from session.compression_source import compression_messages
    from session.hydrate import messages_from_rows
    from session.message_store import MessageStore
    from session.surface import fold_surface_rows
    from session.record_transcript import record_transcript_sync
    from session.transcript_blobs import resolve_transcript_rows
    from synaptic.project import project
    from tools.tool_registry import ToolRegistry
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool

    output.mkdir(parents=True, exist_ok=True)
    original_bytes = session.read_bytes()
    original_hash = hashlib.sha256(original_bytes).hexdigest()
    raw = [json.loads(line) for line in original_bytes.decode("utf-8-sig").splitlines() if line.strip()]
    selected_raw = raw[:boundary]
    rows = resolve_transcript_rows(fold_surface_rows(selected_raw), session)
    if not rows or rows[-1].get("role") != "user":
        raise ValueError("probe_boundary_not_user_request")
    keys = re.findall(r"sk-[A-Za-z0-9_-]{16,}", key_file.read_text(encoding="utf-8-sig"))
    if len(keys) != 1:
        raise ValueError("key_file_format_ambiguous")
    key = keys[0]
    budget = Budget(total=total_budget)
    captures, usages = [], []
    with environment(output):
        store = MessageStore(messages_from_rows(rows))
        source = lambda: compression_messages(store, WorkingSnapshot())
        original_source = deepcopy(source())
        before = project(original_source, region_end=len(original_source), params=production_params(), view_path=output / "before.txt")
        if surface == "runtime":
            boundary_state = WorkingSnapshot(session_id="real-task-boundary")
            initial = force_compact(original_source, boundary_state, cwd=output)
            initial_head = initial[0]["content"]
        else:
            initial = [{"role": "assistant", "content": before.text},
                       {"role": "user", "content": rows[-1]["content"]}]
            initial_head = before.text
        (output / "before-head.txt").write_text(initial_head, encoding="utf-8")
        provider = DeepSeekModelClient(api_key=key, base_url="https://api.deepseek.com", model="deepseek-flash", thinking="disabled")

        class Model:
            context_limit = 1_000_000
            last_usage = None
            def for_handoff(self, max_tokens):
                client = Model()
                client.max_tokens = max_tokens
                return client
            def context_input(self, messages, tools):
                body = provider._build_body(messages, tools, stream=False)
                return {"messages": body["messages"], "tools": body.get("tools", [])}
            async def stream(self, messages, tools, abort):
                body = provider._build_body(messages, tools, stream=False)
                serialized = json.dumps(body, ensure_ascii=False)
                # Captures never contain credentials, including archived keys.
                if key in serialized or re.search(r"sk-[A-Za-z0-9_-]{24,}", serialized):
                    raise ValueError("probe_sensitive_source")
                entry = budget.admit(body, self.max_tokens)
                wire = await asyncio.to_thread(chat, messages, tools=tools, model="deepseek-flash", max_tokens=self.max_tokens,
                    thinking="disabled", temperature=0, timeout=50, retries=0, capture_wire=True)
                self.last_usage = wire["response"].get("usage")
                budget.settle(entry, self.last_usage)
                captures.append(wire)
                response = wire["response"]["choices"][0]["message"]
                if response.get("content"):
                    yield ModelChunk(kind="text_delta", text=response["content"])
                for call in response.get("tool_calls") or []:
                    function = call["function"]
                    yield ModelChunk(kind="tool_use", tool_use=ToolUse(call["id"], function["name"], json.loads(function["arguments"])))

        tools = ToolRegistry(cwd=str(output))
        tools.register(TodoWriteTool(cwd=str(output)))
        known = set()
        path = output / "transcript.jsonl"
        def persist():
            record_transcript_sync(store.items, session_id="real-task-probe", path=path, known_ids=known)
        persist()
        prefix = path.read_bytes()
        error, receipt = None, None
        async def declaration(captured):
            return await generate(Model(), initial, captured, TodoWriteTool().schema(), AbortController(),
                                  account=usages.append, scope_protocol=scope_protocol, recent_text_sources=recent_text_sources)
        try:
            receipt = await commit(source=source, generate=declaration, store=store, tools=tools,
                                   abort=AbortController(), persist=persist)
        except Exception as exc:
            error = str(exc)
            if key in error:
                error = type(exc).__name__
        after = project(source(), region_end=len(source()), params=production_params(), view_path=output / "after.txt")
        (output / "after-head.txt").write_text(after.text, encoding="utf-8")
        # The full-history baseline is only measured for budget admission;
        # it is never truncated to make a cheaper passing control.
        full_body = provider._build_body(original_source, [TodoWriteTool().schema()], stream=False)
        full_bytes = len(json.dumps(full_body, ensure_ascii=False).encode("utf-8"))
        full_admission_upper = ((full_bytes + 8192) * 2 + 2048 * 8) / 1_000_000
        report = {"scope": __doc__, "source_session": str(session), "boundary_exclusive": boundary,
            "selected_storage_rows": len(selected_raw), "restored_source_rows": len(original_source),
            "initial_surface": surface,
            "scope_protocol": scope_protocol,
            "recent_text_sources": recent_text_sources,
            "original_sha256": original_hash, "original_unchanged": hashlib.sha256(session.read_bytes()).hexdigest() == original_hash,
            "source_prefix_unchanged": source()[:len(original_source)] == original_source,
            "offline_transcript_prefix_unchanged": path.read_bytes().startswith(prefix),
            "before_head_characters": len(initial_head), "after_head_characters": len(after.text),
            "real_commit": receipt, "error": error, "requests": captures, "usage": usages,
            "cost": {"peak_cny_upper": budget.spent_upper, "entries": budget.entries},
            "full_history_baseline": {"sent": False, "request_bytes": full_bytes,
                "admission_cny_upper": full_admission_upper,
                "within_per_call_limit": full_admission_upper <= budget.per_call},
            "completion_claim": "No semantic continuity score from a successful transaction alone."}
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"commit": receipt is not None, "error": error, "cost_upper": budget.spent_upper,
                          "original_unchanged": report["original_unchanged"]}, ensure_ascii=False))
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--boundary", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--total-budget", type=float, default=0.12)
    parser.add_argument("--surface", choices=["runtime", "fully_archived"], default="runtime")
    parser.add_argument("--scope-protocol", action="store_true")
    parser.add_argument("--recent-text-sources", action="store_true")
    args = parser.parse_args()
    if not 0 < args.total_budget <= 0.4:
        raise ValueError("probe_total_budget_invalid")
    asyncio.run(run(args.session, args.boundary, args.output, args.key_file, args.total_budget, args.surface,
                    scope_protocol=args.scope_protocol, recent_text_sources=args.recent_text_sources))
