"""Small real-Flash task-continuity probe, with a lossy negative control.

Synthetic task, read-only tools, same task and scoring across all arms. This
cannot establish absence of every possible long-task drift.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys

from evals.wsc_drift_budget import Budget
from evals.wsc_execution_behavior import event, execute_response
from evals.wsc_recall_executor import RecallExecutor
from evals.wsc_unfolded_source_ab import environment
from memory.wsc_projection import production_params
from synaptic.project import project
from tools.todo_write_tool.todo_write_tool import TodoWriteTool, parse_input


EXPECTED = {"objective_id": "BILL-27", "step_id": "verify", "pending_steps": ["verify", "report"],
            "decision": "decimal_half_even", "verification_id": "v-new",
            "verification_status": "error", "source_value": "7391", "latest_result_seen": "run-4827"}


def seed():
    # The relevant source is too large for checkpoint inlining; the code is
    # only in its final line, requiring a real archive read/search after fold.
    note = "任务 BILL-27 的规范记录。\n" + "无关存档字段 abcdefghijklmnopqrstuvwxyz\n" * 1150 + "request_code=7391\n"
    rows = [{"role": "user", "content": "顺口提一下，ChatGPT启动也有问题。", "id": "old"},
            {"role": "assistant", "content": "旧方案：浮点half_up，先处理启动窗口。"},
            {"role": "user", "id": "plan", "content": note},
            {"role": "user", "content": "当前任务 BILL-27：修复invoice精度。浮点half_up方案已否决，改用decimal_half_even。verify未完成，随后report；setup已完成。"}]
    rows += event("v-old", "Bash", {"command": "verify invoice"}, {"content": "older verification passed", "is_error": False})
    rows += event("v-new", "Bash", {"command": "verify invoice"}, {"content": "precision check failed after revision", "is_error": True})
    declaration = {"objective": "BILL-27：修复invoice精度", "context_message_ids": ["plan"],
                   "decisions": ["浮点half_up已否决；采用decimal_half_even"], "verification_call_ids": ["v-new"]}
    records = [{"id": "setup", "content": "建立校验脚本", "status": "completed", "activeForm": "建立校验"},
               {"id": "verify", "content": "修订并验证精度", "status": "in_progress", "activeForm": "验证精度"},
               {"id": "report", "content": "生成报告", "status": "pending", "activeForm": "生成报告"}]
    tool = TodoWriteTool()
    parsed = parse_input({"todos": records, "checkpoint": declaration})
    result = tool.call(parsed)
    rows += event("cp", "TodoWrite", {}, {"content": tool.map_tool_result_to_content(result), "is_error": False})
    return rows, note


class ProbeExecutor(RecallExecutor):
    def schemas(self):
        fields = {key: {"type": "string"} for key in EXPECTED}
        fields["pending_steps"] = {"type": "array", "items": {"type": "string"},
            "description": "All unfinished step IDs: both in_progress and pending; excludes completed."}
        fields["decision"] = {"type": "string", "description": "The selected precision rule identifier only, without commentary."}
        fields["verification_status"] = {"type": "string", "enum": ["ok", "error", "unknown"]}
        fields["source_value"] = {"type": "string", "description": "The value of request_code only, excluding its field name."}
        fields["latest_result_seen"] = {"type": "string", "description": "The latest_result value only, excluding its field name."}
        return super().schemas() + [{"name": "Submit", "description": "Records the task result.",
            "input_schema": {"type": "object", "properties": fields,
                             "required": list(EXPECTED), "additionalProperties": False}}]

    def execute(self, name, arguments):
        if name == "Submit":
            return {"is_error": False, "content": "result_recorded"}
        return super().execute(name, arguments)


def run(output, key_file, selected_arms=None):
    key_text = Path(key_file).read_text(encoding="utf-8-sig")
    keys = re.findall(r"sk-[A-Za-z0-9_-]{16,}", key_text)
    if len(keys) != 1:
        raise ValueError("key_file_format_ambiguous")
    key = keys[0]
    os.environ["DEEPSEEK_API_KEY"] = key
    os.environ["DEEPSEEK_BASE_URL"] = "https://api.deepseek.com"
    from evals.client import chat
    from model.deepseek import DeepSeekModelClient
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    budget = Budget(total=0.4)
    report = {"model": "deepseek-flash", "scope": "synthetic continuity probe; no proof of universal absence of drift",
              "price_source": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
              "price_per_m_cny": {"input_miss_peak": 2, "input_hit_peak": 0.04, "output_peak": 8},
              "per_call_budget_cny": 0.5, "total_budget_cny": 0.4, "arms": {}}
    rows, note = seed()
    for label in selected_arms or ("full_history", "lossy_control", "current_wsc"):
        root = output / label
        root.mkdir()
        with environment(root):
            projection = project(rows, region_end=len(rows), params=production_params(), view_path=root / "cold.txt") if label != "lossy_control" else None
            if label == "full_history":
                messages = list(rows)
            elif label == "current_wsc":
                messages = [{"role": "assistant", "content": projection.text}]
            else:
                # Intentional state/evidence loss; an explicit counter-control,
                # not a claim to reconstruct the historical implementation.
                messages = [{"role": "assistant", "content": "历史摘要：ChatGPT启动问题；旧方案浮点half_up；较早验证已通过。"}]
            messages += [{"role": "assistant", "content": [{"type": "tool_use", "id": "fresh", "name": "Read", "input": {"file_path": "latest-result.txt"}}]},
                         {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "fresh", "content": "latest_result=run-4827"}]},
                         {"role": "user", "content": "继续当前任务。用Submit记录当前目标ID、进行中步骤ID、未完成步骤ID列表、采用的精度方案、最新绑定验收调用ID与状态、规范中的request_code、最新读取结果标记。缺少的事实可以查询。"}]
            executor = ProbeExecutor(root, "read_search")
            schemas = executor.schemas()
            calls, wires, answer = [], [], {}
            for turn in range(3):
                client = DeepSeekModelClient(api_key=key, base_url="https://api.deepseek.com", model="deepseek-flash", thinking="disabled")
                body = client._build_body(messages, schemas, stream=False)
                entry = budget.admit(body, 700)
                try:
                    wire = chat(messages, model="deepseek-flash", tools=schemas, max_tokens=700,
                                thinking="disabled", temperature=0, timeout=50, retries=0, capture_wire=True)
                except Exception as exc:
                    report["error"] = {"class": type(exc).__name__, "arm": label, "turn": turn, "cost_unknown": True}
                    break
                budget.settle(entry, wire["response"].get("usage"))
                # The wire has no headers; reject any accidental secret leak.
                if key in json.dumps(wire):
                    raise RuntimeError("secret_in_capture")
                wires.append(wire)
                emitted, executed = execute_response(wire["response"]["choices"][0]["message"], executor)
                messages.extend(emitted)
                calls.extend(executed)
                submissions = [item for item in executed if item["name"] == "Submit"]
                if submissions:
                    answer = submissions[-1]["arguments"]
                    break
                if not executed:
                    break
            checks = {key: answer.get(key) == expected for key, expected in EXPECTED.items()}
            retrievals = [item for item in calls if item["name"] in {"Read", "Grep"} and not item["is_error"] and "request_code=7391" in item["content"]]
            report["arms"][label] = {"answer": answer, "checks": checks, "correct": sum(checks.values()),
                                     "total": len(checks), "source_recalled": bool(retrievals), "calls": calls,
                                     "projection_tokens_estimate": projection.tokens if projection else None}
            (root / "wire.json").write_text(json.dumps(wires, ensure_ascii=False, indent=2), encoding="utf-8")
            (root / "head.txt").write_text(projection.text if projection else messages[0]["content"], encoding="utf-8")
            report["cost"] = {"peak_cny_upper": budget.spent_upper, "requests": budget.entries}
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"arm": label, "correct": sum(checks.values()), "total": len(checks), "source_recalled": bool(retrievals), "peak_cny_upper": budget.spent_upper}), flush=True)
        if "error" in report:
            break
    return report


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--arm", choices=("full_history", "lossy_control", "current_wsc"))
    args = parser.parse_args()
    run(args.output, args.key_file, [args.arm] if args.arm else None)
