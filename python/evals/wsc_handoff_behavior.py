"""Paired model continuation/recall probe, with fixed task-fact ground truth.

No model rewrites the compression. This evaluates read-only continuation
answers; it is not a full agent execution or historical-progress reconstruction.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evals.wsc_task_continuity_ab import task_event
from evals.wsc_request_projection import arm
from evals.stale_goal_ab import tool_read
from memory.wsc_projection import production_params
from synaptic.project import project


QUERY = "继续当前任务。返回 JSON：task_id（下一待办的步骤 ID），objective（任务目标声明），decisions（决定声明数组），completed_ids（已完成步骤 ID 数组），verification_ids（关联执行回执 ID 数组）。未知字段用 null。"
READ = {"type": "function", "function": {"name": "Read", "description": "Read a recorded source file and line range.",
    "parameters": {"type": "object", "properties": {"file_path": {"type": "string"},
        "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["file_path"]}}}


def cases():
    common = [{"role": "user", "content": "随口提过的历史请求：修复 ChatGPT 启动。", "id": "old"},
        {"role": "user", "content": "当前两批计划：第一批接线；第二批身份贯穿去重、分组和跨轮匹配。存在性过滤方案已否决。", "id": "plan"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "baseline", "name": "Bash", "input": {"command": "pytest identity_checks.py"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "baseline", "content": "12 passed", "is_error": False,
            "execution": {"status": "ok", "complete": True}}]}]
    records = [{"id": "batch1", "content": "第一批接线", "status": "completed", "activeForm": "核对接线"},
               {"id": "batch2", "content": "第二批：身份贯穿去重、分组和跨轮匹配", "status": "pending", "activeForm": "核对身份"}]
    checkpoint = {"objective": "WSC 第二批身份修复", "context_message_ids": ["plan"],
        "decisions": ["存在性过滤方案已否决"], "constraints": ["未知失败保留来源"], "verification_call_ids": ["baseline"]}
    yield {"name": "second_batch", "rows": common + task_event("checkpoint", records, checkpoint),
        "truth": {"task_id": "batch2", "objective": checkpoint["objective"], "decisions": checkpoint["decisions"],
                  "completed_ids": ["batch1"], "verification_ids": ["baseline"]}}
    changed = [dict(item) for item in records]
    changed[0]["id"] = "setup"
    changed[1].update(id="payment", content="当前任务：支付金额计算的边界验证")
    checkpoint = {"objective": "支付金额计算验证", "context_message_ids": ["@latest_user"],
        "decisions": ["历史登录任务无当前绑定"], "constraints": ["保留验证回执"], "verification_call_ids": ["baseline"]}
    rows = common + [{"role": "user", "content": "当前支付任务的边界说明：退款与折扣分别验证。", "id": "payment-plan"}]
    yield {"name": "unclosed_old_request", "rows": rows + task_event("checkpoint", changed, checkpoint),
        "truth": {"task_id": "payment", "objective": checkpoint["objective"], "decisions": checkpoint["decisions"],
                  "completed_ids": ["setup"], "verification_ids": ["baseline"]}}


def answer_json(content):
    text = str(content or "")
    for index, char in enumerate(text):
        if char == "{":
            try:
                value, _ = json.JSONDecoder().raw_decode(text[index:])
                if isinstance(value, dict):
                    return value
            except ValueError:
                pass
    return {}


def grade(answer, truth):
    """Fixed schema facts, not keywords in the compressed head or an LLM judge."""
    matches = {}
    for field, expected in truth.items():
        actual = answer.get(field)
        matches[field] = (isinstance(actual, list) and all(isinstance(item, str) for item in actual)
                          and sorted(actual) == sorted(expected)) if isinstance(expected, list) else actual == expected
    given = sum(answer.get(field) is not None for field in truth)
    correct = sum(matches.values())
    return {"fields": matches, "correct": correct, "expected": len(truth), "provided": given,
        "declared_field_exact_recall": correct / len(truth), "declared_field_exact_precision": correct / given if given else 0,
        "wrong_task_identity": answer.get("task_id") not in (None, truth["task_id"]),
        "old_goal_selected": answer.get("task_id") == "legacy-chatgpt" or answer.get("objective") == "修复 ChatGPT 启动"}


def run(output, *, model=None, max_calls=3):
    from evals.client import chat, MODEL_ID, UsageAccount
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    previous = {key: os.environ.get(key) for key in ("XEYO_WSC_TASK_CONTINUITY", "XEYO_WSC_FAILURE_FACTS")}
    report = {"scope": "paired read-only continuation answers; declared fixture states, not reconstructed historical progress",
              "model": model or MODEL_ID, "arms": {}, "compression_model_calls": 0, "prices_verified": False}
    try:
        os.environ["XEYO_WSC_TASK_CONTINUITY"] = "1"
        corpus = list(cases())
        for label, flag in (("before", "0"), ("after", "1")):
            os.environ.update(XEYO_WSC_TASK_CONTINUITY=flag, XEYO_WSC_FAILURE_FACTS="1")
            samples = []
            with arm("1", output / label / "home"):
                for case in corpus:
                    folder = output / label / case["name"]
                    folder.mkdir(parents=True, exist_ok=True)
                    projected = project(case["rows"], region_end=len(case["rows"]), params=production_params(),
                        view_path=folder / "cold.txt", view_ref=str(folder / "cold.txt"))
                    (folder / "head.txt").write_text(projected.text, encoding="utf-8")
                    messages = [{"role": "user", "content": projected.text}, {"role": "user", "content": QUERY}]
                    usage = []
                    reads = []
                    answer = {}
                    for turn in range(max_calls):
                        account = UsageAccount(case["name"])
                        response = chat(messages, model=model, tools=[READ], max_tokens=900, temperature=0,
                                        timeout=55, retries=0, acct=account)
                        counts = account.summary()
                        usage.append({key: counts[key] for key in ("requests", "prompt_tokens", "completion_tokens", "cached_tokens", "elapsed_s")})
                        calls = [{"id": f"probe-{turn}-{index}", "type": "function", "function": {
                            "name": call["name"], "arguments": json.dumps(call["arguments"], ensure_ascii=False)}}
                            for index, call in enumerate(response.get("tool_calls") or [])]
                        message = {"role": "assistant", "content": response.get("content")}
                        if calls:
                            message["tool_calls"] = calls
                        messages.append(message)
                        if not calls:
                            answer = answer_json(message.get("content"))
                            break
                        for call in calls:
                            function = call.get("function") or {}
                            try:
                                arguments = json.loads(function.get("arguments") or "{}")
                                requested = Path(arguments.get("file_path", "")).resolve()
                                if function.get("name") != "Read" or requested.parent != folder:
                                    result = {"is_error": True, "content": "Permission denied: fixture_source_scope"}
                                else:
                                    result = tool_read(arguments, folder)
                            except (ValueError, TypeError):
                                result = {"is_error": True, "content": "invalid_arguments"}
                            reads.append({"arguments": function.get("arguments"), "is_error": result["is_error"]})
                            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result["content"]})
                    sample = {"case": case["name"], "answer": answer, "truth": case["truth"],
                              "grade": grade(answer, case["truth"]), "usage": usage, "reads": reads,
                              "head_tokens_estimated": projected.tokens, "calls": len(usage)}
                    samples.append(sample)
                    (folder / "exchange.json").write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
                    report["arms"][label] = samples
                    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(json.dumps({"arm": label, "case": case["name"], "grade": sample["grade"], "calls": len(usage)}), flush=True)
        return report
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--model")
    parser.add_argument("--max-calls", type=int, default=3)
    args = parser.parse_args()
    run(args.output, model=args.model, max_calls=args.max_calls)
