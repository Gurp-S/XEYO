import json
import pytest

from tests.wsc.test_task_continuity import receipt, task
from tests.wsc._fixtures import msg_asst_use, msg_tool
from synaptic.project import project
from memory.wsc_projection import production_params


def evidence(identity, text, error):
    return [msg_asst_use(identity, "Bash", {"command": "verify revision"}),
            msg_tool(identity, "Bash", text, is_error=error)]


def state_of(output):
    return json.loads(next(pin.text for pin in output.result.hot.pins if pin.key == "task_checkpoint"))


def initial():
    return evidence("bound", "failed precision verification", True) + receipt(
        "checkpoint", [task("verify", "in_progress")],
        {"objective": "当前任务", "verification_call_ids": ["bound"]})


def test_completed_declaration_retains_bound_failure_despite_unrelated_success(tmp_path):
    rows = initial() + evidence("unbound", "later check passed", False)
    rows += receipt("complete", [task("verify", "completed")])
    output = project(rows, region_end=len(rows), params=production_params(), view_path=tmp_path / "cold.txt")
    state = state_of(output)
    assert not state["declared_objective"] and not state["verification_receipts"]
    terminal = state["terminal_task"]
    assert terminal["kind"] == "completed"
    assert terminal["verification_call_ids"] == ["bound"]
    bound = terminal["verification_receipts"]
    assert len(bound) == 1 and bound[0]["is_error"] is True
    assert bound[0]["result"] == "failed precision verification"
    assert "检查点绑定验收" in output.text
    assert '目标（声明）: "当前任务"' not in output.text


def test_explicit_completed_checkpoint_selects_new_verification(tmp_path):
    rows = initial() + evidence("new", "new revision passed", False)
    rows += receipt("complete", [task("verify", "completed")],
                    {"objective": "当前任务", "verification_call_ids": ["new"]})
    output = project(rows, region_end=len(rows), view_path=tmp_path / "cold.txt")
    terminal = state_of(output)["terminal_task"]
    assert terminal["verification_call_ids"] == ["new"]
    assert terminal["verification_receipts"][0]["call_id"] == "new"
    assert terminal["verification_receipts"][0]["is_error"] is False


def test_unknown_terminal_verification_does_not_infer_success(tmp_path):
    rows = evidence("duplicate", "first failed", True) + evidence("duplicate", "second passed", False)
    rows += receipt("complete", [task("verify", "completed")],
                    {"objective": "当前任务", "verification_call_ids": ["duplicate", "missing"]})
    output = project(rows, region_end=len(rows), view_path=tmp_path / "cold.txt")
    terminal = state_of(output)["terminal_task"]
    assert terminal["verification_receipts"] == []
    assert {item["call_id"] for item in terminal["unknown_verification_sources"]} == {"duplicate", "missing"}
    assert "未知验收来源" in output.text


def test_large_terminal_receipt_is_recoverable_by_real_read(tmp_path):
    from evals.stale_goal_ab import tool_read
    from synaptic.coldstore import node_group_handle
    body = "详细失败验收：" + "actual receipt data;" * 400
    rows = evidence("large", body, True)
    rows += receipt("complete", [task("verify", "completed")],
                    {"objective": "当前任务", "verification_call_ids": ["large"]})
    output = project(rows, region_end=len(rows), params=production_params(), view_path=tmp_path / "cold.txt")
    bound = state_of(output)["terminal_task"]["verification_receipts"][0]
    assert not bound["result_inline"] and "result" not in bound
    _, ranges = output.cold.render_text_view()
    first, last = ranges[node_group_handle((bound["source"],))]
    result = tool_read({"file_path": output.view_path, "offset": first, "limit": last-first+1}, tmp_path)
    assert not result["is_error"] and body in result["content"]


@pytest.mark.parametrize("status", ["in_progress", "completed"])
def test_large_verification_input_has_separate_exact_recall_and_keeps_result(tmp_path, status):
    from copy import deepcopy
    from evals.stale_goal_ab import tool_read
    from synaptic.coldstore import node_group_handle
    command = "源文件内容🙂\\n" * 1400
    rows = [msg_asst_use("verify-large-input", "Edit", {"new_string": command}),
            msg_tool("verify-large-input", "Edit", "verification failed", is_error=True)]
    rows += receipt("state", [task("verify", status)],
                    {"objective": "当前任务", "verification_call_ids": ["verify-large-input"]})
    before = deepcopy(rows)
    output = project(rows, region_end=len(rows), params=production_params(), view_path=tmp_path / "cold.txt")
    state = state_of(output)
    scope = state if status == "in_progress" else state["terminal_task"]
    bound = scope["verification_receipts"][0]
    assert bound["input_inline"] is False and "input" not in bound
    assert bound["result"] == "verification failed" and bound["is_error"] is True
    assert "调用来源=" in output.text and command not in output.text
    _, ranges = output.cold.render_text_view()
    first, last = ranges[node_group_handle((bound["input_source"],))]
    recovered = tool_read({"file_path": output.view_path, "offset": first, "limit": last-first+1}, tmp_path)
    assert not recovered["is_error"]
    assert json.dumps(command, ensure_ascii=False)[1:-1] in recovered["content"] or command in recovered["content"]
    assert rows == before


def test_verification_inputs_and_results_share_total_byte_allowance():
    from synaptic.task_verification import collect
    rows = evidence("a", "small-result", False) + evidence("b", "small-result", False)
    receipts, unknown, nodes = collect(rows, ["a", "b"], len(rows), inline_bytes=55)
    assert not unknown and len(nodes) == 4
    assert all("input_source" in row for row in receipts)
    assert sum(row["result_bytes"] for row in receipts if row["result_inline"]) + sum(
        row["input_bytes"] for row in receipts if row["input_inline"]) <= 55
