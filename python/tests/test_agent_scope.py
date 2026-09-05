"""Wave 6：agent_scope 记忆边界。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.agent_scope import (
    attach_subagent_result,
    filter_tool_names_for_scope,
    format_subagent_summary,
    handoff_from_run_result,
    scoped_session_id,
    scope_for,
)
from memory.governance import MemoryCandidate
from session.message_store import MessageStore


def test_scope_for_main_vs_sub():
    main = scope_for("main")
    assert main.can_write_memdir is True
    assert main.can_write_session_md is True
    assert main.share_kv_prefix is True

    sub = scope_for("agent-t1-abc")
    assert sub.can_write_memdir is False
    assert sub.can_write_session_md is False
    assert sub.share_kv_prefix is False


def test_scoped_session_id_isolates_subagent():
    assert scoped_session_id("sess-main", "main") == "sess-main"
    assert scoped_session_id("sess-main", "") == "sess-main"
    key = scoped_session_id("sess-main", "agent-x")
    assert key != "sess-main"
    assert "agent-x" in key


def test_filter_tool_names_strips_memory_for_sub():
    names = ["Read", "Write", "Memory", "Edit"]
    assert filter_tool_names_for_scope(names, "main") == names
    assert filter_tool_names_for_scope(names, "agent-a") == [
        "Read",
        "Write",
        "Edit",
    ]


def test_format_subagent_summary_with_candidates():
    h = handoff_from_run_result(
        agent_id="agent-z",
        conclusion="done",
        files_touched=["src/a.ts"],
        memories=[
            MemoryCandidate(content="prefer pytest", source={"kind": "agent"}),
        ],
    )
    text = format_subagent_summary(h)
    assert "done" in text
    assert "src/a.ts" in text
    assert "pytest" in text


def test_attach_subagent_result_tool_path():
    store = MessageStore()
    h = handoff_from_run_result(agent_id="agent-a", conclusion="ok")
    msg = attach_subagent_result(store, h, tool_use_id="call-1", tool_name="Agent")
    assert len(store) == 1
    assert msg.role == "tool"
    assert msg.tool_call_id == "call-1"
    assert "ok" in str(msg.content)


def test_attach_subagent_result_fallback_user_message():
    store = MessageStore()
    msg = attach_subagent_result(store, "summary only")
    assert len(store) == 1
    assert msg.role == "user"
    assert "summary only" in str(msg.content)


def test_normalize_and_enqueue_candidates(tmp_path, monkeypatch):
    import os

    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / "mem"))
    from memory.agent_scope import enqueue_subagent_candidates, normalize_memory_candidates
    from memory.memdir import candidates_path, workspace_id
    from memory.nightshift import load_candidates

    ws = str(tmp_path)
    os.chdir(ws)
    wsid = workspace_id(ws)
    cands = normalize_memory_candidates(
        [{"content": "prefer pytest", "source": {"kind": "agent"}}],
        main_session_id="sess-1",
        agent_id="agent-a",
    )
    assert len(cands) == 1
    assert cands[0].source.get("session_id") == "sess-1"
    h = handoff_from_run_result(
        agent_id="agent-a",
        conclusion="ok",
        memories=[{"content": "prefer pytest"}],
    )
    n = enqueue_subagent_candidates(ws, [h], main_session_id="sess-1")
    assert n == 1
    loaded = load_candidates(wsid)
    assert len(loaded) == 1
    assert "pytest" in loaded[0].content
    assert candidates_path(wsid).is_file()


@pytest.mark.asyncio
async def test_persist_multi_agent_turn_no_extra_user_bubble():
    from memory.agent_scope import persist_multi_agent_turn
    from session.message_store import MessageStore

    class FakeSession:
        def __init__(self) -> None:
            self.messages = MessageStore()
            self.session_id = "sess-live"
            self.cwd = "."
            self.transcript_known_ids: set[str] = set()

        def is_session_persistence_disabled(self) -> bool:
            return True

    engine = type("E", (), {"_session": FakeSession()})()
    await persist_multi_agent_turn(
        engine,
        user_text="跑 multi",
        user_message_id="u1",
        task_rows=[
            {
                "agent_id": "agent-x",
                "status": "done",
                "result": "done ok",
                "memories": [],
            }
        ],
        summary_md="### 多 Agent 运行结果",
    )
    roles = [m.role for m in engine._session.messages.items]
    assert roles == ["user", "assistant"]


def test_append_candidates_dedupes(tmp_path, monkeypatch):
    from memory.governance import MemoryCandidate
    from memory.memdir import workspace_id
    from memory.nightshift import append_candidates, load_candidates

    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / "mem"))
    wsid = workspace_id(str(tmp_path))
    c1 = MemoryCandidate(
        content="same fact",
        source={"kind": "agent", "session_id": "sess-old", "agent_id": "a1"},
        evidence=["subagent_marker"],
    )
    c2 = MemoryCandidate(
        content="same fact",
        source={"kind": "agent", "session_id": "sess-new", "agent_id": "a2"},
        evidence=["subagent_marker"],
    )
    assert append_candidates(wsid, [c1]) == 1
    assert append_candidates(wsid, [c2]) == 0
    loaded = load_candidates(wsid)
    assert len(loaded) == 1
    assert loaded[0].source.get("session_id") == "sess-new"
    assert loaded[0].source.get("agent_id") == "a2"
