"""Publication, retirement, provenance and restart contracts against real tools."""
from dataclasses import replace
from pathlib import Path
import pytest
from synaptic.project import project
from synaptic.contracts import publish, verify_object
from memory.wsc_projection import production_params


@pytest.fixture
def strict(monkeypatch, tmp_path):
    monkeypatch.setenv("XEYO_WSC_STATE_CONTRACTS", "1")
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))


def messages():
    return [{"role": "user", "content": "修复 ChatGPT 前台窗口；必须保留所有用户文件。"},
            {"role": "assistant", "content": "观察到后台进程。"},
            {"role": "user", "content": "ChatGPT 前台窗口已经修好了。"}]


def build(tmp_path, rows, previous=None, **kwargs):
    return project(rows, region_end=len(rows), params=production_params(),
                   view_path=tmp_path / "session.txt", prev=previous.state if previous else None,
                   cold=previous.cold if previous else None, **kwargs)


def test_content_address_is_actual_bytes_and_never_replaces(strict, tmp_path):
    first = publish(tmp_path / "s.txt", b"first\n")
    second = publish(tmp_path / "s.txt", b"second\n")
    assert first != second and first.read_bytes() == b"first\n"
    assert publish(tmp_path / "s.txt", b"first\n") == first
    assert verify_object(first)
    first.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="digest mismatch"):
        publish(tmp_path / "s.txt", b"first\n")


def test_mixed_goal_retires_but_standing_constraint_survives(strict, tmp_path):
    result = build(tmp_path, messages())
    assert not result.seeds.original_task
    assert not result.seeds.constraints
    assert result.cold.expand("node://0") == (messages()[0]["content"],)
    assert verify_object(result.view_path)
    assert ".pending-" not in result.text
    assert result.state.full_text == result.text


@pytest.mark.parametrize("status", ["completed", "abandoned", "active", "paused", "blocked"])
def test_authoritative_goal_has_independent_lifecycle(strict, tmp_path, status):
    snapshot = {"goal_id": "g1", "revision": 4, "status": status, "text": "检查 WSC 证据"}
    result = build(tmp_path, messages(), goal_snapshot=snapshot)
    assert result.seeds.original_task == (snapshot["text"] if status in {"active", "paused", "blocked"} else "")
    assert result.state.lifecycle["goal_id"] == "g1"
    assert result.state.lifecycle["revision"] == 4
    goal = next((p for p in result.result.hot.pins if p.key == "goal"), None)
    assert goal is None or not goal.nodes  # No invented transcript origin.


def test_retirement_rebases_once_and_old_object_survives(strict, tmp_path):
    rows = messages()
    first = build(tmp_path, rows[:2])
    old_bytes = Path(first.view_path).read_bytes()
    second = build(tmp_path, rows, first)
    assert second.result.rebuilt
    assert "[UNRESOLVED]" not in second.text
    assert not second.seeds.original_task
    assert Path(first.view_path).read_bytes() == old_bytes
    third = build(tmp_path, rows + [{"role": "assistant", "content": "记录已更新。"}], second)
    assert not third.result.rebuilt
    assert third.text.startswith(second.text)


def test_manifest_rejects_tampered_head_and_view(strict, monkeypatch, tmp_path):
    import json
    from memory import wsc_head_store as store
    monkeypatch.setattr(store, "enabled", lambda: True)
    rows = messages()
    result = build(tmp_path, rows)
    store.save("s", text=result.text, cwd=str(tmp_path), cursor=2,
               region_end=3, messages=rows, view_path=result.view_path)
    assert store.load("s", cwd=str(tmp_path), cursor=2, messages=rows)
    rec = json.loads(store.path_for("s").read_text(encoding="utf-8"))
    rec["lifecycle"] = {"goal": "invented"}
    store.path_for("s").write_text(json.dumps(rec), encoding="utf-8")
    assert store.load("s", cwd=str(tmp_path), cursor=2, messages=rows) is None
    store.save("s", text=result.text, cwd=str(tmp_path), cursor=2,
               region_end=3, messages=rows, view_path=result.view_path)
    rec = json.loads(store.path_for("s").read_text(encoding="utf-8"))
    rec["text"] += "altered"
    store.path_for("s").write_text(json.dumps(rec), encoding="utf-8")
    assert store.load("s", cwd=str(tmp_path), cursor=2, messages=rows) is None
    store.save("s", text=result.text, cwd=str(tmp_path), cursor=2,
               region_end=3, messages=rows, view_path=result.view_path)
    Path(result.view_path).write_text("tampered", encoding="utf-8")
    assert store.load("s", cwd=str(tmp_path), cursor=2, messages=rows) is None


def test_actual_read_rejects_tampered_object_before_unchanged_stub(strict, tmp_path):
    from tools.file_read_tool.file_read_tool import FileReadTool, ReadInput
    target = publish(tmp_path / "s.txt", b"original\n")
    reader = FileReadTool(cwd=str(tmp_path))
    reader.call(ReadInput(file_path=str(target)))
    target.write_bytes(b"tampered\n")
    with pytest.raises(ValueError, match="stale_view"):
        reader.call(ReadInput(file_path=str(target)))


def test_goal_binding_adapter_uses_existing_store(strict, tmp_path):
    from engine.goal_state import GoalStore
    from memory.wsc_goal_source import snapshot
    store = GoalStore(str(tmp_path))
    goal = store.create(title="task", text="current goal")
    store.bind("session", goal.goal_id)
    assert snapshot(str(tmp_path), "session")["goal_id"] == goal.goal_id
    assert snapshot(str(tmp_path), "other") is None


def failure_messages(success=True, complete=True):
    rows = [{"role": "user", "content": "验证 tests/a.py"}]
    for i in range(3):
        uid = f"c{i}"
        rows.append({"role": "assistant", "content": [{"type": "tool_use", "id": uid, "name": "Bash", "input": {"command": "pytest tests/a.py"}}]})
        ok = success and i == 2
        rows.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": uid,
                      "content": "" if ok else "AssertionError: expected equal",
                      "is_error": not ok, "execution": {"status": "ok" if ok else "error", "complete": complete}}]})
    return rows


def test_typed_success_without_stdout_resolves_all_duplicates(strict, tmp_path):
    rows = failure_messages()
    first = build(tmp_path, rows[:5])
    assert first.seeds.unresolved_errors
    after = build(tmp_path, rows, first)
    assert after.result.rebuilt
    assert not after.seeds.unresolved_errors
    assert "[UNRESOLVED]" not in after.text
    assert "AssertionError" not in after.text
    assert after.cold.expand("node://2") == ("AssertionError: expected equal",)


def test_started_background_is_not_successful_resolution(strict, tmp_path):
    rows = failure_messages(complete=False)
    result = build(tmp_path, rows)
    assert result.seeds.unresolved_errors


def test_readable_prior_content_object_family(strict, tmp_path):
    from memory.wsc_continuation import prior_generation
    old = publish(tmp_path / "s.txt", b"old")
    new = publish(tmp_path / "s.txt", b"new")
    other = publish(tmp_path / "other.txt", b"old")
    assert prior_generation(str(new), str(old))
    assert not prior_generation(str(new), str(other))


def test_gc_keeps_all_explicit_recovery_roots(strict, tmp_path):
    from memory.wsc_object_gc import collect
    active = publish(tmp_path / "s.txt", b"active")
    historical = publish(tmp_path / "s.txt", b"historical")
    orphan = publish(tmp_path / "s.txt", b"unpublished")
    assert collect(tmp_path, [active], dry_run=False)["status"] == "incomplete_roots"
    assert historical.exists() and orphan.exists()
    result = collect(tmp_path, [active, historical], inventory_complete=True, dry_run=False)
    assert result["deleted"] == [str(orphan)]
    assert active.exists() and historical.exists()


@pytest.mark.parametrize("text", ["如果 ChatGPT 前台窗口已解决，测试通知机制。", "检查关键词‘已解决’的匹配规则。", "ChatGPT 前台窗口还没有解决，继续修复。"])
def test_nonasserted_closure_is_not_a_goal_transition(strict, tmp_path, text):
    result = build(tmp_path, [{"role": "user", "content": text}])
    assert not result.seeds.original_task
    assert result.seeds.request_text == text
    assert result.cold.expand("node://0") == (text,)


def test_live_emission_keeps_prefix_then_rebuilds_at_fold_and_restores(strict, monkeypatch, tmp_path):
    import copy
    from types import SimpleNamespace
    from memory import wsc_projection as live, wsc_head_store as store
    prior = dict(live._STATE)
    monkeypatch.setattr(live, "live_enabled", lambda: True)
    monkeypatch.setattr(live, "freeze_enabled", lambda: True)
    monkeypatch.setattr(store, "enabled", lambda: True)
    monkeypatch.setattr("memory.wsc_extension_economics.absorb_boundary", lambda messages, cursor: cursor)
    rows = messages()[:2]
    rows += [{"role": "assistant", "content": "观测数据 " * 2000} for _ in range(8)]
    working = SimpleNamespace(session_id="contract-live", compact_cursor=len(rows), c1_frozen_until=len(rows))
    try:
        first = live.project_c2_messages(rows, working, cwd=str(tmp_path))
        assert first is not None
        head = first[0]["content"]
        with_closure = rows + [messages()[-1]]
        second = live.project_c2_messages(with_closure, working, cwd=str(tmp_path))
        assert second[:len(first)] == first
        assert second[0]["content"] == head
        working.compact_cursor = len(with_closure)
        working.c1_frozen_until = len(with_closure)
        third = live.project_c2_messages(with_closure, working, cwd=str(tmp_path))
        assert third is not None and third[0]["content"] != head
        assert not live._STATE["contract-live"].lifecycle["goal"]
        live._STATE.clear()
        restarted = live.project_c2_messages(with_closure, working, cwd=str(tmp_path))
        assert restarted == third
        assert store.load("contract-live", cwd=str(tmp_path), cursor=working.compact_cursor, messages=with_closure).lifecycle
        # A failed durable publication cannot replace the in-memory generation.
        monkeypatch.setattr(store, "save", lambda *args, **kwargs: False)
        more = with_closure + [{"role": "assistant", "content": "next observation " * 2000}]
        working.compact_cursor = len(more)
        working.c1_frozen_until = len(more)
        not_saved = live.project_c2_messages(more, working, cwd=str(tmp_path))
        assert not_saved is not None and not_saved[0] == restarted[0]
        # Force a subsequent fold to fail: the validated old head is still emitted.
        def fail(*args, **kwargs):
            raise RuntimeError("private-command-secret")
        import importlib
        monkeypatch.setattr(importlib.import_module("synaptic.project"), "project", fail)
        failed = live.project_c2_messages(more, working, cwd=str(tmp_path))
        assert failed is not None and failed[0] == restarted[0]
        diagnostics = (tmp_path / "home" / "wsc_diagnostics.jsonl").read_text(encoding="utf-8")
        assert "RuntimeError" in diagnostics and "private-command-secret" not in diagnostics
    finally:
        live._STATE.clear()
        live._STATE.update(prior)


def test_file_error_annotation_shares_resolved_state(strict, tmp_path):
    from synaptic.filestate import build_file_states
    from synaptic.freshness import analyze
    from synaptic.graph import build_graph
    from synaptic.lifecycle import filter_file_failures
    from synaptic.types import FileState
    rows = failure_messages()
    graph = build_graph(rows)
    sig = graph.node(2).error_sig
    states = {"tests/a.py": FileState(path="tests/a.py", observed_hash="", last_read_idx=-1, read_ranges=(), related_errors=(sig,))}
    after = filter_file_failures(states, graph, analyze(graph, region_end=len(rows)), len(rows))
    assert not after["tests/a.py"].related_errors


def test_rejected_gain_does_not_publish_object(strict, tmp_path):
    result = build(tmp_path, messages(), region_baseline_tokens=1)
    assert not result.result.compressed
    assert not Path(result.view_path).exists()
