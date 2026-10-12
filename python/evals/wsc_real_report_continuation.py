"""Actual model reporting after force-compacting real offline handoff copies.

Read and optional Grep execute within private archives; explicitly selected
assets are read-only. This compares captured checkpoints, not randomized
live 85% runs or complete-history input.
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


def archive_search(args, folder, contexts=None):
    """Execute existing Grep only on a concrete generated archive view."""
    from engine.abort import AbortController
    from tools.grep_tool.grep_tool import GrepTool
    path = Path(args.get("path", ""))
    if not path.is_absolute():
        path = folder / path
    archive = (folder / ".xeyo_offload" / "wsc").resolve()
    if not path.resolve().is_relative_to(archive) or not path.is_file() or path.suffix != ".txt":
        return {"is_error": True, "content": "Permission denied: search path outside archive view"}
    result = asyncio.run(GrepTool(cwd=str(folder)).execute(args, AbortController()))
    context = (contexts or {}).get(str(path.resolve()))
    if not result.is_error and context and args.get("output_mode") == "content":
        from synaptic.archive_passages import passages, matched_lines
        text, sources = context
        if path.read_text(encoding="utf-8") == text:
            hits = matched_lines(result.content, path, folder)
            result.content = json.dumps({"grep_result": result.content, **passages(text, sources, hits)}, ensure_ascii=False)
    return {"is_error": result.is_error, "content": result.content}


def run(sessions, output, key_file, *, execute=False, artifact_cwd=None, resume=False, channel=None, cards_index=False, query=None, search=False, source_passages=False, cycle_recovery=False, receipt_binding=False, assembled=False):
    from evals.client import chat
    from evals.stale_goal_ab import tool_read
    from memory.runtime import force_compact
    from memory.working import WorkingSnapshot
    from model.deepseek import DeepSeekModelClient
    from session.record_transcript import load_transcript
    from session.transcript_blobs import resolve_transcript_rows
    from session.surface import fold_surface_rows
    from session.hydrate import messages_from_rows
    from session.message_store import MessageStore
    from session.compression_source import compression_messages
    from tools.file_read_tool.file_read_tool import FileReadTool

    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    key = None
    if execute:
        keys = re.findall(r"sk-[A-Za-z0-9_-]{16,}", key_file.read_text(encoding="utf-8-sig"))
        if len(keys) != 1: raise ValueError("key_file_format_ambiguous")
        key = keys[0]
    budget = Budget(total=0.4)
    arms = []
    artifact_hashes = {}
    if artifact_cwd is not None:
        for name in ("ab_off.txt", "ab_on.txt"):
            path = (artifact_cwd / ".xeyo" / name).resolve()
            if path.is_file(): artifact_hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()
    previous_key = os.environ.get("DEEPSEEK_API_KEY")
    if key: os.environ["DEEPSEEK_API_KEY"] = key
    try:
        for label, session in sessions:
            folder = output / label
            folder.mkdir()
            original = session.read_bytes()
            restored = resolve_transcript_rows(fold_surface_rows(load_transcript(session)), session)
            rows = compression_messages(MessageStore(messages_from_rows(restored)), WorkingSnapshot())
            with environment(folder):
                if channel is not None:
                    os.environ["XEYO_WSC"] = str(int(channel == "native"))
                os.environ["XEYO_WSC_CARD_INDEX_ONLY"] = str(int(cards_index))
                os.environ["XEYO_WSC_RECEIPT_SOURCE_BINDING"] = str(int(receipt_binding))
                replay = None
                if artifact_cwd is not None:
                    # Re-run only the captured declaration, not task execution.
                    # Output stat observes the explicitly selected real worktree.
                    from evals.wsc_flash_compact_chain import native_store
                    from memory.wsc_handoff_transaction import commit
                    from engine.abort import AbortController
                    from msgtypes.message import ToolUse
                    from synaptic.textutil import tool_use_blocks, tool_result_blocks
                    from tools.tool_registry import ToolRegistry
                    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
                    from session.record_transcript import record_transcript_sync
                    use = list(tool_use_blocks(rows[-2]))
                    result = list(tool_result_blocks(rows[-1]))
                    if len(use) != 1 or use[0]["name"] != "TodoWrite" or len(result) != 1:
                        raise ValueError("probe_last_declaration_missing")
                    store = native_store([dict(row, id=row["message_id"]) for row in rows[:-2]])
                    source = lambda: compression_messages(store, WorkingSnapshot())
                    prior_rows = deepcopy(source())
                    registry = ToolRegistry(cwd=str(folder))
                    registry.register(TodoWriteTool(cwd=str(artifact_cwd.resolve())))
                    async def declaration(captured):
                        return ToolUse(use[0]["id"], "TodoWrite", deepcopy(use[0]["input"]))
                    path, known = folder / "replayed.jsonl", set()
                    def persist():
                        record_transcript_sync(store.items, session_id="report-replay", path=path, known_ids=known)
                    replay = asyncio.run(commit(source=source, generate=declaration, store=store,
                                                 tools=registry, abort=AbortController(), persist=persist))
                    rows = source()
                    if rows[:len(prior_rows)] != prior_rows:
                        raise ValueError("probe_replay_prefix_changed")
                working = WorkingSnapshot(session_id="report-" + label)
                # Every output folder is a new offline generation. Live cache
                # identity is session-only, so cwd/env isolation is insufficient.
                from memory.wsc_projection import _STATE
                _STATE.pop(working.session_id, None)
                cycle = None
                if cycle_recovery:
                    from synaptic.todo_snapshot import latest_todo_snapshot
                    from memory.runtime import project_for_model
                    from memory.working import flush, hydrate
                    prior = latest_todo_snapshot(rows[:-2])
                    if not prior.observed or prior.checkpoint_source < 0:
                        raise ValueError("cycle_prior_checkpoint_missing")
                    first = force_compact(rows[:prior.checkpoint_source + 1], working, cwd=folder)
                    cursor = working.compact_cursor
                    appended = project_for_model(rows, working, cwd=folder, capacity_managed=True)
                    second = force_compact(rows, working, cwd=folder)
                    flush(working.session_id, working)
                    _STATE.pop(working.session_id, None)
                    restored = hydrate(working.session_id, source_layout=working.compression_source_layout)
                    request = project_for_model(rows, restored, cwd=folder, capacity_managed=True)
                    cycle = {"first_cursor": cursor, "second_cursor": working.compact_cursor,
                        "advanced": working.compact_cursor > cursor,
                        "append_prefix_equal": appended[0] == first[0],
                        "recovery_equal": request == second}
                    if not all(cycle[key] for key in ("advanced", "append_prefix_equal", "recovery_equal")):
                        raise ValueError("cycle_contract_failed")
                else:
                    request = force_compact(rows, working, cwd=folder)
                contexts = {}
                if source_passages:
                    from memory.wsc_projection import _STATE
                    from synaptic.archive_passages import source_ranges
                    for live in _STATE.values():
                        if live.view_path and Path(live.view_path).resolve().is_relative_to(folder):
                            contexts[str(Path(live.view_path).resolve())] = source_ranges(live.cold, rows)
                frozen = deepcopy(request[0])
                # The live boundary was 'continue'; the offline handoff itself
                # is not a new human objective.
                if query is not None or not resume:
                    request.append({"role": "user", "content": query if query is not None else "继续"})
                (folder / "input.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
                schema = FileReadTool(cwd=str(folder)).schema()
                schemas = [schema]
                if search:
                    from tools.grep_tool.grep_tool import GrepTool
                    schemas.append(GrepTool(cwd=str(folder)).schema())
                if assembled:
                    from prompt.assembler import PromptAssembler
                    assembler = PromptAssembler()
                    system, breakdown = asyncio.run(assembler.build_system_parts(
                        cwd=str(folder), model="deepseek-flash",
                        tool_names=[item["name"] for item in schemas]))
                    request = assembler.build(system, request)
                    (folder / "system-parts.json").write_text(json.dumps({
                        "system": system, "breakdown": breakdown}, ensure_ascii=False, indent=2), encoding="utf-8")
                    frozen_index = 1
                else:
                    frozen_index = 0
                calls, reads, answer, error = [], [], None, None
                provider = DeepSeekModelClient(api_key=key or "not-sent", base_url="https://api.deepseek.com",
                                               model="deepseek-flash", thinking="disabled")
                initial_body = provider._build_body(request, schemas, stream=False)
                if execute:
                    try:
                        for attempt in range(4):
                            body = provider._build_body(request, schemas, stream=False)
                            encoded = json.dumps(body, ensure_ascii=False)
                            if key in encoded or re.search(r"sk-[A-Za-z0-9_-]{24,}", encoded):
                                raise ValueError("probe_sensitive_source")
                            entry = budget.admit(body, 1800)
                            wire = chat(request, tools=schemas, model="deepseek-flash", thinking="disabled",
                                        max_tokens=1800, temperature=0, timeout=50, retries=0, capture_wire=True)
                            budget.settle(entry, wire["response"].get("usage"))
                            calls.append(wire)
                            message = wire["response"]["choices"][0]["message"]
                            uses = message.get("tool_calls") or []
                            if not uses:
                                answer = message.get("content") or ""
                                break
                            if len(uses) > 16: raise ValueError("probe_read_frame_limit")
                            blocks = [{"type": "text", "text": message["content"]}] if message.get("content") else []
                            for use in uses:
                                fn = use["function"]
                                args = json.loads(fn["arguments"])
                                blocks.append({"type": "tool_use", "id": use["id"], "name": fn["name"], "input": args})
                            request.append({"role": "assistant", "content": blocks})
                            for use in uses:
                                fn = use["function"]
                                args = json.loads(fn["arguments"])
                                path = Path(args.get("file_path", ""))
                                if not path.is_absolute(): path = folder / path
                                if search and fn["name"] == schemas[-1]["name"]:
                                    result = archive_search(args, folder, contexts)
                                elif fn["name"] != schema["name"]:
                                    result = {"is_error": True, "content": "Unknown tool: " + fn["name"]}
                                elif not path.resolve().is_relative_to(folder) and path.resolve() not in artifact_hashes:
                                    result = {"is_error": True, "content": "Permission denied: path outside archive"}
                                else:
                                    result = tool_read(args, artifact_cwd.resolve() if path.resolve() in artifact_hashes else folder)
                                if len(str(result["content"]).encode("utf-8")) > 48_000:
                                    result = {"is_error": True, "content": "archive_read_result_exceeds_capacity"}
                                reads.append({"call_id": use["id"], "name": fn["name"], "input": args, "result": result})
                                request.append({"role": "tool", "content": [{"type": "tool_result", "tool_use_id": use["id"],
                                                "content": result["content"], "is_error": result["is_error"]}]})
                    except Exception as exc:
                        error = type(exc).__name__ if key and key in str(exc) else str(exc)
                    if answer is None and error is None:
                        error = "probe_request_limit_without_final_answer"
                report = {"label": label, "session": str(session.resolve()), "source_rows": len(rows),
                    "cycle_recovery": cycle, "receipt_binding": receipt_binding,
                    "resume_without_new_user_message": resume and query is None,
                    "archive_search": search,
                    "source_passages": source_passages,
                    "source_passage_views": len(contexts),
                    "requested_channel": channel,
                    "cards_index": cards_index,
                    "probe_query": query,
                    "artifact_observation_cwd": str(artifact_cwd.resolve()) if artifact_cwd else None,
                    "declaration_replay": replay,
                    "source_sha256": hashlib.sha256(original).hexdigest(), "source_unchanged": session.read_bytes() == original,
                    "cursor_before_send": working.compact_cursor, "head_characters": len(str(frozen["content"])),
                    "frozen_prefix_unchanged": request[frozen_index] == frozen,
                    "assembled": assembled,
                    "input_bytes": len(json.dumps(initial_body, ensure_ascii=False).encode("utf-8")),
                    "requests": calls, "reads": reads, "answer": answer, "error": error}
                (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                if answer: (folder / "answer.md").write_text(answer, encoding="utf-8")
                arms.append(report)
                print(json.dumps({k: report[k] for k in ("label", "cursor_before_send", "head_characters", "source_unchanged", "error")}), flush=True)
    finally:
        if previous_key is None: os.environ.pop("DEEPSEEK_API_KEY", None)
        else: os.environ["DEEPSEEK_API_KEY"] = previous_key
    report = {"scope": __doc__, "executed": execute, "arms": [{k: a[k] for k in
        ("label", "cursor_before_send", "head_characters", "source_unchanged", "frozen_prefix_unchanged", "error")} for a in arms],
        "cost_upper": budget.spent_upper, "budget_entries": budget.entries,
        "selected_artifacts_unchanged": all(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == value
                                             for path, value in artifact_hashes.items()),
        "semantic_acceptance": "Requires inspection of reports against receipts before the selected boundary."}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--phase", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--artifact-cwd", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--channel", choices=["native", "fallback"])
    parser.add_argument("--only-phase", action="store_true")
    parser.add_argument("--cards-index", action="store_true")
    parser.add_argument("--query")
    parser.add_argument("--search", action="store_true")
    parser.add_argument("--source-passages", action="store_true")
    parser.add_argument("--cycle-recovery", action="store_true")
    parser.add_argument("--receipt-binding", action="store_true")
    parser.add_argument("--assembled", action="store_true")
    args = parser.parse_args()
    sessions = [("phase", args.phase)] if args.only_phase else [("ordinary", args.old), ("phase", args.phase)]
    run(sessions, args.output, args.key_file, execute=args.execute, artifact_cwd=args.artifact_cwd,
        resume=args.resume, channel=args.channel, cards_index=args.cards_index, query=args.query, search=args.search,
        source_passages=args.source_passages, cycle_recovery=args.cycle_recovery,
        receipt_binding=args.receipt_binding, assembled=args.assembled)
