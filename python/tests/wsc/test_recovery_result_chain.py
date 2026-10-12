"""A recovery observation is not a second actual execution result."""
from copy import deepcopy
import json

import pytest

from tests.wsc.test_late_media_identity import IMAGE
from tests.wsc.test_late_wire_prefix import assert_wire_prefix, invocation, result


def recovered():
    from session.hydrate import messages_from_rows
    from session.transcript_blobs import message_fields
    rows = [{"id": "goal", "role": "user", "content": "current task"}, invocation("pending")]
    items = messages_from_rows(rows, session_id="recovery-chain")
    assert len(items) == 3
    return [message_fields(item) for item in items]


@pytest.mark.parametrize("provider", ["deepseek", "anthropic"])
@pytest.mark.parametrize("media", [False, True])
def test_actual_result_after_recovery_keeps_native_sent_prefix(monkeypatch, provider, media):
    from model.deepseek import DeepSeekModelClient
    from model.anthropic import AnthropicModelClient
    from session.hydrate import message_from_row
    from session.late_result_guard import request_conflict
    from session.late_result_projection import ENV, supported, project
    from session.recovery_result_chain import supersessions
    monkeypatch.delenv(ENV, raising=False)
    prior = recovered()
    frozen = deepcopy(prior)
    body = ([{"type": "text", "text": "actual result=137"}, deepcopy(IMAGE)] if media else "actual result=137")
    rows = prior + [result("pending", body)]
    assert supersessions(rows) == {(3, "pending"): 2}
    assert supported([message_from_row(row) for row in rows])
    assert request_conflict(rows) is None
    projected = project(rows)
    assert projected[:len(prior)] == prior == frozen
    assert "after_recovery_observation" in projected[-1]["content"][0]["text"]
    client = (DeepSeekModelClient(api_key="not-sent", model="deepseek-flash") if provider == "deepseek"
              else AnthropicModelClient(api_key="not-sent", model="claude-test"))
    old = client._build_body(project(prior), [], stream=False)["messages"]
    new = client._build_body(projected, [], stream=False)["messages"]
    assert_wire_prefix(old, new)
    assert "actual result=137" in json.dumps(new)
    assert prior == frozen


@pytest.mark.parametrize("invalid", ["legacy", "origin", "digest", "actual_twice", "two_observations", "call_twice"])
def test_only_unique_bound_observation_chain_is_accepted(monkeypatch, invalid):
    from session.hydrate import message_from_row
    from session.late_result_guard import request_conflict
    from session.late_result_projection import ENV, supported, project
    from session.recovery_result_chain import supersessions
    monkeypatch.setenv(ENV, "1")
    rows = recovered() + [result("pending", "actual result=137")]
    execution = rows[2]["content"][0]["execution"]
    if invalid == "legacy":
        execution.pop("recovery_observation")
    elif invalid == "origin":
        execution["recovery_observation"]["origin_message_id"] = "another-origin"
    elif invalid == "digest":
        rows[1]["content"][0]["input"]["file_path"] = "changed.txt"
    elif invalid == "actual_twice":
        rows.append(result("pending", "second actual result"))
    elif invalid == "two_observations":
        rows[3] = deepcopy(rows[2])
    else:
        rows.insert(2, deepcopy(rows[1]))
    original = deepcopy(rows)
    assert not supersessions(rows)
    assert not supported([message_from_row(row) for row in rows])
    assert request_conflict(rows) is not None
    assert project(rows) == original == rows


def test_disabled_candidate_retains_sources_and_stops(monkeypatch):
    from session.late_result_projection import ENV, project
    from session.late_result_guard import request_conflict
    monkeypatch.setenv(ENV, '0')
    rows = recovered() + [result("pending", "actual result=137")]
    assert project(rows) is rows and request_conflict(rows) is not None
    from evals.wsc_receipt_sequence_audit import inspect
    from session.hydrate import message_from_row
    audit = inspect([message_from_row(row) for row in rows])
    assert audit["recovery_supplement_ids"] == ["pending"]
    assert audit["default_guard_would_stop"] and audit["candidate_supported"]


def test_unknown_and_actual_survive_disk_restart_and_store_cleanup(monkeypatch, tmp_path):
    from session.hydrate import message_from_row, messages_from_transcript
    from session.message_store import MessageStore
    from session.record_transcript import record_transcript_sync
    from session.transcript_blobs import message_fields
    from session.recovery_result_chain import supersessions
    from engine.query_loop import _repair_unpaired_tool_calls
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    rows = recovered() + [result("pending", "actual result=137")]
    path = tmp_path / "transcript.jsonl"
    record_transcript_sync([message_from_row(row) for row in rows], session_id="recovery-chain", path=path, known_ids=set())
    original = path.read_bytes()
    restored = messages_from_transcript(path, session_id="recovery-chain")
    assert [message_fields(item) for item in restored] == rows
    assert supersessions(restored) == {(3, "pending"): 2}
    store = MessageStore(restored)
    expected = deepcopy(store.items)
    store.as_api_messages()
    _repair_unpaired_tool_calls(store)
    assert store.items == expected and path.read_bytes() == original


def test_checkpoint_verification_uses_actual_result_not_unknown_observation():
    from synaptic.task_verification import collect
    rows = recovered() + [result("pending", "actual result=137")]
    rows[-1]["content"][0]["is_error"] = False
    observations, unknown, nodes = collect(rows, ["pending"], len(rows))
    assert not unknown and observations[0]["result"] == "actual result=137"
    assert observations[0]["source"] == 3 and observations[0]["is_error"] is False
    assert nodes == (1, 3)


@pytest.mark.parametrize("native", [False, True])
def test_actual_result_after_original_call_was_folded_keeps_head_and_recovers(monkeypatch, tmp_path, native):
    from memory.runtime import force_compact, project_for_model
    from memory.working import WorkingSnapshot, flush, hydrate
    from memory import wsc_projection
    from prompt.assembler import PromptAssembler
    from session.late_result_guard import request_conflict
    from evals.wsc_unfolded_source_ab import environment
    import os
    with environment(tmp_path):
        os.environ["XEYO_WSC"] = str(int(native))
        os.environ["XEYO_LATE_RESULT_PROJECTION"] = "1"
        rows = recovered() + [{"id": f"work-{index}", "role": "assistant",
                               "content": "recorded work " + "field " * 500} for index in range(24)]
        original = deepcopy(rows)
        working = WorkingSnapshot(session_id="recovered-cold-" + str(native))
        wsc_projection._STATE.clear()
        first = force_compact(rows, working, cwd=tmp_path)
        cursor = working.compact_cursor
        assert cursor > 3
        extended = rows + [result("pending", "actual result=137")]
        current = project_for_model(extended, working, cwd=tmp_path, capacity_managed=True, context_limit=1000000)
        assert current[0] == first[0] and working.compact_cursor == cursor
        assert request_conflict(current) is None
        sent = PromptAssembler().build("fixture", current)
        assert "after_recovery_observation" in json.dumps(sent)
        assert "actual result=137" in json.dumps(sent)
        flush(working.session_id, working)
        wsc_projection._STATE.clear()
        restored = hydrate(working.session_id, source_layout=working.compression_source_layout)
        replay = project_for_model(extended, restored, cwd=tmp_path, capacity_managed=True, context_limit=1000000)
        assert replay == current and rows == original
