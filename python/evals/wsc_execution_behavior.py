"""Isolated real-model/tool execution across forced folds and a cold restart.

Uses product Read/Edit/Write/TodoWrite; the Bash adapter executes only the
immutable fixture verifier. No live session/settings or production work files
are changed. Compression timing is forced, not a historical wire replay.
"""
import argparse
import asyncio
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evals.wsc_request_projection import arm
from synaptic.todo_snapshot import latest_todo_snapshot


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def event(uid, name, arguments, result):
    return [{"role": "assistant", "content": [{"type": "tool_use", "id": uid, "name": name, "input": arguments}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": uid, "content": result["content"],
             "is_error": result["is_error"], "execution": {"status": "error" if result["is_error"] else "ok", "complete": True,
                 **(result.get("execution") or {})}}]}]


def execute_response(response, executor):
    """Keep the provider's single assistant turn and exact call identities."""
    blocks, results, calls = [], [], []
    if response.get("content"):
        blocks.append({"type": "text", "text": response["content"]})
    for call in response.get("tool_calls") or []:
        uid = call.get("id")
        if not isinstance(uid, str) or not uid:
            raise ValueError("provider_call_id_missing")
        fn = call["function"]
        arguments = json.loads(fn["arguments"])
        blocks.append({"type": "tool_use", "id": uid, "name": fn["name"], "input": arguments})
        result = executor.execute(fn["name"], arguments)
        results.extend(event(uid, fn["name"], arguments, result)[1:])
        calls.append({"id": uid, "name": fn["name"], "arguments": arguments, **result})
    return ([{"role": "assistant", "content": blocks}] + results), calls


class Executor:
    def __init__(self, root, records=()):
        from tools.file_read_tool.file_read_tool import FileReadTool
        from tools.file_edit_tool.file_edit_tool import FileEditTool
        from tools.file_write_tool.file_write_tool import FileWriteTool
        from tools.fileio.read_state import ReadFileState
        from tools.todo_write_tool.todo_write_tool import TodoWriteTool
        from tools.todo_write_tool.types import todo_item_from_raw
        from tools.todo_write_tool.store import TodoStore
        self.root = root
        state = ReadFileState()
        store = TodoStore()
        store.set([todo_item_from_raw(item) for item in records], key="default")
        self.tools = {"Read": FileReadTool(cwd=str(root), read_state=state),
            "Edit": FileEditTool(cwd=str(root), read_state=state),
            "Write": FileWriteTool(cwd=str(root), read_state=state),
            "TodoWrite": TodoWriteTool(cwd=str(root), store=store)}

    def schemas(self):
        definitions = [tool.schema() for tool in self.tools.values()]
        definitions.append({"name": "Bash", "description": "Fixture verification command execution.",
            "input_schema": {"type": "object", "properties": {"command": {"type": "string",
                "enum": ["py -3.11 verify.py price", "py -3.11 verify.py all"]}}, "required": ["command"]}})
        return definitions

    def execute(self, name, arguments):
        from engine.abort import AbortController
        if name == "Bash":
            command = arguments.get("command", "")
            if command not in {"py -3.11 verify.py price", "py -3.11 verify.py all"}:
                return {"is_error": True, "content": "Permission denied: fixture_command_scope"}
            completed = subprocess.run([sys.executable, "-B", "verify.py", command.split()[-1]], cwd=self.root,
                capture_output=True, text=True, timeout=15)
            return {"is_error": completed.returncode != 0,
                "content": completed.stdout + completed.stderr + f"\nexit_code={completed.returncode}"}
        if name in {"Read", "Edit", "Write"}:
            target = (self.root / str(arguments.get("file_path", ""))).resolve()
            if not target.is_relative_to(self.root):
                return {"is_error": True, "content": "Permission denied: fixture_path_scope"}
            if name != "Read" and target.name not in {"payment.py", "report.json"}:
                return {"is_error": True, "content": "Permission denied: immutable_fixture_file"}
        if name not in self.tools:
            return {"is_error": True, "content": "unknown_tool"}
        result = asyncio.run(self.tools[name].execute(arguments, AbortController()))
        from engine.execution_facts import tool_receipt
        return {"is_error": result.is_error, "content": result.content, "execution": tool_receipt(result)}


def seed(root):
    root.mkdir(parents=True, exist_ok=False)
    (root / "payment.py").write_text("def total(subtotal, discount):\n    return subtotal + discount\n\ndef refund(amount, fee):\n    return amount + fee\n", encoding="utf-8")
    (root / "legacy.txt").write_text("Historical ChatGPT task; no current binding.\n", encoding="utf-8")
    (root / "verify.py").write_text("import sys\nfrom payment import total, refund\nassert total(100, 10) == 90, 'discount boundary'\nprint('price=passed')\nif sys.argv[1] == 'all':\n    assert refund(100, 5) == 95, 'refund boundary'\n    assert refund(0, 0) == 0, 'zero refund'\n    print('refund=passed; all=passed')\n", encoding="utf-8")
    plan = ("当前任务：完成 payment.py 的折扣与退款修复，并写 report.json。步骤 ID 为 price/refund/report。"
        "折扣 total(100,10)=90；退款 refund(100,5)=95，refund(0,0)=0。第一步完成后继续其余步骤。"
        "决定：用算术结果及执行回执核验完成，文件存在不作为成功证据。报告 JSON 字段为 result='passed'、"
        "verification_call_id=最后成功全量验证的实际调用 ID、completed_task_ids=['price','refund']。"
        "验证命令为 py -3.11 verify.py price 与 py -3.11 verify.py all；legacy.txt 是历史资料。")
    rows = [{"role": "user", "content": "顺口提一下：ChatGPT 启动也有问题。", "id": "old"},
            *[{"role": "assistant", "content": f"归档负载记录 {index}: " + "0123456789abcdef" * 256}
              for index in range(12)],
            {"role": "user", "content": plan, "id": "plan"}]
    executor = Executor(root)
    for uid, name, arguments in [("seed-read", "Read", {"file_path": "payment.py"}),
        ("seed-edit", "Edit", {"file_path": "payment.py", "old_string": "return subtotal + discount", "new_string": "return subtotal - discount"}),
        ("price-ok", "Bash", {"command": "py -3.11 verify.py price"}),
        ("all-failed", "Bash", {"command": "py -3.11 verify.py all"})]:
        result = executor.execute(name, arguments)
        rows += event(uid, name, arguments, result)
        if uid != "all-failed" and result["is_error"]:
            raise RuntimeError("fixture_seed_failed: " + result["content"])
    records = [{"id": uid, "content": text, "status": status, "activeForm": text}
        for uid, text, status in (("price", "折扣修复与验证", "completed"),
            ("refund", "退款与零值修复及全量验证", "in_progress"), ("report", "写入实际验证回执的 JSON 报告", "pending"))]
    checkpoint = {"objective": "完成付款算术修复与验证报告", "context_message_ids": ["plan"],
        "decisions": ["文件存在不作为成功证据"], "constraints": ["报告关联实际全量成功调用 ID"],
        "verification_call_ids": ["price-ok", "all-failed"]}
    result = executor.execute("TodoWrite", {"todos": records, "checkpoint": checkpoint})
    if result["is_error"]:
        raise RuntimeError("fixture_checkpoint_failed")
    rows += event("seed-checkpoint", "TodoWrite", {"todos": records, "checkpoint": checkpoint}, result)
    return rows, records


def verification_association(rows, artifact):
    """Use actual paired receipts, including the resumed trace, not log labels."""
    from synaptic.textutil import tool_use_blocks, tool_result_blocks
    uses, results = {}, {}
    for index, row in enumerate(rows):
        for use in tool_use_blocks(row):
            uses.setdefault(use.get("id"), []).append((index, use))
        for result in tool_result_blocks(row):
            results.setdefault(result.get("tool_use_id"), []).append((index, result))
    successes, writes = [], []
    for uid, calls in uses.items():
        receipts = results.get(uid, [])
        if len(calls) != 1 or len(receipts) != 1:
            continue
        index, use = calls[0]
        result_index, receipt = receipts[0]
        execution = receipt.get("execution") or {}
        if index >= result_index or receipt.get("is_error") is not False or execution.get("complete") is False:
            continue
        if execution.get("status") in {"error", "cancelled"}:
            continue
        args = use.get("input") or {}
        if use.get("name") == "Bash" and args.get("command") == "py -3.11 verify.py all":
            successes.append((result_index, uid))
        if use.get("name") == "Write" and args.get("file_path") == "report.json":
            try:
                if json.loads(args.get("content", "")) == artifact:
                    writes.append(index)
            except (ValueError, TypeError):
                pass
    preceding = sorted((index, uid) for index, uid in successes if writes and index < max(writes))
    return {"report_actual_success_reference": any(uid == artifact.get("verification_call_id") for _, uid in successes),
            "report_latest_success_at_write": bool(preceding) and preceding[-1][1] == artifact.get("verification_call_id")}


def run_arm(root, flag, *, model, max_turns, resume_source=None):
    from evals.client import chat, UsageAccount
    from memory import wsc_projection as live, wsc_head_store as heads
    os.environ["XEYO_WSC_TASK_CONTINUITY"] = "1"
    rows, records = seed(root)
    if resume_source is not None:
        captured = json.loads((resume_source / "trace.json").read_text(encoding="utf-8"))["rows"]
        cut = next(index + 1 for index in range(len(captured))
            if (current := latest_todo_snapshot(captured[:index + 1])).observed
            and current.active_count == 0 and current.records)
        rows = captured[:cut]
        records = list(latest_todo_snapshot(rows).records)
        for name in ("payment.py", "report.json", "verify.py", "legacy.txt"):
            shutil.copyfile(resume_source / name, root / name)
    (root / "seed.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    frozen_files = {name: digest(root / name) for name in ("legacy.txt", "verify.py")}
    os.environ["XEYO_WSC_TASK_CONTINUITY"] = flag
    executor = Executor(root, records)
    working = SimpleNamespace(session_id="execution-fixture-" + flag, compact_cursor=len(rows), c1_frozen_until=len(rows))
    if resume_source is None:
        rows += [{"role": "user", "content": "继续当前任务。"}]
    log, emissions, usage, wires = [], [], [], []
    folds = 0
    restarts = 0
    final = ""
    with ExitStack() as stack:
        stack.enter_context(patch.object(live, "live_enabled", return_value=True))
        stack.enter_context(patch.object(live, "freeze_enabled", return_value=True))
        stack.enter_context(patch.object(heads, "enabled", return_value=True))
        stack.enter_context(patch("memory.wsc_extension_economics.absorb_boundary", side_effect=lambda messages, cursor: cursor))
        previous = None
        for turn in range(max_turns):
            emitted = live.project_c2_messages(rows, working, cwd=str(root))
            if emitted is None:
                raise RuntimeError("fixture_compression_not_admitted")
            if previous is not None and turn % 2:
                if emitted[:len(previous)] != previous:
                    raise RuntimeError("same_generation_prefix_changed")
            emissions.append({"turn": turn, "cursor": working.compact_cursor, "head_sha256": hashlib.sha256(emitted[0]["content"].encode()).hexdigest()})
            account = UsageAccount("execution")
            response = chat(emitted, model=model, tools=executor.schemas(), max_tokens=1600,
                            temperature=0, timeout=55, retries=0, acct=account, capture_wire=True)
            wires.append(response)
            (root / "wire.json").write_text(json.dumps(wires, ensure_ascii=False, indent=2), encoding="utf-8")
            usage.append({key: value for key, value in account.summary().items() if key != "cost_cny"})
            message = response["response"]["choices"][0]["message"]
            new_rows, calls = execute_response(message, executor)
            rows += new_rows
            log.extend(calls)
            if not calls:
                final = str(message.get("content") or "")
                break
            previous = emitted
            if turn % 2 == 1:
                working.compact_cursor = len(rows)
                working.c1_frozen_until = len(rows)
                folds += 1
                if restarts == 0:
                    live._STATE.clear()
                    current = latest_todo_snapshot(rows)
                    executor = Executor(root, current.records)
                    restarts += 1
                previous = None
            (root / "trace.json").write_text(json.dumps({"rows": rows, "calls": log, "usage": usage, "emissions": emissions}, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "trace.json").write_text(json.dumps({"rows": rows, "calls": log, "usage": usage, "emissions": emissions}, ensure_ascii=False, indent=2), encoding="utf-8")
    verification = executor.execute("Bash", {"command": "py -3.11 verify.py all"})
    try:
        artifact = json.loads((root / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        artifact = {}
    snapshot = latest_todo_snapshot(rows)
    status = {item.get("id"): item["status"] for item in snapshot.records}
    acceptance = {"arithmetic_verified": not verification["is_error"],
        **verification_association(rows, artifact),
        "report_completed_steps": artifact.get("completed_task_ids") == ["price", "refund"] and artifact.get("result") == "passed",
        "committed_completion": all(status.get(uid) == "completed" for uid in ("price", "refund", "report")),
        "model_terminated": bool(final.strip()),
        "immutable_fixture_unchanged": all(digest(root / name) == value for name, value in frozen_files.items()),
        "cold_restart_exercised": restarts == 1,
        "repeated_fold_exercised": folds >= 2,
        "no_old_task_write_attempt": not any(entry["name"] in {"Edit", "Write"} and "legacy" in str(entry["arguments"]) for entry in log)}
    last_commit = max((index for index, entry in enumerate(log)
        if entry["name"] == "TodoWrite" and not entry["is_error"]), default=-1)
    post_completion = log[last_commit + 1:] if acceptance["committed_completion"] and last_commit >= 0 else []
    return {"acceptance": acceptance, "calls": log, "usage": usage, "emissions": emissions,
            "post_completion_tool_calls": len(post_completion),
            "post_completion_verification_calls": sum(entry["name"] == "Bash" for entry in post_completion),
            "final": final, "report": artifact, "final_verification": verification, "final_todo_status": status}


def run(output, model=None, max_turns=12, selected_arm="both"):
    from evals.client import MODEL_ID
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    previous = {key: os.environ.get(key) for key in ("XEYO_WSC_TASK_CONTINUITY", "XEYO_WSC_FAILURE_FACTS")}
    report = {"scope": "real model/product tools, isolated arithmetic fixture, forced folds and executor cold restart",
        "model": model or MODEL_ID, "arms": {}, "compression_model_calls": 0, "live_files_modified": False}
    report["selected_arm"] = selected_arm
    try:
        os.environ["XEYO_WSC_FAILURE_FACTS"] = "1"
        for label, flag in (("before", "0"), ("after", "1")):
            if selected_arm not in {"both", label}:
                continue
            with arm("1", output / label / "home"):
                report["arms"][label] = run_arm(output / label / "task", flag, model=model, max_turns=max_turns)
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"arm": label, "acceptance": report["arms"][label]["acceptance"]}), flush=True)
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
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--arm", choices=("both", "before", "after"), default="both")
    args = parser.parse_args()
    run(args.output, args.model, args.max_turns, args.arm)
