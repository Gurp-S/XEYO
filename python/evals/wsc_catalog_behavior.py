"""Real model retrieval from a cold identity directory; no production thresholds changed."""
import argparse
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sys

from evals.wsc_drift_budget import Budget
from evals.wsc_unfolded_source_ab import environment


async def run(output, key_file, *, cold=False, arm="current_wsc", bound=False, total_budget=0.15, spec_repeat=1800):
    keys = re.findall(r"sk-[A-Za-z0-9_-]{16,}", Path(key_file).read_text(encoding="utf-8-sig"))
    if len(keys) != 1:
        raise ValueError("key_file_format_ambiguous")
    key = keys[0]
    os.environ["DEEPSEEK_API_KEY"] = key
    os.environ["DEEPSEEK_BASE_URL"] = "https://api.deepseek.com"
    from evals.client import chat
    from evals.wsc_flash_compact_chain import native_store, extract_answer
    from engine.abort import AbortController
    from memory.wsc_handoff_catalog import Catalog
    from memory.wsc_handoff_generation import generate
    from memory.wsc_handoff_transaction import commit
    from memory.wsc_projection import production_params
    from memory.working import WorkingSnapshot
    from model.chunks import ModelChunk
    from model.deepseek import DeepSeekModelClient
    from msgtypes.message import ToolUse
    from session.compression_source import compression_messages
    from session.record_transcript import record_transcript_sync
    from synaptic.project import project
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    from tools.tool_registry import ToolRegistry
    from evals.wsc_recall_executor import RecallExecutor
    from evals.wsc_execution_behavior import execute_response
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    if not 0 < total_budget <= 0.4:
        raise ValueError("evaluation_total_budget_invalid")
    if type(spec_repeat) is not int or not 0 <= spec_repeat <= 300000:
        raise ValueError("evaluation_spec_repeat_invalid")
    budget = Budget(total=total_budget)
    with environment(output):
        rules = ["billing-spec：金额使用整数分，不使用浮点。", "退款和折扣分别验收。", "报告绑定最近失败回执，不以文件存在作为成功。"]
        if cold:
            rules = ["billing-spec：退款验收标记为RF-683917，折扣验收标记为DS-294806。", "报告关联失败标签EV-571308，文件存在不作为成功。", "验收报告归档编号AR-826451。"]
        rows = [{"id": "old", "role": "user", "content": "顺口提一下，启动窗口有问题。"}]
        rows += [{"id": f"record-{i}", "role": "assistant", "content": f"已归档执行记录{i}"} for i in range(120)]
        rows[20] = {"id": "billing-rule", "role": "assistant", "content": ("billing-spec归档记录\n" + "资料条目abcdefghijk\n" * spec_repeat if cold else "") + "\n".join(rules)}
        rows += [{"id": f"ack-{i}", "role": "user", "content": "继续"} for i in range(9)]
        rows += [{"id": "verify-use", "role": "assistant", "content": [{"type": "tool_use", "id": "verify-current", "name": "Bash", "input": {"command": "verify payment"}}]},
                 {"id": "verify-result", "role": "tool", "tool_call_id": "verify-current", "content": [{"type": "tool_result", "tool_use_id": "verify-current", "content": "refund boundary failed", "is_error": True, "execution": {"complete": True, "status": "error"}}]},
                 {"id": "current", "role": "user", "content": "当前任务PAY-42：支付边界验收；setup已完成，refund进行中，discount和report未完成。当前规范归档标题billing-spec，详细内容仍在原来源" + ("末尾" if cold else "") + "。最近验收调用verify-current失败。"}]
        store = native_store(rows)
        working = WorkingSnapshot(session_id="catalog-behavior")
        sources = compression_messages(store, working)
        catalog = Catalog(sources)
        assert "billing-rule" not in [r["message_id"] for r in catalog.initial()]
        initial = [{"role": "user", "content": rows[-1]["content"]}]
        if cold:
            prior = project(sources, region_end=len(sources), params=production_params(), view_path=output / "before.txt")
            assert all(value not in prior.text for value in ["RF-683917", "DS-294806", "EV-571308", "AR-826451"])
            initial = [{"role": "assistant", "content": prior.text}, {"role": "user", "content": rows[-1]["content"]}]
        registry = ToolRegistry(cwd=str(output))
        registry.register(TodoWriteTool(cwd=str(output)))
        if bound:
            initial_state = {"todos": [
                {"id": "setup", "content": "setup", "activeForm": "setup", "status": "completed"},
                {"id": "refund", "content": "refund", "activeForm": "refund", "status": "in_progress"},
                {"id": "discount", "content": "discount", "activeForm": "discount", "status": "pending"},
                {"id": "report", "content": "report", "activeForm": "report", "status": "pending"}],
                "checkpoint": {"objective": "PAY-42 支付边界验收", "context_message_ids": ["billing-rule", "current"],
                               "verification_call_ids": ["verify-current"]}}
            async def initial_generation(rows): return ToolUse("bound-state", "TodoWrite", initial_state)
            initial_known = set()
            await commit(source=lambda: compression_messages(store, working), generate=initial_generation, store=store,
                tools=registry, abort=AbortController(), persist=lambda: record_transcript_sync(store.items,
                    session_id=working.session_id,path=output / "initial-transcript.jsonl",known_ids=initial_known))
            sources = compression_messages(store, working)
            prior = project(sources, region_end=len(sources), params=production_params(), view_path=output / "bound-before.txt")
            assert all(value not in prior.text for value in ["RF-683917", "DS-294806", "EV-571308", "AR-826451"]) if cold else True
            initial = [{"role": "assistant", "content": prior.text}, {"role": "user", "content": rows[-1]["content"]}]
        client = DeepSeekModelClient(api_key=key, base_url="https://api.deepseek.com", model="deepseek-flash", thinking="disabled")
        traces, usages, calls = [], [], []
        class Model:
            context_limit = 1_000_000
            def __init__(self, max_tokens=2048):
                self.max_tokens = max_tokens
                self.last_usage = None
            def for_handoff(self, max_tokens): return Model(max_tokens)
            def context_input(self, messages, tools):
                body = client._build_body(messages, tools, stream=False)
                return {"messages": body["messages"], "tools": body.get("tools", [])}
            async def stream(self, messages, tools, abort):
                body = client._build_body(messages, tools, stream=False)
                entry = budget.admit(body, self.max_tokens)
                wire = await asyncio.to_thread(chat, messages, tools=tools, model="deepseek-flash", max_tokens=self.max_tokens,
                    thinking="disabled", temperature=0, timeout=50, retries=0, capture_wire=True)
                budget.settle(entry, wire["response"].get("usage"))
                self.last_usage = wire["response"].get("usage")
                if key in json.dumps(wire): raise RuntimeError("secret_in_capture")
                traces.append({"messages": deepcopy(messages), "wire": wire})
                response = wire["response"]["choices"][0]["message"]
                if response.get("content"): yield ModelChunk(kind="text_delta", text=response["content"])
                for call in response.get("tool_calls") or []:
                    fn = call["function"]
                    calls.append(fn["name"])
                    yield ModelChunk(kind="tool_use", tool_use=ToolUse(call["id"], fn["name"], json.loads(fn["arguments"])))
        known, error, declaration, answer, retrievals = set(), None, None, {}, []
        async def generated(source):
            return await generate(Model(), initial, source, TodoWriteTool().schema(), AbortController(), account=usages.append)
        try:
            if arm == "current_wsc":
                await commit(source=lambda: compression_messages(store, working), generate=generated, store=store,
                    tools=registry, abort=AbortController(), persist=lambda: record_transcript_sync(store.items,
                        session_id=working.session_id, path=output / "transcript.jsonl", known_ids=known))
                declaration = next(b["input"] for b in store.items[-2].content if b.get("type") == "tool_use")
                projected = project(compression_messages(store, working), region_end=len(store.items), params=production_params(), view_path=output / "cold.txt")
                (output / "head.txt").write_text(projected.text, encoding="utf-8")
                follow = [{"role": "assistant", "content": projected.text}]
            elif arm == "full_history":
                follow = deepcopy(sources)
            else:
                follow = [{"role": "assistant", "content": "历史摘要：旧启动任务；较早验收成功。"}]
            follow.append({"role": "user", "content": "继续当前任务，以JSON返回objective_id、pending_steps、verification_id、verification_status、rules（当前规范的全部原文" + ("，按原文逐条组成字符串数组" if cold else "") + "）。"})
            consumer = Model(700)
            executor = RecallExecutor(output, "read_search")
            for _ in range(4 if cold else 1):
                text, emitted_uses = "", []
                async for chunk in consumer.stream(follow, executor.schemas() if cold else [], AbortController()):
                    text += chunk.text or ""
                    if chunk.kind == "tool_use": emitted_uses.append(chunk.tool_use)
                if not emitted_uses:
                    answer = extract_answer(text)
                    break
                response = {"content": text, "tool_calls": [{"id": use.id, "function": {"name": use.name, "arguments": json.dumps(use.input)}} for use in emitted_uses]}
                emitted, executed = await asyncio.to_thread(execute_response, response, executor)
                follow.extend(emitted)
                retrievals.extend(executed)
        except Exception as exc:
            error = type(exc).__name__ + ": " + str(exc)
            if key in error: error = type(exc).__name__
        checks = {"real_catalog_call": "HandoffCatalog" in calls, "real_source_read": "HandoffSource" in calls,
            "rule_source_read": any(call["function"]["name"] == "HandoffSource" and json.loads(call["function"]["arguments"]).get("message_id") == "billing-rule"
                for trace in traces for call in trace["wire"]["response"]["choices"][0]["message"].get("tool_calls", [])),
            "real_commit": declaration is not None, "all_rules_recalled": answer.get("rules") == rules,
            "current_goal": answer.get("objective_id") == "PAY-42",
            "pending_steps": answer.get("pending_steps") == ["refund", "discount", "report"],
            "verification": answer.get("verification_id") == "verify-current" and answer.get("verification_status") in {"error", "failed"},
            "no_old_goal_declared": declaration is not None and "启动" not in declaration["checkpoint"]["objective"]}
        checks["consumer_rules_verified_by_actual_read"] = any(not r["is_error"] and all(code in r["content"] for code in ["RF-683917", "DS-294806", "EV-571308", "AR-826451"]) for r in retrievals) if cold else False
        report = {"scope": "synthetic cold-directory handoff, real generation/commit/deterministic project/read-only continuation; no query-loop Compact or 85% trigger",
            "arm": arm, "cold": cold, "bound": bound, "spec_repeat": spec_repeat, "rules_ground_truth": rules, "retrievals": retrievals,
            "source_rows": len(sources), "checks": checks, "error": error, "calls": calls, "declaration": declaration,
            "answer": answer, "requests": traces, "usage": usages, "cost": {"peak_cny_upper": budget.spent_upper, "requests": budget.entries}}
        (output / "report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"checks": checks, "error": error, "cost_upper": budget.spent_upper},ensure_ascii=False))
        return report


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--cold", action="store_true")
    parser.add_argument("--bound", action="store_true")
    parser.add_argument("--total-budget", type=float, default=0.15)
    parser.add_argument("--spec-repeat", type=int, default=1800)
    parser.add_argument("--arm", choices=["current_wsc", "full_history", "lossy_control"], default="current_wsc")
    args = parser.parse_args()
    asyncio.run(run(args.output,args.key_file,cold=args.cold,arm=args.arm,bound=args.bound,total_budget=args.total_budget,spec_repeat=args.spec_repeat))
