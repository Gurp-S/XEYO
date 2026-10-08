"""Paired real Read/model recall of a task source exceeding atomic Read limits."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evals.wsc_execution_behavior import execute_response
from evals.wsc_recall_executor import RecallExecutor
from evals.wsc_request_projection import arm
from evals.wsc_task_continuity_ab import task_event
from evals.wsc_handoff_behavior import answer_json
from memory.wsc_projection import production_params
from synaptic.project import project
from synaptic.task_handoff import render as handoff


def old_capacity_render(state, nodes, handles):
    return handoff({**state, "unknown_sources": state["unknown_sources"] + state.get("deferred_sources", []),
        "deferred_sources": []}, nodes, handles)


def run(output, max_calls=4, query_profile="unknown_allowed", tool_surface="read"):
    from evals.client import chat, MODEL_ID, UsageAccount
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    previous = os.environ.get("XEYO_WSC_TASK_CONTINUITY")
    os.environ["XEYO_WSC_TASK_CONTINUITY"] = "1"
    plan = "当前文档定义，唯一 request_code 位于末尾。" + "abcdefghij" * 12000 + "; request_code=7391"
    rows = [{"role": "user", "id": "large-plan", "content": plan}] + task_event("checkpoint",
        [{"id": "work", "content": "核验文档定义", "status": "in_progress", "activeForm": "核验定义"}],
        {"objective": "核验文档定义", "context_message_ids": ["large-plan"]})
    queries = {
        "unknown_allowed": "继续核验当前任务文档。返回 JSON：task_id、request_code（原文末尾定义的值）、evidence_call_id（实际读取该定义的调用ID）。未知字段用null。",
        "lookup": "查询当前任务文档中 request_code 的定义。返回 JSON：task_id、request_code、evidence_call_id（取得定义的实际调用ID）。",
        "step_lookup": "查询当前步骤关联文档中 request_code 的定义。返回 JSON：step_id、request_code、evidence_call_id（取得定义的实际调用ID）。",
    }
    query = queries[query_profile]
    report = {"scope": "paired real-model/Read cold recall; declared synthetic task, not historical execution",
        "query_profile": query_profile, "user_query": query, "tool_surface": tool_surface,
        "identity_contract": "step_id" if query_profile == "step_lookup" else "legacy_task_alias_for_step_id",
        "model": MODEL_ID, "arms": {}, "compression_model_calls": 0, "live_files_modified": False}
    try:
        for label in ("before", "after"):
            root = output / label
            root.mkdir(exist_ok=True)
            with ExitStack() as stack:
                stack.enter_context(arm("1", root / "home"))
                if label == "before":
                    stack.enter_context(patch("synaptic.chunked_recovery.prepare", return_value={}))
                    stack.enter_context(patch("synaptic.task_handoff.render", side_effect=old_capacity_render))
                projection = project(rows, region_end=len(rows), params=production_params(), view_path=root / "cold.txt")
                (root / "head.txt").write_text(projection.text, encoding="utf-8")
                messages = [{"role": "assistant", "content": projection.text}, {"role": "user", "content": query}]
                executor = RecallExecutor(root, tool_surface)
                schemas = executor.schemas()
                calls, wires, usage, answer = [], [], [], {}
                for turn in range(max_calls):
                    account = UsageAccount(label)
                    from synaptic.receipt_render import render as render_receipts
                    wire = chat(render_receipts(messages), tools=schemas, max_tokens=900, temperature=0,
                        timeout=55, retries=0, acct=account, capture_wire=True)
                    wires.append(wire)
                    usage.append({key: value for key, value in account.summary().items() if key != "cost_cny"})
                    response = wire["response"]["choices"][0]["message"]
                    emitted, executed = execute_response(response, executor)
                    calls.extend(executed)
                    messages.extend(emitted)
                    (root / "wire.json").write_text(json.dumps(wires, ensure_ascii=False, indent=2), encoding="utf-8")
                    if not executed:
                        answer = answer_json(response.get("content"))
                        break
                evidence = [entry["id"] for entry in calls if entry["name"] in {"Read", "Grep"} and not entry["is_error"]
                    and "request_code=7391" in entry["content"]
                    and (root / str(entry["arguments"].get("file_path" if entry["name"] == "Read" else "path", ""))).resolve()
                        == Path(projection.view_path).resolve()]
                identity_field = "step_id" if query_profile == "step_lookup" else "task_id"
                identity_metric = "step_identity" if query_profile == "step_lookup" else "legacy_task_alias"
                evidence_metric = "actual_source_reference" if tool_surface == "read_search" else "actual_read_reference"
                score = {identity_metric: answer.get(identity_field) == "work",
                    "source_fact": str(answer.get("request_code")) == "7391",
                    evidence_metric: answer.get("evidence_call_id") in evidence,
                    "model_terminated": bool(answer)}
                sample = {"answer": answer, "acceptance": score, "calls": calls, "usage": usage,
                    "cold_storage": {"source_bytes": sum(len(text.encode("utf-8")) for text in projection.cold.texts.values()),
                        "snapshot_bytes": sum(len(text.encode("utf-8")) for text in projection.cold.snapshots.values()),
                        "published_view_bytes": Path(projection.view_path).stat().st_size}}
                report["arms"][label] = sample
                (root / "exchange.json").write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
                (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({"arm": label, "acceptance": score}), flush=True)
        return report
    finally:
        if previous is None:
            os.environ.pop("XEYO_WSC_TASK_CONTINUITY", None)
        else:
            os.environ["XEYO_WSC_TASK_CONTINUITY"] = previous


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-calls", type=int, default=4)
    parser.add_argument("--query-profile", choices=("unknown_allowed", "lookup", "step_lookup"), default="unknown_allowed")
    parser.add_argument("--tool-surface", choices=("read", "read_search"), default="read")
    args = parser.parse_args()
    result = run(args.output, args.max_calls, args.query_profile, args.tool_surface)
    sys.exit(0 if all(result["arms"]["after"]["acceptance"].values()) else 1)
