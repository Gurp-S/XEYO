"""Real executor/preflight invariants before paid behavior probes."""
from evals.wsc_execution_behavior import Executor, seed
from evals.wsc_request_projection import arm
from synaptic.todo_snapshot import latest_todo_snapshot


def test_provider_identity_and_parallel_assistant_turn_are_not_rewritten():
    from evals.wsc_execution_behavior import execute_response
    class FakeExecutor:
        def execute(self, name, arguments):
            return {"is_error": False, "content": name}
    response = {"content": "Observed state", "tool_calls": [
        {"id": "vendor-read", "function": {"name": "Read", "arguments": "{}"}},
        {"id": "vendor-verify", "function": {"name": "Bash", "arguments": "{}"}}]}
    rows, calls = execute_response(response, FakeExecutor())
    assert len(rows) == 3 and rows[0]["content"][0]["text"] == "Observed state"
    assert [block["id"] for block in rows[0]["content"][1:]] == ["vendor-read", "vendor-verify"]
    assert [row["content"][0]["tool_use_id"] for row in rows[1:]] == ["vendor-read", "vendor-verify"]
    assert [call["id"] for call in calls] == ["vendor-read", "vendor-verify"]


def test_probe_captures_actual_wire_without_authentication(monkeypatch):
    import io
    import json
    from evals import client
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret-never-persisted")
    payload = {"choices": [{"message": {"content": "Observed", "tool_calls": [
        {"id": "provider-17", "function": {"name": "Read", "arguments": "{}"}}]}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3}}
    monkeypatch.setattr(client.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(json.dumps(payload).encode()))
    account = client.UsageAccount("test")
    wire = client.chat([{"role": "user", "content": "inspect"}], capture_wire=True, acct=account)
    assert wire["response"] == payload and wire["request"]["messages"][0]["content"] == "inspect"
    assert "test-secret-never-persisted" not in json.dumps(wire)
    assert account.prompt_tokens == 12 and account.requests == 1


def test_execution_seed_has_real_pass_failure_and_committed_status(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    with arm("1", tmp_path / "home"):
        rows, records = seed(tmp_path / "task")
        state = latest_todo_snapshot(rows)
        assert state.observed and state.records[0]["status"] == "completed"
        failures = [block for row in rows for block in row.get("content", []) if isinstance(block, dict) and block.get("is_error")]
        assert len(failures) == 1 and "refund boundary" in failures[0]["content"]
        executor = Executor(tmp_path / "task", records)
        assert executor.execute("Read", {"file_path": "payment.py"})["is_error"] is False
        assert executor.execute("Edit", {"file_path": "payment.py", "old_string": "return amount + fee", "new_string": "return amount - fee"})["is_error"] is False
        assert not executor.execute("Bash", {"command": "py -3.11 verify.py all"})["is_error"]
        assert executor.execute("Write", {"file_path": "legacy.txt", "content": "changed"})["is_error"]
        assert executor.execute("Bash", {"command": "arbitrary command"})["is_error"]


def test_post_checkpoint_receipts_keep_actual_ids_without_inferred_completion(monkeypatch, tmp_path):
    from evals.wsc_execution_behavior import event
    from synaptic.task_checkpoint import project_state
    from synaptic.graph import build_graph
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    with arm("1", tmp_path / "home"):
        rows, records = seed(tmp_path / "task")
        executor = Executor(tmp_path / "task", records)
        executor.execute("Read", {"file_path": "payment.py"})
        args = {"file_path": "payment.py", "old_string": "return amount + fee", "new_string": "return amount - fee"}
        rows += event("edit-real", "Edit", args, executor.execute("Edit", args))
        args = {"command": "py -3.11 verify.py all"}
        rows += event("verify-real", "Bash", args, executor.execute("Bash", args))
        state, nodes = project_state(rows, build_graph(rows))
        entries = state["subsequent_executions"]["inline_or_indexed"]
        assert entries[-1]["call_id"] == "verify-real" and entries[-1]["is_error"] is False
        assert "all=passed" in entries[-1]["output"]
        assert entries[-1]["task_association"] == "undeclared"
        assert state["items"][1]["status"] == "in_progress"
        assert len(rows)-1 in nodes and len(rows)-2 in nodes


def test_legacy_checklist_does_not_declare_a_recent_execution_scope(monkeypatch, tmp_path):
    from evals.wsc_execution_behavior import event
    from synaptic.task_checkpoint import project_state
    from synaptic.graph import build_graph
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    with arm("1", tmp_path / "home"):
        rows, records = seed(tmp_path / "task")
        executor = Executor(tmp_path / "task", records)
        args = {"todos": records}  # Replacement has no checkpoint declaration.
        rows += event("legacy-checklist", "TodoWrite", args, executor.execute("TodoWrite", args))
        args = {"command": "py -3.11 verify.py all"}
        rows += event("unbound-verification", "Bash", args, executor.execute("Bash", args))
        state, nodes = project_state(rows, build_graph(rows))
        assert state["context_observed"] is False
        assert "subsequent_executions" not in state
        assert len(rows)-1 not in nodes


def test_receipt_render_is_a_pure_append_stable_projection(monkeypatch):
    import copy
    from synaptic.receipt_render import render
    rows = [{"role": "assistant", "content": "frozen-head"},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "vendor-read", "content": "unchanged"},
            {"type": "tool_result", "tool_use_id": "vendor-verify", "content": "passed"}]}]
    original = copy.deepcopy(rows)
    monkeypatch.delenv("XEYO_WSC_TASK_CONTINUITY", raising=False)
    default = render(rows)
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "0")
    assert render(rows) == default
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    first = render(rows)
    assert first == default
    assert first[0] == rows[0] and rows == original
    assert '"call_id":"vendor-verify"' in first[1]["content"][1]["content"]
    assert first[1]["content"][1]["content"].endswith("\npassed")
    assert render(rows + [{"role": "user", "content": "continue"}])[:len(first)] == first
    assert render(rows) == first


def test_receipt_render_keeps_image_and_literal_header_text(monkeypatch):
    from synaptic.receipt_render import render
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    body = [{"type": "text", "text": '执行回执身份={"call_id":"quoted"}'},
            {"type": "image", "source": {"type": "base64", "data": "AA=="}}]
    rows = [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "actual", "content": body}]}]
    projected = render(rows)[0]["content"][0]["content"]
    assert projected[1:] == body and '"call_id":"actual"' in projected[0]["text"]


def test_completed_task_keeps_terminal_identity_and_commit_bounded_evidence(monkeypatch, tmp_path):
    from evals.wsc_execution_behavior import event
    from synaptic.task_checkpoint import project_state
    from synaptic.graph import build_graph
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    with arm("1", tmp_path / "home"):
        rows, records = seed(tmp_path / "task")
        executor = Executor(tmp_path / "task", records)
        args = {"command": "py -3.11 verify.py price"}
        rows += event("last-before-commit", "Bash", args, executor.execute("Bash", args))
        done = [{**item, "status": "completed"} for item in records]
        args = {"todos": done, "merge": True}
        rows += event("completed-commit", "TodoWrite", args, executor.execute("TodoWrite", args))
        state, nodes = project_state(rows, build_graph(rows))
        terminal = state["terminal_task"]
        assert terminal["kind"] == "completed" and terminal["step_ids"] == ["price", "refund", "report"]
        assert terminal["objective"] == "完成付款算术修复与验证报告"
        assert not state["context_observed"] and not state["declared_objective"]
        assert not state["declared_constraints"] and not state["declared_decisions"]
        assert terminal["preceding_executions"]["inline_or_indexed"][-1]["call_id"] == "last-before-commit"
        assert terminal["commit_source"] in nodes and terminal["checkpoint_source"] in nodes
        args = {"command": "py -3.11 verify.py all"}
        rows += event("late-check", "Bash", args, executor.execute("Bash", args))
        later, _ = project_state(rows, build_graph(rows))
        assert later["terminal_task"] == terminal
        # Declarative completion is not promoted to an arithmetic success.
        assert executor.execute("Bash", args)["is_error"]


def test_clear_and_unrelated_replacement_never_claim_previous_task_completed(monkeypatch, tmp_path):
    from evals.wsc_execution_behavior import event
    from synaptic.task_checkpoint import project_state
    from synaptic.graph import build_graph
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    with arm("1", tmp_path / "home"):
        initial, records = seed(tmp_path / "task")
        for items, kind in [([], "cleared"), ([{**records[0], "id": "new-task", "status": "completed"}], "replaced")]:
            executor = Executor(tmp_path / "task", records)
            args = {"todos": items}
            rows = initial + event("replacement", "TodoWrite", args, executor.execute("TodoWrite", args))
            state, _ = project_state(rows, build_graph(rows))
            assert state["terminal_task"]["kind"] == kind
            assert "preceding_executions" not in state["terminal_task"]
            # An unrelated later completed checklist cannot inherit this scope.
            args = {"todos": [{**records[0], "id": "other-task", "status": "completed"}]}
            rows += event("unrelated", "TodoWrite", args, executor.execute("TodoWrite", args))
            state, _ = project_state(rows, build_graph(rows))
            assert "terminal_task" not in state
        executor = Executor(tmp_path / "task", records)
        args = {"todos": [{**item, "status": "completed"} for item in records],
                "checkpoint": {"objective": "explicit new terminal declaration"}}
        rows = initial + event("explicit-rebind", "TodoWrite", args, executor.execute("TodoWrite", args))
        state, _ = project_state(rows, build_graph(rows))
        assert state["terminal_task"]["objective"] == "explicit new terminal declaration"
        assert state["terminal_task"]["checkpoint_source"] == len(rows)-1


def test_report_association_checks_receipt_order_and_ambiguous_ids():
    from evals.wsc_execution_behavior import event, verification_association
    ok = {"content": "passed", "is_error": False}
    verify = {"command": "py -3.11 verify.py all"}
    report = {"verification_call_id": "verify-actual"}
    write = {"file_path": "report.json", "content": '{"verification_call_id":"verify-actual"}'}
    rows = event("verify-actual", "Bash", verify, ok) + event("write", "Write", write, ok)
    assert all(verification_association(rows, report).values())
    assert not verification_association(rows[::-1], report)["report_latest_success_at_write"]
    assert not verification_association(rows + event("verify-actual", "Bash", verify, ok), report)["report_actual_success_reference"]
    later = event("verify-new", "Bash", verify, ok)
    assert not verification_association(rows[:2] + later + rows[2:], report)["report_latest_success_at_write"]


def test_real_unchanged_read_is_not_hashed_as_file_content(monkeypatch, tmp_path):
    from evals.wsc_execution_behavior import event
    from synaptic.filestate import build_file_states
    from synaptic.graph import build_graph
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    monkeypatch.setattr("tools.file_read_tool.file_read_tool.aging_enabled", lambda: False)
    executor = Executor(tmp_path)
    path = tmp_path / "fixture.py"
    # Literal protocol-like language is valid file content, not a receipt kind.
    path.write_text("File unchanged since last read.\nactual second line\n", encoding="utf-8")
    args = {"file_path": "fixture.py"}
    first = executor.execute("Read", args)
    second = executor.execute("Read", args)
    assert first["execution"]["read_observation"]["kind"] == "text"
    assert second["execution"]["read_observation"]["kind"] == "file_unchanged"
    rows = event("body", "Read", args, first)
    before = build_file_states(build_graph(rows), rows)["fixture.py"]
    # Rendering/localization changes cannot turn a stub into a body observation.
    second["content"] = "different result explanation\nwith any number of lines"
    rows += event("stub", "Read", args, second)
    after = build_file_states(build_graph(rows), rows)["fixture.py"]
    assert before.observed_hash == after.observed_hash
    assert before.last_read_idx == after.last_read_idx == 1
    assert before.read_ranges == after.read_ranges == ((1, 2),)


def test_read_observation_metadata_is_present_in_main_flow(monkeypatch, tmp_path):
    monkeypatch.delenv("XEYO_WSC_TASK_CONTINUITY", raising=False)
    monkeypatch.delenv("XEYO_EXECUTION_FACT_CONTRACTS", raising=False)
    (tmp_path / "file.py").write_text("x=1\n", encoding="utf-8")
    result = Executor(tmp_path).execute("Read", {"file_path": "file.py"})
    assert result["execution"]["status"] == "ok"
    assert result["execution"]["read_observation"]["kind"] == "text"
    assert result["execution"]["read_observation"]["returned_range"] == [1, 1]


def test_unconsumed_parallel_response_frame_is_not_absorbed(monkeypatch):
    from memory.wsc_execution_boundary import protect
    rows = [{"role": "user", "content": "current task"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "a", "name": "Read", "input": {}},
            {"type": "tool_use", "id": "b", "name": "Bash", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "body"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "b", "content": "passed"}]}]
    monkeypatch.delenv("XEYO_WSC_TASK_CONTINUITY", raising=False)
    assert protect(rows, 4) == 1
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    assert protect(rows, 4) == 1
    assert protect(rows, 0) == 0
    assert protect(rows + [{"role": "assistant", "content": "observed results"}], 5) == 5


def test_pinned_response_window_survives_consumption_and_cold_restart(monkeypatch, tmp_path):
    from memory.wsc_projection import _emit
    from memory import wsc_head_store as heads
    from evals.wsc_execution_behavior import event
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    monkeypatch.setenv("XEYO_WSC_SIZE_PRUNE", "1")
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    rows = [{"role": "user", "content": "existing source"}]
    rows += event("fresh-result", "Bash", {"command": "check"}, {"content": "x" * 12000, "is_error": False})
    lifecycle = {"response_tail_from": 1}
    first = _emit("frozen-head", rows, 1, len(rows), cwd=str(tmp_path), lifecycle=lifecycle)
    assert first[-1]["content"][0]["content"].endswith("x" * 12000)
    rows += [{"role": "assistant", "content": "consumed the result"}]
    second = _emit("frozen-head", rows, 1, 3, cwd=str(tmp_path), lifecycle=lifecycle)
    assert second[:len(first)] == first
    monkeypatch.setattr(heads, "enabled", lambda: True)
    assert heads.save("response-window", text="frozen-head", cwd=str(tmp_path), cursor=3,
        region_end=1, messages=rows, lifecycle=lifecycle)
    restored = heads.load("response-window", cwd=str(tmp_path), cursor=3, messages=rows)
    assert restored.lifecycle["response_tail_from"] == 1
    third = _emit(restored.text, rows, restored.region_end, 3, cwd=str(tmp_path), lifecycle=restored.lifecycle)
    assert third == second


def test_c2_failure_fallback_keeps_response_frame_and_saved_head(monkeypatch, tmp_path):
    from memory.runtime import apply_c2_messages
    from memory.working import WorkingSnapshot
    from evals.wsc_execution_behavior import event
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    monkeypatch.setattr("memory.wsc_projection.project_c2_messages", lambda *a, **k: None)
    rows = [{"role": "user", "content": "earlier fact"}] + event("recent", "Bash", {"command": "check"},
        {"content": "current result " + "z" * 12000, "is_error": False})
    working = WorkingSnapshot(compact_cursor=3, c1_frozen_until=3, c2_summary_text="saved-head")
    emitted = apply_c2_messages(rows, working, cwd=str(tmp_path))
    assert emitted[0]["content"] == "saved-head" and working.c2_summary_text == "saved-head"
    assert emitted[1] == rows[1] and emitted[2]["content"][0]["content"].endswith("z" * 12000)


def test_keep_response_window_is_append_stable_and_persisted(monkeypatch, tmp_path):
    from memory.wsc_pressure_admission import keep_emission
    from memory.working import WorkingSnapshot, flush, hydrate
    from evals.wsc_execution_behavior import event
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    rows = [{"role": "user", "content": "fact"}] + event("read", "Read", {"file_path": "x"},
        {"content": "w" * 12000, "is_error": False})
    working = WorkingSnapshot(session_id="keep-window")
    first = keep_emission(rows, working, cwd=str(tmp_path))
    rows += [{"role": "assistant", "content": "consumed"}]
    second = keep_emission(rows, working, cwd=str(tmp_path))
    assert second[:len(first)] == first
    assert working.c0_response_tail_from == 1
    flush("keep-window", working)
    restored = hydrate("keep-window")
    assert restored.c0_response_tail_from == 1
    assert keep_emission(rows, restored, cwd=str(tmp_path)) == second


def test_pressure_c1_keeps_newest_response_and_retires_only_consumed_window(monkeypatch):
    from engine.compact import project
    from memory.wsc_execution_boundary import unfolded
    from memory.working import WorkingSnapshot
    from evals.wsc_execution_behavior import event
    monkeypatch.setenv("XEYO_WSC_TASK_CONTINUITY", "1")
    rows = [{"role": "user", "content": "task"}]
    rows += event("old", "Read", {"file_path": "x"}, {"content": "old body " + "a" * 12000, "is_error": False})
    rows += event("current", "Bash", {"command": "check"}, {"content": "fresh " + "b" * 12000, "is_error": False})
    working = WorkingSnapshot(c1_frozen_until=len(rows), c0_response_tail_from=1)
    projected = project(rows, frozen_until=len(rows))
    emitted = unfolded(projected, rows, working, fold=True)
    assert not emitted[2]["content"][0]["content"].endswith("a" * 12000)
    assert emitted[-1]["content"][0]["content"].endswith("b" * 12000)
    assert working.c0_response_tail_from == 3
    later = rows + [{"role": "assistant", "content": "result consumed"}]
    assert unfolded(project(later, frozen_until=len(rows)), later, working)[:len(emitted)] == emitted
