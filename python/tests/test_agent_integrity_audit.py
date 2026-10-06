"""Paired reproductions for result loss and durable action boundaries."""
import asyncio
import json
import multiprocessing
import time
from pathlib import Path

import pytest

from engine.abort import AbortController
from engine.action_journal import ActionJournal
from extension.mcp_client import _finalize_mcp_result, _result_from_mcp_call
from msgtypes.message import ToolUse
from tools.base_tool import ToolResult
from tools.tool_registry import ToolRegistry


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_ACTION_JOURNAL", "1")
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
    monkeypatch.setenv("XEYO_SPILL_DIR", str(tmp_path / "spill"))
    monkeypatch.setenv("XEYO_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    from audit.log import reset_default_audit_log
    reset_default_audit_log()
    yield tmp_path
    reset_default_audit_log()


def begin(journal):
    return journal.begin(action_id="act_probe", idempotency_key="idem_probe",
                         turn_id="t", tool_use_id="c", tool_name="Write", side_effect="write")


def test_mcp_finalize_preserves_receipt():
    original = ToolResult("interrupted", status="cancelled", error_kind="ABORTED",
                          side_effect="external", action_id="a", retryable=True,
                          todos=[{"content": "unfinished"}], ui={"panel": "files"})
    result = _finalize_mcp_result(original, apply_vision=True, session_id="s")
    assert result == original


@pytest.mark.parametrize("field", ["text", "blob"])
def test_mcp_spill_failure_keeps_resource(monkeypatch, field):
    monkeypatch.setattr("tools.spill.save_text", lambda *a: (_ for _ in ()).throw(OSError("full")))
    body = "RESOURCE_BODY_原文" if field == "text" else "UkVTT1VSQ0VfQk9EWQ=="
    raw = {"content": [{"type": "resource", "resource": {"uri": "res://probe", field: body}}]}
    result = _finalize_mcp_result(_result_from_mcp_call(raw), apply_vision=True, session_id="s")
    assert body in result.content and "res://probe" in result.content


@pytest.mark.parametrize("text", [None, "summary"])
def test_mcp_structured_content_visible(text):
    raw = {"structuredContent": {"answer": 42, "path": "src/fix.py"}}
    if text:
        raw["content"] = [{"type": "text", "text": text}]
    result = _result_from_mcp_call(raw)
    assert "src/fix.py" in result.content and "42" in result.content


def test_mcp_structured_duplicate_not_repeated():
    data = {"answer": 42}
    result = _result_from_mcp_call({"structuredContent": data,
                                  "content": [{"type": "text", "text": json.dumps(data)}]})
    assert result.content.count("42") == 1


def test_mcp_resource_link_visible():
    result = _result_from_mcp_call({"content": [{"type": "resource_link", "uri": "file:///src/main.rs",
                                               "name": "main.rs", "description": "entry point"}]})
    assert "file:///src/main.rs" in result.content and "entry point" in result.content


@pytest.mark.parametrize("damage", ["unreadable", "malformed"])
@pytest.mark.asyncio
async def test_journal_failure_never_executes_side_effect(isolated, monkeypatch, damage):
    calls = []
    class Probe:
        name = "Write"
        async def execute(self, input, abort):
            calls.append(1)
            return ToolResult("written")
    journal = ActionJournal("s")
    journal.path.parent.mkdir(parents=True)
    journal.path.write_text("broken\n")
    if damage == "unreadable":
        original = Path.open
        def open_checked(path, *a, **kw):
            if path == journal.path and a and a[0] == "r":
                raise PermissionError("locked")
            return original(path, *a, **kw)
        monkeypatch.setattr(Path, "open", open_checked)
    result = await ToolRegistry()._execute_audited(Probe(), ToolUse("c", "Write", {}),
                                                 AbortController(), session_id="s", turn_id="t")
    assert not calls and result.is_error


def _begin_process(root, name, queue):
    class SlowRead(ActionJournal):
        def _latest(self):
            result = super()._latest()
            Path(root, name).touch()
            deadline = time.monotonic() + .7
            while time.monotonic() < deadline and not all(Path(root, n).exists() for n in ("p1", "p2")):
                time.sleep(.01)
            return result
    queue.put(begin(SlowRead("s", enabled=True, sessions_dir=Path(root))).action)


def test_journal_cross_process_atomic_begin(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    processes = [ctx.Process(target=_begin_process, args=(str(tmp_path), name, queue)) for name in ("p1", "p2")]
    try:
        for p in processes:
            p.start()
        results = [queue.get(timeout=15) for _ in processes]
        assert results.count("execute") == 1 and results.count("recovery_required") == 1
    finally:
        for p in processes:
            p.join(timeout=10)
            if p.is_alive():
                p.terminate()
                p.join()
        queue.close()


def test_action_intent_is_durable_before_execute(tmp_path, monkeypatch):
    import os
    monkeypatch.delenv("XEYO_REWIND_FSYNC", raising=False)
    original = os.fsync
    synced = []
    def sync(fd):
        synced.append(fd)
        original(fd)
    monkeypatch.setattr(os, "fsync", sync)
    assert begin(ActionJournal("s", enabled=True, sessions_dir=tmp_path)).action == "execute"
    assert synced


@pytest.mark.parametrize("kind", ["payload", "long"])
@pytest.mark.asyncio
async def test_action_replay_preserves_result(isolated, kind):
    calls = []
    original = ToolResult("x" * 14000 if kind == "long" else "written",
                          images=["data:image/png;base64,AA=="], todos=[{"content": "done"}],
                          ui={"panel": "files"}, metadata={"receipt": "r"}, side_effect="write")
    if kind == "long":
        original.images = original.todos = original.ui = original.metadata = None
    class Probe:
        name = "Write"
        output_budget = 0
        async def execute(self, input, abort):
            calls.append(1)
            return original
    registry = ToolRegistry()
    use = ToolUse("c", "Write", {})
    first = await registry._execute_audited(Probe(), use, AbortController(), session_id="s", turn_id="t")
    replay = await registry._execute_audited(Probe(), use, AbortController(), session_id="s", turn_id="t")
    assert len(calls) == 1
    if kind == "long":
        assert replay.content == first.content
    else:
        assert replay.images == first.images and replay.ui == first.ui and replay.todos == first.todos
        assert replay.metadata["receipt"] == "r"


@pytest.mark.parametrize("status", ["pending", "running", "cancelled"])
def test_nonterminal_action_not_replayed_as_completed(tmp_path, status):
    journal = ActionJournal("s", enabled=True, sessions_dir=tmp_path)
    begin(journal)
    journal.complete("act_probe", ToolResult("not a receipt", status=status, side_effect="write"))
    assert begin(journal).action == "recovery_required"


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_nonfinite_cost_cannot_poison_budget(value):
    from engine.budget import BudgetTracker
    from usage.money import round_money8
    from usage.pricing import official_cost_cny
    tracker = BudgetTracker(provider="unpriced_probe", model="unknown")
    tracker.add_usage({"usd": value, "cost_cny": value, "prompt_tokens": 1})
    assert tracker.last_usage_usd is None and tracker.last_usage_cny is None
    assert tracker.used_usd == 0 and tracker.used_cny == 0
    assert official_cost_cny({"cost_cny": value}) is None
    assert round_money8(float(value)) is None


def test_repeat_fold_byte_count_is_utf8():
    from engine.repeat_fold import _facts_line
    assert "6 字节" in _facts_line("中文")


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf"])
def test_nonfinite_runtime_knobs_fall_back(monkeypatch, raw):
    from tools.orchestration import _tool_timeout_s, _progress_interval_s
    monkeypatch.setenv("XEYO_TOOL_TIMEOUT_S", raw)
    monkeypatch.setenv("XEYO_TOOL_PROGRESS_S", raw)
    assert _tool_timeout_s() == 300 and _progress_interval_s() == 5


@pytest.mark.asyncio
async def test_journal_wait_does_not_block_event_loop(isolated, monkeypatch):
    original = ActionJournal.begin
    entered = __import__("threading").Event()
    def slow_begin(self, **kwargs):
        entered.set()
        time.sleep(.15)
        return original(self, **kwargs)
    monkeypatch.setattr(ActionJournal, "begin", slow_begin)
    class Probe:
        name = "Write"
        async def execute(self, input, abort):
            return ToolResult("written")
    task = asyncio.create_task(ToolRegistry()._execute_audited(Probe(), ToolUse("c", "Write", {}),
                                                             AbortController(), session_id="s", turn_id="t"))
    started = time.monotonic()
    await asyncio.sleep(.02)
    elapsed = time.monotonic() - started
    await task
    assert entered.is_set() and elapsed < .10


@pytest.mark.parametrize("damage", ["removed", "modified"])
@pytest.mark.asyncio
async def test_replay_missing_or_corrupt_artifact_never_reexecutes(isolated, damage):
    calls = []
    class Probe:
        name = "Write"
        output_budget = 0
        async def execute(self, input, abort):
            calls.append(1)
            return ToolResult("x" * 14000)
    registry = ToolRegistry()
    use = ToolUse("c", "Write", {})
    await registry._execute_audited(Probe(), use, AbortController(), session_id="s", turn_id="t")
    artifact = next((isolated / "s" / "action-results").glob("*.json"))
    if damage == "removed":
        artifact.unlink()
    else:
        artifact.write_text("{}")
    result = await registry._execute_audited(Probe(), use, AbortController(), session_id="s", turn_id="t")
    assert len(calls) == 1 and result.is_error


def test_legacy_short_receipt_still_replays():
    from engine.action_result import replay_result
    record = {"result_content": "written", "result_status": "ok", "side_effect": "write"}
    assert replay_result(record, action_id="a", side_effect="write").content == "written"


@pytest.mark.asyncio
async def test_disabled_journal_does_not_touch_unreadable_ledger(isolated, monkeypatch):
    monkeypatch.setenv("XEYO_ACTION_JOURNAL", "0")
    def fail(*a, **kw):
        raise AssertionError("disabled journal touched disk")
    monkeypatch.setattr(ActionJournal, "begin", fail)
    monkeypatch.setattr(ActionJournal, "complete", fail)
    class Probe:
        name = "Write"
        async def execute(self, input, abort):
            return ToolResult("written")
    result = await ToolRegistry()._execute_audited(Probe(), ToolUse("c", "Write", {}),
                                                 AbortController(), session_id="s", turn_id="t")
    assert result.content == "written" and not result.is_error
