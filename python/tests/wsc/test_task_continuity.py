"""Task state and pressure survive continuation without reviving old requests."""
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from synaptic.project import project
from synaptic.task_checkpoint import canonical, project_state
from synaptic.types import WscParams
from synaptic.graph import build_graph
from tests.wsc._fixtures import msg_user, msg_asst_use, msg_tool
from tools.todo_write_tool.todo_write_tool import TodoWriteTool, TodoWriteInput, parse_input
from tools.todo_write_tool.types import TodoItem


def receipt(uid, items, checkpoint=None):
    tool = TodoWriteTool()
    parsed = parse_input({"todos": items, **({"checkpoint": checkpoint} if checkpoint is not None else {})})
    assert isinstance(parsed, TodoWriteInput)
    out = tool.call(parsed)
    return [msg_asst_use(uid, "TodoWrite", {"todos": items}),
            msg_tool(uid, "TodoWrite", tool.map_tool_result_to_content(out))]


def task(uid="batch2", status="pending", text="第二批：工具、类别、目标身份贯穿匹配"):
    return {"id": uid, "content": text, "status": status, "activeForm": "核对身份", "output": "report.json"}


def assert_receipt_body_intact(actual, original):
    import copy
    restored = copy.deepcopy(actual)
    for block in restored["content"]:
        if block.get("type") == "tool_result":
            header, block["content"] = block["content"].split("\n", 1)
            assert header == "执行回执身份=" + json.dumps({"call_id": block["tool_use_id"]}, separators=(",", ":"))
    assert restored == original


def test_committed_checkpoint_keeps_plan_progress_decision_and_receipt_not_old_goal(monkeypatch):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    old = dict(msg_user("旧 ChatGPT 任务"), id="old")
    plan = dict(msg_user("第一批接线\n第二批不能只改一半\n验收：噪声不进，真坑不漏"), id="plan")
    rows = [old, plan, msg_asst_use("verify", "Bash", {"command": "pytest checks.py"}),
            msg_tool("verify", "Bash", "12 passed", is_error=False)]
    checkpoint = {"context_message_ids": ["plan"], "decisions": ["存在性过滤已否决；采用声明来源"],
                  "verification_call_ids": ["verify"]}
    rows += receipt("todo", [task("batch1", "completed"), task()], checkpoint)
    rows += [msg_user("继续")]
    output = project(rows, region_end=len(rows))
    pin = next(p for p in output.result.hot.pins if p.key == "task_checkpoint")
    state = json.loads(pin.text)
    assert state["context_sources"][0]["text"] == plan["content"]
    assert [t["status"] for t in state["items"]] == ["completed", "pending"]
    assert state["declared_decisions"] == checkpoint["decisions"]
    assert state["verification_receipts"][0]["call_id"] == "verify"
    assert old["content"] not in pin.text
    assert "\n".join("    " + line for line in plan["content"].split("\n")) in output.text
    assert not any(p.key == "goal" for p in output.result.hot.pins)


def test_completion_and_replacement_do_not_revive_previous_decisions(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    rows = [dict(msg_user("当前方案"), id="plan")]
    rows += receipt("initial", [task()], {"context_message_ids": ["plan"], "decisions": ["原决定"]})
    from memory.wsc_projection import production_params
    params = production_params()
    view = tmp_path / "cold.txt"
    previous = project(rows, region_end=len(rows), params=params, view_path=view)
    for extra in (receipt("complete", [task(status="completed")]), receipt("clear", [])):
        output = project(rows + extra, region_end=len(rows + extra), prev=previous.state,
            cold=previous.cold, params=params, view_path=view)
        state = json.loads(next(p.text for p in output.result.hot.pins if p.key == "task_checkpoint"))
        assert not state["declared_decisions"] and not state["context_sources"]
        assert "原决定" not in output.text


@pytest.mark.parametrize("missing", ["missing", "duplicate"])
def test_ambiguous_or_missing_sources_remain_unknown(monkeypatch, missing):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    rows = [dict(msg_user("A"), id="same"), dict(msg_user("B"), id="same")]
    rows += receipt("todo", [task()], {"context_message_ids": ["same" if missing == "duplicate" else "absent"]})
    state, _ = project_state(rows, build_graph(rows))
    assert state["unknown_sources"] and not state["context_sources"]


def test_committed_todo_survives_size_prune_in_actual_emission(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    monkeypatch.setenv("XEYO_WSC_SIZE_PRUNE", "1")
    from memory.wsc_projection import _emit
    rows = [msg_user("检查")]+receipt("todo", [task(text="需求 " + "x" * 4500)])
    actual = _emit("frozen", rows, 0, 0, cwd=str(tmp_path), session="")
    assert_receipt_body_intact(actual[-1], rows[-1])


def test_pressure_uses_current_emission_not_archived_history(monkeypatch):
    from memory.wsc_pressure_admission import assess
    monkeypatch.delenv("XEYO_WSC_SOFT_WATERMARK", raising=False)
    w = SimpleNamespace(compact_cursor=500, last_prompt_tokens=1_184_044,
        last_projection_manifest={"compact_cursor": 400, "estimated_tokens": 1_150_000})
    p = SimpleNamespace(reserve_tokens=16000)
    result = assess([msg_user("现在只有几百字")], w, context_limit=1_000_000, system_prompt="事实", params=p)
    assert not result["admitted"] and result["forecast_tokens"] < 20000
    result = assess([msg_user("x" * 3_400_000)], w, context_limit=1_000_000, system_prompt="事实", params=p)
    assert result["admitted"]


def test_pressure_calibration_requires_current_request_receipt_provenance(monkeypatch):
    from memory.wsc_pressure_admission import assess
    monkeypatch.delenv("XEYO_WSC_SOFT_WATERMARK", raising=False)
    w = SimpleNamespace(compact_cursor=500, last_prompt_tokens=1_184_044,
        last_projection_manifest={"compact_cursor": 500, "estimated_tokens": 2000})
    params = SimpleNamespace(reserve_tokens=16000)
    legacy = assess([msg_user("当前很短")], w, context_limit=1_000_000, system_prompt="事实", params=params)
    assert not legacy["admitted"]
    w.last_projection_manifest.update(context_receipt_cursor=500, context_receipt_basis="provider_current_request")
    measured = assess([msg_user("当前很短")], w, context_limit=1_000_000, system_prompt="事实", params=params)
    assert measured["admitted"] and measured["overhead_tokens"] == 1_182_044


@pytest.mark.parametrize("action", ["C1", "C2"])
def test_early_compression_refused_through_real_runtime(monkeypatch, mem_switch, action):
    from tests.wsc.test_fold_gate_coverage import _press, _big_msgs
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    w = _press(monkeypatch, mem_switch, msgs=_big_msgs(12), cursor=0,
               action=action, context_limit=1_000_000)
    assert w.compact_cursor == 0 and w.c1_frozen_until == 0


def test_failed_todo_input_and_open_intent_cannot_replace_committed_state(monkeypatch):
    from tools.todo_write_tool.restore import restore_todos_from_messages
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    rows = receipt("ok", [task()]) + [msg_asst_use("bad", "TodoWrite", {"todos": []}),
            msg_tool("bad", "TodoWrite", "failed", is_error=True),
            msg_asst_use("open", "TodoWrite", {"todos": []})]
    assert restore_todos_from_messages(rows)[0].id == "batch2"
    assert restore_todos_from_messages(rows + receipt("clear", [])) == []


def test_checkpoint_schema_available_in_main_flow(monkeypatch):
    monkeypatch.delenv("XEYO_WSC_TASK_CONTINUITY", raising=False)
    assert "checkpoint" in TodoWriteTool().schema()["input_schema"]["properties"]
    assert isinstance(parse_input({"todos": [], "checkpoint": {}}), TodoWriteInput)
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    assert "checkpoint" in TodoWriteTool().schema()["input_schema"]["properties"]
    assert isinstance(parse_input({"todos": [], "checkpoint": {"decisions": ["已决定"]}}), TodoWriteInput)


def test_observed_failed_payload_is_not_a_committed_checkpoint(monkeypatch):
    from synaptic.todo_snapshot import latest_todo_snapshot
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    rows = receipt("old", [task()]) + receipt("failed", [])
    rows[-1]["content"][0]["execution"] = {"status": "error", "complete": True}
    assert latest_todo_snapshot(rows).source == 1


def test_later_unstructured_acknowledgement_does_not_erase_committed_state(monkeypatch):
    from synaptic.todo_snapshot import latest_todo_snapshot
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    rows = receipt("old", [task()], {"decisions": ["已否决的方案"]})
    rows += [msg_asst_use("legacy", "TodoWrite", {"todos": []}),
             msg_tool("legacy", "TodoWrite", "ok")]
    state = latest_todo_snapshot(rows)
    assert state.observed and state.source == 1
    assert state.checkpoint["decisions"] == ["已否决的方案"]


def test_failed_legacy_standalone_receipt_is_not_restored():
    from tools.todo_write_tool.committed_restore import restore
    raw = {"role": "tool", "name": "TodoWrite", "content": "<todo_list>" + canonical([task()]) + "</todo_list>",
           "execution": {"status": "error", "complete": True}}
    assert restore([raw]) == []


def test_merge_progress_inherits_checkpoint_but_replacement_and_clear_do_not(monkeypatch):
    from synaptic.todo_snapshot import latest_todo_snapshot
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    initial = receipt("initial", [task()], {"decisions": ["存在性方案已否决"]})
    update = receipt("progress", [task(status="in_progress")])
    update[0]["content"][0]["input"]["merge"] = True
    state = latest_todo_snapshot(initial + update)
    assert state.source == 3 and state.checkpoint_source == 1
    assert state.checkpoint["decisions"] == ["存在性方案已否决"]
    assert latest_todo_snapshot(initial + receipt("replace", [task("new")])).checkpoint is None
    assert latest_todo_snapshot(initial + receipt("clear", []) + update).checkpoint is None
    explicit = receipt("explicit", [task()], {})
    explicit[0]["content"][0]["input"]["merge"] = True
    assert not latest_todo_snapshot(initial + explicit).checkpoint["decisions"]


def test_merge_receipt_and_original_checkpoint_survive_unfrozen_tail(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    monkeypatch.setenv("XEYO_WSC_SIZE_PRUNE", "1")
    from memory.wsc_projection import _emit
    initial = receipt("initial", [task()], {"decisions": ["决定" + "x" * 4500]})
    update = receipt("progress", [task(status="in_progress")])
    update[0]["content"][0]["input"]["merge"] = True
    rows = initial + update
    actual = _emit("frozen", rows, 0, 0, cwd=str(tmp_path), session="")
    assert_receipt_body_intact(actual[2], initial[-1])
    assert_receipt_body_intact(actual[4], update[-1])


def test_quoted_history_is_not_promoted_to_constraint_authority(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    proposal = "别人方案：必须修复旧 ChatGPT 问题；但这个问题我已经自己修好了。"
    rows = [dict(msg_user(proposal), id="proposal"), msg_user("现在核对第二批")]
    rows += receipt("current", [task()], {"constraints": ["当前任务保持前缀不变"]})
    from memory.wsc_projection import production_params
    output = project(rows, region_end=len(rows), params=production_params(), view_path=tmp_path / "cold.txt")
    assert not output.seeds.constraints
    candidates = next(p for p in output.result.hot.pins if p.key == "constraint_candidates")
    assert candidates.nodes == (0,) and "validity=unobserved" in candidates.text
    assert proposal not in output.text
    state = json.loads(next(p.text for p in output.result.hot.pins if p.key == "task_checkpoint"))
    assert state["declared_constraints"] == ["当前任务保持前缀不变"]
    from synaptic.coldstore import node_group_handle
    assert len(output.cold.expand(node_group_handle(candidates.nodes))) == 1


def test_source_alias_stays_at_declaration_across_merge_and_short_followup(monkeypatch):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    plan = msg_user("第二批完整计划，先验证身份再对比结果")
    rows = [plan] + receipt("initial", [task()], {"objective": "第二批身份闭环", "context_message_ids": ["@latest_user"]})
    rows += [msg_user("继续")]
    update = receipt("progress", [task(status="in_progress")])
    update[0]["content"][0]["input"]["merge"] = True
    rows += update
    state, nodes = project_state(rows, build_graph(rows))
    assert state["declared_objective"] == "第二批身份闭环"
    assert state["context_sources"][0]["source"] == 0
    assert state["context_sources"][0]["text"] == plan["content"]
    assert 0 in nodes


def test_handoff_distinguishes_declared_completion_and_failed_execution(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    rows = [msg_user("当前明确任务")]
    rows += [msg_asst_use("verify", "Bash", {"command": "pytest checks.py"}),
             msg_tool("verify", "Bash", "exit code 1", is_error=True)]
    rows += receipt("todo", [task("first", "completed"), task()],
                    {"objective": "核对第二批", "context_message_ids": ["@latest_user"],
                     "decisions": ["存在性方案已否决"], "verification_call_ids": ["verify"]})
    from memory.wsc_projection import production_params
    result = project(rows, region_end=len(rows), params=production_params(), view_path=tmp_path / "cold.txt")
    text = result.text
    assert "任务交接快照：" in text and '目标（声明）: "核对第二批"' in text
    assert 'id="first"' in text and 'id="batch2"' in text
    assert "已完成（声明）: 1 项" in text and "执行回执: 1 项" in text
    assert '"is_error":true' in text and '"call_id":"verify"' in text
    assert '原文:\n    当前明确任务' in text
    from evals.wsc_task_continuity_ab import emission_cost
    cost = emission_cost(text)
    assert cost["partition_exact"] and cost["utf8_bytes"]["task_state"] > 0
    assert cost["utf8_bytes"]["original_context_sources"] > 0


def test_behavior_grader_does_not_call_source_id_confusion_old_goal_revival():
    from evals.wsc_handoff_behavior import grade
    truth = {"task_id": "batch2", "objective": "身份修复", "decisions": ["否决 A"],
             "completed_ids": ["batch1"], "verification_ids": ["verify"]}
    result = grade(dict(truth, task_id="#4", verification_ids=["#3"]), truth)
    assert result["correct"] == 3 and result["wrong_task_identity"]
    assert not result["old_goal_selected"]
    assert not grade(dict(truth, decisions=[{}]), truth)["fields"]["decisions"]


def test_stale_sidecar_yields_to_commit_and_empty_barrier(monkeypatch):
    from tools.todo_write_tool.committed_restore import reconcile
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    snapshot = SimpleNamespace(todos=[task("old")])
    assert reconcile(snapshot, receipt("current", [task("new")]))
    assert snapshot.todos[0]["id"] == "new"
    assert reconcile(snapshot, receipt("current", []))
    assert snapshot.todos == []
    snapshot.todos = [task("unchanged")]
    assert not reconcile(snapshot, [msg_asst_use("open", "TodoWrite", {"todos": []})])
    assert snapshot.todos[0]["id"] == "unchanged"


def test_source_identity_survives_production_reader_without_mutating_api(monkeypatch):
    from session.message_store import MessageStore
    from session.compression_source import compression_messages
    from memory.working import WorkingSnapshot
    from msgtypes.message import user_message
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    message = user_message("任务原文")
    store = MessageStore([message])
    rows = compression_messages(store, WorkingSnapshot())
    assert rows[0]["message_id"] == message.id
    assert "message_id" not in store.as_api_messages()[0]


def test_pressure_force_does_not_use_prefold_receipt_after_cursor_change(monkeypatch, tmp_path):
    from memory import runtime
    from memory.working import WorkingSnapshot
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    monkeypatch.setattr(runtime, "_wsc_owns_emission", lambda: True)
    monkeypatch.setattr(runtime, "apply_c2_messages", lambda *a, **k: [msg_user("当前紧凑投影")])
    w = WorkingSnapshot(session_id="guard")
    w.compact_cursor = 500
    w.last_prompt_tokens = 1_184_044
    w.last_projection_manifest = {"compact_cursor": 400, "estimated_tokens": 1_150_000}
    monkeypatch.setattr(runtime, "force_compact", lambda *a, **k: pytest.fail("unnecessary force"))
    assert not runtime.maybe_force_compact_on_pressure([msg_user("x" * 4_500_000)], w,
        context_limit=1_000_000, cwd=str(tmp_path))


def test_failure_index_preserves_all_invocations_and_explicit_verification_remains_visible(monkeypatch):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    rows = [msg_user("当前任务")]
    for uid in ("old1", "old2", "current"):
        rows.extend([msg_asst_use(uid, "Bash", {"command": "pytest " + uid + ".py"}),
                     msg_tool(uid, "Bash", "exit code 1", is_error=True)])
    rows += receipt("task", [task()], {"verification_call_ids": ["current"]})
    output = project(rows, region_end=len(rows))
    archive = next(p for p in output.result.hot.pins if p.key == "failure_archive")
    current = [p for p in output.result.hot.pins if p.key.startswith("unresolved:")]
    assert len(current) == 1 and current[0].nodes == (6,)
    assert {1, 2, 3, 4} <= set(archive.nodes)
    from synaptic.coldstore import node_group_handle
    assert len(output.cold.expand(node_group_handle(archive.nodes))) == 4
    assert output.seeds.unresolved_source_groups == ((2,), (4,), (6,))


def test_checkpoint_sources_outside_fold_region_have_real_cold_origins(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    rows = [dict(msg_user("方案"), id="plan"), msg_user("观察")]
    rows += receipt("tail", [task()], {"context_message_ids": ["plan"]})
    from memory.wsc_projection import production_params
    output = project(rows, region_end=2, params=production_params(), view_path=tmp_path / "cold.txt")
    pin = next(p for p in output.result.hot.pins if p.key == "task_checkpoint")
    from synaptic.coldstore import node_group_handle
    assert len(output.cold.expand(node_group_handle(pin.nodes))) == 2


@pytest.mark.asyncio
async def test_query_loop_records_context_receipt_not_billing_split(monkeypatch, mem_switch):
    from engine.query_loop import query_loop
    from engine.abort import AbortController
    from engine.budget import BudgetTracker
    from model.fake import FakeModelClient
    from memory.working import WorkingSnapshot
    from prompt.assembler import PromptAssembler
    from session.message_store import MessageStore
    from tools.tool_registry import ToolRegistry
    from msgtypes.message import user_message
    mem_switch(XEYO_L5="project")
    model = FakeModelClient()
    model.last_context_tokens = 1200
    model.last_usage = {"prompt_cache_hit_tokens": 500000, "prompt_cache_miss_tokens": 500000}
    snapshot = WorkingSnapshot(session_id="context-test")
    async for _ in query_loop(store=MessageStore([user_message("hi")]), model=model,
        tools=ToolRegistry(), prompt=PromptAssembler(), system_prompt="事实", working=snapshot,
        abort=AbortController(), budget=BudgetTracker(max_turns=1)):
        pass
    assert snapshot.last_prompt_tokens == 1200
