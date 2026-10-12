"""Offline model-owned phase review at two boundaries of a real transcript.

This evaluates an uncommitted draft. It does not enable a production review
call, change compression policy, or claim post-fold execution continuity.
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

REVIEW = (
    "以上是尚未提交的交接草稿。请依据来源时间顺序复核当前阶段的有效状态，"
    "返回完整任务交接声明。目标、步骤进度、决定及约束采用当前阶段；"
    "已结束阶段的要求属于历史来源。后来的消息不自动废弃持续有效的约束。"
    "阶段与约束适用性由你根据原始来源判断，执行结果以已观察回执为准。"
)


def phase_score(label, raw, candidate):
    """Fixture-specific current-phase assertions, separate from commit validity."""
    checkpoint = raw["checkpoint"]
    from synaptic.task_phase import applicable
    active_constraints = applicable(checkpoint, "constraints")
    old_active = any(fact.get("source_message_id") == "msg_mv2ihbrn_0yg7c0"
                     for fact in active_constraints)
    if label == "implementation":
        criteria = {"old_stage_requirement_not_current": not old_active,
            "current_test_limit_retained": any(fact.get("source_message_id") == "msg_mv2ivet1_d4f6oi"
                and "过程中不用进行任何测试" in fact.get("quote", "") for fact in active_constraints),
            "report_still_in_progress": any(item["status"] == "in_progress" and "汇总" in item["content"] for item in raw["todos"]),
            "actual_verification_ids_retained": {"call_00_n8N74Rqd18UaM2Ueii4T3899", "call_00_1lmc0GWrgBxRuLlchMmZ6048"}
                <= set(checkpoint["verification_call_ids"])}
    else:
        criteria = {"still_effective_no_edit_retained": old_active,
            "current_review_step_in_progress": any(item["status"] == "in_progress" and "复审" in item["content"] for item in raw["todos"])}
    return {"criteria": criteria, "all_passed": all(criteria.values()), "final_equals_candidate": raw == candidate,
            "limits": "Known real fixture phase assertions; no post-fold execution or semantic coverage guarantee."}


async def run(session, captured, output, key_file, *, scope_protocol=False):
    from engine.abort import AbortController
    from evals.client import chat
    from evals.wsc_catalog_behavior import environment
    from memory.runtime import force_compact
    from memory.working import WorkingSnapshot
    from memory.wsc_handoff_generation import generate
    from memory.wsc_handoff_transaction import commit
    from model.chunks import ModelChunk
    from model.deepseek import DeepSeekModelClient
    from msgtypes.message import ToolUse
    from session.compression_source import compression_messages
    from session.hydrate import messages_from_rows
    from session.message_store import MessageStore
    from session.record_transcript import record_transcript_sync
    from session.surface import fold_surface_rows
    from session.transcript_blobs import resolve_transcript_rows
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    from tools.tool_registry import ToolRegistry

    session, captured, output = session.resolve(), captured.resolve(), output.resolve()
    data = session.read_bytes()
    rows = [json.loads(line) for line in data.decode("utf-8-sig").splitlines() if line.strip()]
    keys = re.findall(r"sk-[A-Za-z0-9_-]{16,}", key_file.read_text(encoding="utf-8-sig"))
    if len(keys) != 1:
        raise ValueError("key_file_format_ambiguous")
    key = keys[0]
    os.environ["DEEPSEEK_API_KEY"] = key
    os.environ["DEEPSEEK_BASE_URL"] = "https://api.deepseek.com"
    report = json.loads(captured.read_text(encoding="utf-8"))
    draft = json.loads(report["requests"][-1]["response"]["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
    budget = Budget(total=0.3)
    results = []
    for label, boundary in (("implementation", 364), ("design", 226)):
        folder = output / label
        folder.mkdir(parents=True, exist_ok=False)
        with environment(folder):
            selected = resolve_transcript_rows(fold_surface_rows(rows[:boundary]), session)
            store = MessageStore(messages_from_rows(selected))
            source = lambda: compression_messages(store, WorkingSnapshot())
            original = deepcopy(source())
            initial = force_compact(original, WorkingSnapshot(session_id="phase-review"), cwd=folder)
            candidate = deepcopy(draft)
            if label == "design":
                # Positive control uses only facts present at the earlier boundary.
                uid = "msg_mv2ihbrn_0yg7c0"
                text = next(row["content"] for row in original if row.get("message_id", row.get("id")) == uid)
                candidate = {"todos": [{"id": "review", "content": "复审修复方案", "status": "in_progress", "activeForm": "复审修复方案"}],
                    "checkpoint": {"objective": "复审修复方案", "context_message_ids": [uid, "msg_mv2ilvl2_2z2ytw"],
                        "decisions": [], "constraints": [{"source_message_id": uid, "quote": text}], "verification_call_ids": []}}
            initial += [{"role": "assistant", "content": "未提交交接草稿=" + json.dumps(candidate, ensure_ascii=False)},
                        {"role": "user", "content": REVIEW}]
            captures, usages = [], []
            provider = DeepSeekModelClient(api_key=key, base_url="https://api.deepseek.com", model="deepseek-flash", thinking="disabled")

            class Model:
                context_limit = 1_000_000
                last_usage = None
                def for_handoff(self, max_tokens):
                    return self
                def context_input(self, messages, tools):
                    body = provider._build_body(messages, tools, stream=False)
                    return {"messages": body["messages"], "tools": body.get("tools", [])}
                async def stream(self, messages, tools, abort):
                    body = provider._build_body(messages, tools, stream=False)
                    serialized = json.dumps(body, ensure_ascii=False)
                    if key in serialized or re.search(r"sk-[A-Za-z0-9_-]{24,}", serialized):
                        raise ValueError("probe_sensitive_source")
                    entry = budget.admit(body, 2048)
                    wire = await asyncio.to_thread(chat, messages, tools=tools, model="deepseek-flash", thinking="disabled",
                        max_tokens=2048, temperature=0, timeout=50, retries=0, capture_wire=True)
                    self.last_usage = wire["response"].get("usage")
                    budget.settle(entry, self.last_usage)
                    captures.append(wire)
                    message = wire["response"]["choices"][0]["message"]
                    for call in message.get("tool_calls") or []:
                        function = call["function"]
                        yield ModelChunk(kind="tool_use", tool_use=ToolUse(call["id"], function["name"], json.loads(function["arguments"])))

            tools = ToolRegistry(cwd=str(folder))
            tools.register(TodoWriteTool(cwd=str(folder)))
            path, known = folder / "transcript.jsonl", set()
            def persist():
                record_transcript_sync(store.items, session_id="phase-review", path=path, known_ids=known)
            persist()
            prefix = path.read_bytes()
            async def declaration(captured_source):
                return await generate(Model(), initial, captured_source, TodoWriteTool().schema(), AbortController(),
                                      account=usages.append, scope_protocol=scope_protocol)
            error, receipt = None, None
            try:
                receipt = await commit(source=source, generate=declaration, store=store, tools=tools, abort=AbortController(), persist=persist)
            except Exception as exc:
                error = str(exc)
            result = {"arm": label, "boundary_exclusive": boundary, "source_rows": len(original),
                "commit": receipt, "error": error, "candidate": candidate, "requests": captures, "usage": usages,
                "source_prefix_unchanged": source()[:len(original)] == original,
                "persisted_prefix_unchanged": path.read_bytes().startswith(prefix)}
            if receipt is not None:
                final = captures[-1]["response"]["choices"][0]["message"]["tool_calls"][0]
                result["phase_score"] = phase_score(label, json.loads(final["function"]["arguments"]), candidate)
            (folder / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append({key: result[key] for key in ("arm", "boundary_exclusive", "source_rows", "commit", "error", "source_prefix_unchanged", "persisted_prefix_unchanged")})
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    summary = {"scope": __doc__, "results": results, "cost_upper": budget.spent_upper, "entries": budget.entries,
        "scope_protocol": scope_protocol,
        "original_unchanged": hashlib.sha256(data).hexdigest() == hashlib.sha256(session.read_bytes()).hexdigest(),
        "semantic_result": "Requires independent inspection of current-phase validity and retained constraints."}
    (output / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cost_upper": budget.spent_upper, "original_unchanged": summary["original_unchanged"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--captured", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--scope-protocol", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.session, args.captured, args.output, args.key_file, scope_protocol=args.scope_protocol))
