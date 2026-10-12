"""Paired mechanism assertions and compatibility negative controls."""
import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def switches(monkeypatch, on):
    for name in ("WRITES", "FACTS", "HEALTH", "QUERIES", "RESOURCES", "OUTPUT_BYTES"):
        monkeypatch.setenv("XEYO_HARNESS_" + name, "1" if on else "0")
    monkeypatch.delenv("XEYO_TOOL_RESULT_DIFF", raising=False)


@pytest.mark.parametrize("on", [False, True])
@pytest.mark.parametrize("store", [False, True])
def test_edit_after_external_change(monkeypatch, tmp_path, on, store):
    switches(monkeypatch, on)
    from tools.file_edit_tool.file_edit_tool import FileEditTool, EditInput
    from engine.write_store import WriteStore
    path = tmp_path / "a.py"
    path.write_text("value = 1\n")
    tool = FileEditTool(cwd=str(tmp_path))
    if store:
        tool.set_write_store(WriteStore(tmp_path))
    inp = EditInput(str(path), "1", "2")
    assert tool.validate_input(inp)["result"]
    path.write_text("value = 99\n")
    if on or store:
        with pytest.raises(RuntimeError):
            tool.call(inp)
        assert path.read_text() == "value = 99\n"
    else:
        tool.call(inp)
        assert path.read_text() == "value = 2\n"


@pytest.mark.parametrize("on", [False, True])
def test_shared_lock_across_store_instances(monkeypatch, tmp_path, on):
    switches(monkeypatch, on)
    from engine.write_store import WriteStore, ChangeIntent, EditOp, _content_hash_text
    path = tmp_path / "a.txt"
    path.write_text("old")
    barrier = threading.Barrier(2)
    # Delay actual mutation so legacy separate lock domains observe the same base.
    def slow_write(path, text, encoding="utf-8"):
        time.sleep(.08)
        path.write_text(text, encoding=encoding)
    monkeypatch.setattr(WriteStore, "_atomic_write", staticmethod(slow_write))
    def writer(text):
        store = WriteStore(tmp_path)
        barrier.wait()
        return store.submit_sync(ChangeIntent("a", [EditOp(str(path), new_content=text)],
                                 {str(path): _content_hash_text("old")}))
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(writer, ["first", "second"]))
    assert sum(result.ok for result in results) == (1 if on else 2)


@pytest.mark.parametrize("on", [False, True])
def test_deleted_baseline_and_creation_race(monkeypatch, tmp_path, on):
    switches(monkeypatch, on)
    from engine.write_store import WriteStore, ChangeIntent, EditOp, _content_hash_text
    path = tmp_path / "gone.txt"
    result = WriteStore(tmp_path).submit_sync(ChangeIntent("a", [EditOp(str(path), new_content="new")],
                                                {str(path): _content_hash_text("old")}))
    assert result.ok is (not on)
    if on:
        assert not path.exists()
    empty = tmp_path / "empty.txt"
    empty.write_text("")
    result = WriteStore(tmp_path).submit_sync(ChangeIntent("a", [EditOp(str(empty), new_content="x")],
                           annotation={"expected_absent": True}))
    assert not result.ok


@pytest.mark.parametrize("on", [False, True])
def test_wip_and_explicit_strict_commit(monkeypatch, tmp_path, on):
    switches(monkeypatch, on)
    from engine.write_store import WriteStore, ChangeIntent, EditOp, _content_hash_text
    path = tmp_path / "a.py"
    path.write_text("value = 1\n")
    store = WriteStore(tmp_path)
    bad = "return 1\n"
    result = store.submit_sync(ChangeIntent("a", [EditOp(str(path), new_content=bad)],
              {str(path): _content_hash_text(path.read_text())}, annotation={"validation_policy": "strict"}))
    assert result.ok is (not on)
    if on:
        assert path.read_text() == "value = 1\n" and result.checks["status"] == "failed"
    result = store.submit_sync(ChangeIntent("a", [EditOp(str(path), new_content=bad)],
              {str(path): _content_hash_text(path.read_text())}))
    assert result.ok and path.read_text() == bad
    if on:
        assert result.checks["status"] == "failed"
    # Existing broken file can still be repaired; legitimate deletion is legal.
    result = store.submit_sync(ChangeIntent("a", [EditOp(str(path), new_content="")],
              {str(path): _content_hash_text(bad)}, annotation={"validation_policy": "strict"}))
    assert result.ok and path.read_text() == ""


@pytest.mark.parametrize("on", [False, True])
def test_actual_edit_checks_and_deleted_line_visibility(monkeypatch, tmp_path, on):
    switches(monkeypatch, on)
    from tools.file_edit_tool.file_edit_tool import FileEditTool, EditInput
    from prompt.tool_result_diff_digest import apply_tool_result_digest
    path = tmp_path / "a.py"
    path.write_text('message = (\n    "ERROR: "\n    "details"\n)\n')
    tool = FileEditTool(cwd=str(tmp_path))
    inp = EditInput(str(path), '    "ERROR: "\n', "")
    assert tool.validate_input(inp)["result"]
    output = tool.call(inp)
    raw = tool.map_tool_result_to_content(output)
    msgs = [{"name": "Edit", "content": [{"type": "tool_result", "tool_use_id": "c", "content": raw}]}]
    projected = apply_tool_result_digest(msgs)
    text = projected[0]["content"][0]["content"]
    assert ('-    "ERROR: "' in text) is on
    assert ("validation=" in raw) is on
    assert apply_tool_result_digest(projected) == projected
    assert msgs[0]["content"][0]["content"] == raw


@pytest.mark.parametrize("on", [False, True])
def test_stable_cache_and_scope_retraction(monkeypatch, tmp_path, on):
    switches(monkeypatch, on)
    from engine import env_facts
    env_facts._FACTS_CACHE.clear()
    calls = []
    monkeypatch.setattr(env_facts, "collect", lambda _: calls.append(1) or {"shell": "fixture"})
    monkeypatch.setattr(env_facts, "probe_browser", lambda: "")
    monkeypatch.setattr(env_facts, "probe_scratch", lambda _: "")
    monkeypatch.setattr("engine.execution_facts.writable", lambda *_: False)
    env_facts.facts(str(tmp_path))
    env_facts.facts(str(tmp_path))
    assert len(calls) == (1 if on else 2)
    env_facts._FACTS_CACHE[str(tmp_path)] = {"scratch": ".xeyo/tmp", "shell": "fixture"}
    assert ("scratch" in env_facts.facts(str(tmp_path))) is (not on)
    env_facts._FACTS_CACHE.clear()


@pytest.mark.parametrize("on", [False, True])
def test_multiturn_trace_health(monkeypatch, on):
    switches(monkeypatch, on)
    from evals.changedetect.trace import collect
    from evals.changedetect.health import failures
    traces = collect({"loop"})
    assert bool(failures(traces)) is (not on)
    if on:
        assert "Final" in json.loads(traces["loop/multi_turn"])["events"]


def test_exception_cannot_become_a_golden(monkeypatch, tmp_path):
    switches(monkeypatch, True)
    from evals.changedetect.trace import write_golden
    with pytest.raises(ValueError, match="unhealthy_traces"):
        write_golden({"loop/x": "<raised AttributeError: x>"}, directory=tmp_path)
    assert not (tmp_path / "trace").exists()


def test_workset_filter_before_paging_and_restart(monkeypatch, tmp_path):
    switches(monkeypatch, True)
    from memory import journal
    from session.workset_index import query
    for index in range(85):
        sid = "s__agent__child" if index < 3 else "other"
        journal.record_change("fixture", journal.ChangeRecord(seq=0, agent_id="a", path=f"file{index}.py",
              action="write", file_hash_after="hash", ts=1, metadata={"session_id": sid}))
    page = query("fixture", "s", limit=2)
    assert page["returned"] == 2 and page["total_matching_before_cursor"] == 3
    assert page["next_before_seq"] is not None
    second = query("fixture", "s", limit=2, before_seq=page["next_before_seq"])
    assert second["returned"] == 1
    assert not set(row["seq"] for row in page["records"]) & set(row["seq"] for row in second["records"])


def test_registered_flags_match_real_predicates(monkeypatch):
    from engine.flag_definitions import FLAGS, snapshot
    from engine.env_switches import SWITCHES
    assert set(FLAGS) <= {item.name for item in SWITCHES}
    for raw in (None, "0", "1", "garbage"):
        for name in FLAGS:
            if raw is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, raw)
        from evals.harness_friction_audit import flag_probe
        probes = {row["name"]: row["effective"] for row in flag_probe()}
        assert probes == {row["name"]: row["effective"] for row in snapshot(FLAGS)}


@pytest.mark.parametrize("on", [False, True])
def test_partial_spill_write_is_not_reported_complete(monkeypatch, tmp_path, on):
    switches(monkeypatch, on)
    import os
    from tools.spill import save_text
    monkeypatch.setenv("XEYO_SPILL_DIR", str(tmp_path))
    original = os.write
    monkeypatch.setattr(os, "write", lambda fd, data: original(fd, data[:3]))
    ref = save_text("s", "abcdefghijk")
    actual = Path(ref.path).read_text()
    assert actual == ("abcdefghijk" if on else "abc")


def test_artifact_pins_and_cleanup_do_not_depend_on_display(monkeypatch, tmp_path):
    switches(monkeypatch, True)
    from tools.spill import save_text
    from tools.artifact_lifecycle import inspect, pin, release, prune
    monkeypatch.setenv("XEYO_SPILL_DIR", str(tmp_path))
    for display in ("0", "1"):
        monkeypatch.setenv("XEYO_TOOL_COMPLETENESS_FACTS", display)
        ref = save_text("s", "evidence")
        assert pin(ref.path, "checkpoint:s")
        future = time.time() + 8 * 86400
        assert prune(tmp_path, now=future) == 0
        assert Path(ref.path).exists()
        assert release(ref.path, "checkpoint:s")
        assert prune(tmp_path, now=future) == 1
        assert inspect(ref.path)["status"] == "expired"
        assert prune(tmp_path, now=future) == 0
    unrelated = tmp_path / "user.txt"
    unrelated.write_text("keep")
    assert prune(tmp_path, now=time.time() + 100 * 86400) == 0
    assert unrelated.read_text() == "keep"


def test_baseline_does_not_hide_new_or_changed_failures():
    from evals.baseline_compare import compare_runs
    common = {"test_manifest_id": "tests-v1", "environment_id": "env-v1", "source_id": "source"}
    old = {**common, "tests": {"x": {"status": "failed", "failure_sha256": "old"},
                             "y": {"status": "passed"}}}
    new = {**common, "tests": {"x": {"status": "failed", "failure_sha256": "new"},
                             "y": {"status": "failed", "failure_sha256": "other"}}}
    result = compare_runs(old, new)
    assert result["tests"] == {"x": "changed_failure", "y": "new_failure"}
    new["environment_id"] = "different"
    assert not compare_runs(old, new)["comparable"]
    no_evidence = {**common, "tests": {"x": {"status": "failed"}}}
    assert compare_runs(no_evidence, no_evidence)["tests"]["x"] == "not_comparable"


def test_read_explicit_body_and_structure(monkeypatch, tmp_path):
    switches(monkeypatch, True)
    from tools.file_read_tool.file_read_tool import FileReadTool, ReadInput
    path = tmp_path / "large.md"
    path.write_text("# heading\n" + "body\n" * 610)
    tool = FileReadTool(cwd=str(tmp_path))
    body = tool.call(ReadInput(str(path), limit=3, view="body"))
    structure = tool.call(ReadInput(str(path), view="structure"))
    assert not body.structured and structure.structured
    bad = tool.validate_input(ReadInput(str(path), limit=3, view="structure"))
    assert not bad["result"]
    assert "view" in tool.schema()["input_schema"]["properties"]


def test_runtime_identity_is_stable_and_does_not_claim_loaded_disk_version(monkeypatch):
    switches(monkeypatch, True)
    from engine.runtime_identity import snapshot
    first, second = snapshot(), snapshot()
    assert first == second and first["loaded_source_identity"] == "unknown"


def test_direct_edit_preserves_authorized_external_path(monkeypatch, tmp_path):
    switches(monkeypatch, True)
    from tools.file_edit_tool.file_edit_tool import FileEditTool, EditInput
    from engine.write_store import WriteStore, ChangeIntent, EditOp
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = tmp_path / "outside.py"
    path.write_text("value = 1\n")
    tool = FileEditTool(cwd=str(workspace))
    inp = EditInput(str(path), "1", "2")
    assert tool.validate_input(inp)["result"]
    tool.call(inp)
    assert path.read_text() == "value = 2\n"
    result = WriteStore(workspace).submit_sync(ChangeIntent("child", [EditOp(str(path), new_content="bad")]))
    assert not result.ok and path.read_text() == "value = 2\n"


def test_identical_strict_write_still_validates(monkeypatch, tmp_path):
    switches(monkeypatch, True)
    from tools.file_write_tool.file_write_tool import FileWriteTool, WriteInput
    path = tmp_path / "broken.py"
    path.write_text("return 1\n")
    tool = FileWriteTool(cwd=str(tmp_path))
    inp = WriteInput(str(path), "return 1\n", validation_policy="strict")
    assert tool.validate_input(inp)["result"]
    with pytest.raises(RuntimeError, match="validation_failed"):
        tool.call(inp)
    assert path.read_text() == "return 1\n"


def test_explicit_view_does_not_succeed_with_unrelated_media(monkeypatch, tmp_path):
    switches(monkeypatch, True)
    from tools.file_read_tool.file_read_tool import FileReadTool, ReadInput
    tool = FileReadTool(cwd=str(tmp_path))
    for extension in ("png", "pdf", "ipynb"):
        assert not tool.validate_input(ReadInput(str(tmp_path / ("file." + extension)), view="structure"))["result"]


def test_diff_content_and_truncation_are_factual():
    from prompt.mutation_receipt import compact
    from tools.fileio.diff_preview import format_capped_unified_diff, append_diff_fence
    source = append_diff_fence("ok", format_capped_unified_diff("-- prefix\n```\n", "++ prefix\n", file_path="x.txt"))
    result = compact(source)
    assert "--- prefix" in result and "+++ prefix" in result and "-```" in result
    assert "complete=true" in result
    large = append_diff_fence("ok", format_capped_unified_diff("", "x\n" * 500, file_path="x.txt"))
    assert "complete=false" in compact(large)


def test_subset_trace_comparison_does_not_report_unselected_removals(tmp_path):
    from evals.changedetect import trace
    directory = tmp_path / "trace"
    directory.mkdir()
    (directory / "loop__x.txt").write_text("x\n")
    (directory / "inject__x.txt").write_text("y\n")
    assert trace.compare({"loop/x": "x\n"}, directory=tmp_path, batteries={"loop"}) == []


def test_exception_equality_cannot_make_aggregate_verdict_pass(monkeypatch):
    switches(monkeypatch, True)
    from evals.changedetect.verdict import build
    from evals.changedetect.health import apply_verdict, failures
    result = build(surface_changes=[], trace_changes=[], run_compliance=False)
    assert apply_verdict(result, {"loop/x": "<raised AttributeError: broken>"}).overall == "fail"
    assert failures({"loop/x": "[]"})[0]["reason"] == "invalid_loop_contract"


def test_unavailable_source_version_cannot_authorize_overwrite(monkeypatch, tmp_path):
    switches(monkeypatch, True)
    from engine.write_store import WriteStore, ChangeIntent, EditOp, _content_hash_text
    path = tmp_path / "a.txt"
    path.write_text("old")
    monkeypatch.setattr("engine.write_store._content_hash", lambda _: "")
    result = WriteStore(tmp_path).submit_sync(ChangeIntent("a", [EditOp(str(path), new_content="new")],
                         {str(path): _content_hash_text("old")}))
    assert not result.ok and result.reason == "read_failed" and path.read_text() == "old"


def test_journal_tool_bound_session_and_unbound_scope(monkeypatch, tmp_path):
    switches(monkeypatch, True)
    from engine.workspace_context import bind_workspace_context, WorkspaceContext
    from engine.abort import AbortController
    from memory import journal
    from memory.memdir import workspace_id
    from tools.journal_query_tool import JournalQueryTool
    wsid = workspace_id(str(tmp_path))
    for index in range(85):
        journal.record_change(wsid, journal.ChangeRecord(seq=0, agent_id="a", path=f"p{index}",
            action="write", file_hash_after="h", ts=1, metadata={"session_id": "s__agent__child" if index < 3 else "other"}))
    tool = JournalQueryTool(cwd=str(tmp_path))
    with bind_workspace_context(WorkspaceContext(session_id="s", cwd=str(tmp_path))):
        result = asyncio.run(tool.execute({"limit": 2}, AbortController()))
        assert not result.is_error
        page = json.loads(result.content)
        assert page["returned"] == 2 and page["total_matching_before_cursor"] == 3
        result = asyncio.run(tool.execute({"before_seq": page["next_before_seq"]}, AbortController()))
        assert json.loads(result.content)["returned"] == 1
    with bind_workspace_context(None):
        result = asyncio.run(tool.execute({"limit": 2}, AbortController()))
        assert not result.is_error and json.loads(result.content)["session_scope"] == "workspace_unbound"


@pytest.mark.parametrize("on", [False, True])
def test_write_stale_full_observation_even_when_mtime_unchanged(monkeypatch, tmp_path, on):
    switches(monkeypatch, on)
    import os
    from tools.file_write_tool.file_write_tool import FileWriteTool, WriteInput
    from tools.fileio.text import get_mtime_ms
    path = tmp_path / "a.py"
    path.write_text("value = 1\n")
    tool = FileWriteTool(cwd=str(tmp_path))
    previous = path.stat()
    tool._read_state.set_written(str(path), path.read_text(), get_mtime_ms(str(path)), "s", offset=None, limit=None)
    path.write_text("value = 9\n")
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    inp = WriteInput(str(path), "value = 2\n")
    assert tool.validate_input(inp)["result"]
    if on:
        with pytest.raises(RuntimeError, match="stale"):
            tool.call(inp)
        assert path.read_text() == "value = 9\n"
    else:
        tool.call(inp)
        assert path.read_text() == "value = 2\n"
