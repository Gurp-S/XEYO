from copy import deepcopy
import json

import pytest

from tests.wsc._fixtures import msg_asst_use, msg_tool
from tests.wsc.test_task_continuity import receipt, task
from synaptic.task_checkpoint import validate as checkpoint_validate
from memory.wsc_handoff_validation import validate


DESIGN = "先给方案，不能修改代码。"
DURABLE = "金额只能使用整数分；验收必须引用实际回执。"


def sources():
    return [{"id": "design", "role": "user", "content": DESIGN},
            {"id": "permit", "role": "user", "content": "现在允许旁路实施；" + DURABLE},
            {"id": "plan", "role": "assistant", "content": "待完成：汇报实际验证结果。"},
            msg_asst_use("verify", "Bash", {"command": "check amounts"}),
            msg_tool("verify", "Bash", "precision failed", is_error=True)]


def declaration():
    return {"todos": [task("report", "in_progress")], "checkpoint": {
        "objective": "实施并汇报金额验证", "context_message_ids": ["design", "permit", "plan"],
        "decisions": [{"source_message_id": "design", "quote": DESIGN},
                      {"source_message_id": "permit", "quote": "现在允许旁路实施"}],
        "constraints": [{"source_message_id": "design", "quote": DESIGN},
                        {"source_message_id": "permit", "quote": DURABLE}],
        "verification_call_ids": ["verify"], "phase_state": {
            "current_phase_id": "implementation", "phases": [
                {"id": "design", "name": "设计", "source_message_ids": ["design"]},
                {"id": "implementation", "name": "实施", "source_message_ids": ["permit"]}],
            "active_context_message_ids": ["permit", "plan"], "fact_scopes": {
                "decisions": [{"kind": "phase", "phase_id": "design"}, {"kind": "phase", "phase_id": "implementation"}],
                "constraints": [{"kind": "phase", "phase_id": "design"}, {"kind": "task"}]}}}}


def test_scope_projection_retires_only_declared_phase_and_keeps_durable_fact_and_failure(tmp_path):
    from synaptic.project import project
    from synaptic.coldstore import node_group_handle
    from evals.stale_goal_ab import tool_read
    from memory.wsc_projection import production_params
    rows = sources() + receipt("checkpoint", declaration()["todos"], declaration()["checkpoint"])
    before = deepcopy(rows)
    output = project(rows, region_end=len(rows), params=production_params(), view_path=tmp_path / "cold.txt")
    state = json.loads(next(pin.text for pin in output.result.hot.pins if pin.key == "task_checkpoint"))
    assert state["declared_constraints"] == [{"source_message_id": "permit", "quote": DURABLE}]
    assert [row["message_id"] for row in state["context_sources"]] == ["permit", "plan"]
    assert state["historical_fact_count"] == 2
    assert state["verification_receipts"][0]["result"] == "precision failed"
    assert DESIGN not in output.text and DURABLE in output.text
    _, ranges = output.cold.render_text_view()
    first, last = ranges[node_group_handle((0,))]
    result = tool_read({"file_path": output.view_path, "offset": first, "limit": last-first+1}, tmp_path)
    assert not result["is_error"] and DESIGN in result["content"]
    assert rows == before


@pytest.mark.parametrize("broken", ["unbound_active", "missing_scope", "unknown_phase", "duplicate_fact", "unbound_provenance"])
def test_inconsistent_scopes_cannot_publish_current_state(broken):
    raw = declaration()["checkpoint"]
    phase = raw["phase_state"]
    if broken == "unbound_active": phase["active_context_message_ids"].append("missing")
    if broken == "missing_scope": phase["fact_scopes"]["constraints"].pop()
    if broken == "unknown_phase": phase["fact_scopes"]["constraints"][0]["phase_id"] = "missing"
    if broken == "duplicate_fact": raw["constraints"].append(deepcopy(raw["constraints"][0]))
    if broken == "unbound_provenance": phase["phases"][0]["source_message_ids"] = ["missing"]
    with pytest.raises(ValueError): checkpoint_validate(raw)


def test_retrieving_a_historical_source_does_not_reactivate_its_phase_constraint():
    from synaptic.task_phase import applicable
    raw = declaration()["checkpoint"]
    raw["phase_state"]["active_context_message_ids"].append("design")
    value = checkpoint_validate(raw)
    assert DESIGN not in [fact["quote"] for fact in applicable(value, "constraints")]
    assert DURABLE in [fact["quote"] for fact in applicable(value, "constraints")]


def test_phase_alias_is_bound_to_original_user_not_later_followup():
    from memory.wsc_handoff_bindings import basis
    from tests.wsc._fixtures import declared_report_phase
    checkpoint = {"objective": "报告", "context_message_ids": ["@latest_user"],
                  "phase_state": declared_report_phase("@latest_user")}
    rows = [{"id": "original", "role": "user", "content": "完成报告。"}]
    rows += receipt("checkpoint", [task("report", "in_progress")], checkpoint)
    rows.append({"id": "later", "role": "user", "content": "继续"})
    before = deepcopy(rows)
    phase = basis(rows)["phase_state"]
    assert phase["phases"][0]["source_message_ids"] == ["original"]
    assert phase["active_context_message_ids"] == ["original"]
    assert rows == before


def test_retired_phase_cannot_inherit_authority_from_latest_receipt():
    from memory.wsc_handoff_facts import committed_facts
    from synaptic.task_fact_sources import resolve
    rows = sources() + receipt("checkpoint", declaration()["todos"], declaration()["checkpoint"])
    rows[-1]["id"] = "committed"
    facts = committed_facts(rows)["committed"]
    assert DESIGN not in facts["constraints"] and DURABLE in facts["constraints"]
    assert resolve(rows, "committed", "constraints", DESIGN) is None
    assert resolve(rows, "committed", "constraints", DURABLE) is not None


@pytest.mark.parametrize("role", ["user", "assistant"])
def test_phase_switch_requires_new_provenance_not_old_words(role):
    rows = sources() + receipt("checkpoint", declaration()["todos"], declaration()["checkpoint"])
    rows[-1]["id"] = "phase-checkpoint"
    raw = declaration()
    phase = raw["checkpoint"]["phase_state"]
    phase["current_phase_id"] = "design"
    phase["active_context_message_ids"] = ["design", "plan"]
    with pytest.raises(ValueError, match="handoff_phase_transition_source_missing"):
        validate(raw, rows)
    rows.append({"id": "resume", "role": role, "content": "回到设计阶段重新复审方案。"})
    raw["checkpoint"]["context_message_ids"].append("resume")
    phase["phases"][0]["source_message_ids"].append("resume")
    assert validate(raw, rows).checkpoint["phase_state"]["current_phase_id"] == "design"
    assert raw["checkpoint"]["phase_state"]["fact_scopes"]["constraints"][1] == {"kind": "task"}


@pytest.mark.parametrize("broken", [None, "duplicate", "cancelled"])
def test_new_tool_receipt_can_ground_phase_without_fabricating_human_instruction(broken):
    rows = sources() + receipt("checkpoint", declaration()["todos"], declaration()["checkpoint"])
    rows[-1]["id"] = "phase-checkpoint"
    rows += [msg_asst_use("new-verify", "Bash", {"command": "verify current revision"}),
             dict(msg_tool("new-verify", "Bash", "failed current verification", is_error=True), id="new-result")]
    if broken == "duplicate": rows.append(msg_tool("new-verify", "Bash", "duplicate"))
    if broken == "cancelled": rows[-1]["content"][0]["execution"] = {"status": "cancelled"}
    raw = declaration()
    raw["checkpoint"]["context_message_ids"].append("new-result")
    phase = raw["checkpoint"]["phase_state"]
    phase["current_phase_id"] = "verification"
    phase["phases"].append({"id": "verification", "name": "验收", "source_message_ids": ["new-result"]})
    if broken:
        with pytest.raises(ValueError, match="handoff_phase_source_invalid"): validate(raw, rows)
    else:
        assert validate(raw, rows).checkpoint["phase_state"]["current_phase_id"] == "verification"


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_scope_generation_requires_declaration_before_real_tool_commit(tmp_path, monkeypatch, native):
    from engine.abort import AbortController
    from memory.wsc_handoff_generation import generate
    from memory.wsc_handoff_transaction import commit
    from memory.working import WorkingSnapshot
    from model.chunks import ModelChunk
    from msgtypes.message import ToolUse
    from evals.wsc_flash_compact_chain import native_store
    from session.compression_source import compression_messages
    from tools.tool_registry import ToolRegistry
    from tools.todo_write_tool.todo_write_tool import TodoWriteTool
    rows = sources()
    store = native_store(rows)
    source = lambda: compression_messages(store, WorkingSnapshot())
    before = deepcopy(source())
    attempts, persisted = [], []
    class Model:
        context_limit = 100000
        last_usage = None
        def for_handoff(self, max_tokens): return self
        async def stream(self, messages, tools, abort):
            raw = declaration()
            if not attempts:
                raw["checkpoint"].pop("phase_state")
            else:
                assert json.loads(messages[-1]["content"][0]["content"])["error"] == "handoff_phase_state_required"
                assert source() == before
            attempts.append(deepcopy(messages))
            yield ModelChunk(kind="tool_use", tool_use=ToolUse(f"declare-{len(attempts)}", "TodoWrite", raw))
    tools = ToolRegistry(cwd=str(tmp_path))
    tools.register(TodoWriteTool(cwd=str(tmp_path)))
    import importlib
    transcript = importlib.import_module("session.record_transcript")
    path, known = tmp_path / "phase.jsonl", set()
    def persist():
        persisted.append(deepcopy(source()))
        transcript.record_transcript_sync(store.items, session_id="phase", path=path, known_ids=known)
    transcript.record_transcript_sync(store.items, session_id="phase", path=path, known_ids=known)
    prefix = path.read_bytes()
    async def declare(captured):
        return await generate(Model(), rows, captured, TodoWriteTool().schema(), AbortController(),
                              account=lambda usage: None, scope_protocol=True)
    result = await commit(source=source, generate=declare, store=store, tools=tools, abort=AbortController(),
                          persist=persist)
    assert result["call_id"] == "declare-2" and len(attempts) == 2 and len(persisted) == 2
    assert source()[:len(before)] == before
    from synaptic.todo_snapshot import latest_todo_snapshot
    assert latest_todo_snapshot(source()).checkpoint["phase_state"] == declaration()["checkpoint"]["phase_state"]
    assert path.read_bytes().startswith(prefix)
    from session.transcript_blobs import resolve_transcript_rows
    restored = [dict(row, message_id=row.get("id")) for row in resolve_transcript_rows(transcript.load_transcript(path), path)]
    assert latest_todo_snapshot(restored).checkpoint["phase_state"] == declaration()["checkpoint"]["phase_state"]
    from synaptic.project import project
    from memory.wsc_projection import production_params
    projection = project(restored, region_end=len(restored), params=production_params(), view_path=tmp_path / "restored.txt")
    state = json.loads(next(pin.text for pin in projection.result.hot.pins if pin.key == "task_checkpoint"))
    assert state["declared_constraints"] == [{"source_message_id": "permit", "quote": DURABLE}]
    assert DESIGN not in projection.text and DURABLE in projection.text
    from memory.runtime import force_compact, project_for_model
    from memory import wsc_projection
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XEYO_WSC", str(int(native)))
    wsc_projection._STATE.clear()
    full = restored + [{"id": f"archive-{i}", "role": "assistant", "content": "执行记录" + "x" * 1000} for i in range(35)]
    working = WorkingSnapshot(session_id="phase-" + str(native))
    emitted = force_compact(full, working, cwd=tmp_path)
    assert working.compact_cursor > 0
    assert "当前阶段（声明）" in emitted[0]["content"] and DURABLE in emitted[0]["content"]
    frozen = emitted[0]["content"]
    full.append({"id": "later", "role": "assistant", "content": "追加观察事实"})
    assert project_for_model(full, working, cwd=tmp_path)[0]["content"] == frozen
    assert path.read_bytes().startswith(prefix)
