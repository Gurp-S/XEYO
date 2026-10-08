from types import SimpleNamespace

from memory.wsc_handoff_scope import needs_refresh
from tests.wsc._fixtures import msg_asst_use, msg_tool


def test_only_pure_compact_protocol_is_not_new_task_material():
    snapshot = SimpleNamespace(observed=True, checkpoint={}, source=0)
    base = [{"role": "assistant", "content": "已提交声明"}]
    protocol = [msg_asst_use("compact", "Compact", {}), msg_tool("compact", "Compact", "accepted")]
    assert needs_refresh(base + protocol, snapshot) is False
    for row in ({"role": "user", "content": "新规范"}, {"role": "assistant", "content": "新决定"},
                msg_asst_use("read", "Read", {}), msg_tool("unknown", "Read", "晚到规范")):
        assert needs_refresh(base + protocol + [row], snapshot) is True
    assert needs_refresh(base + protocol + [{"role": "user", "content": "engine", "note_key": "runtime"}], snapshot) is False


def test_ambiguous_compact_identity_does_not_hide_task_receipts():
    rows = [msg_asst_use("shared", "Compact", {}), msg_asst_use("shared", "Read", {}),
            msg_tool("shared", "Read", "new data")]
    assert needs_refresh(rows, SimpleNamespace(observed=True, checkpoint={}, source=1)) is True


def test_managed_projection_leaves_successful_request_pending_without_folding(monkeypatch, tmp_path):
    from memory.runtime import project_for_model
    from memory.working import WorkingSnapshot
    from memory.wsc_timing import accepted_request
    from engine.execution_facts import tool_receipt
    from tools.base_tool import ToolResult
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    monkeypatch.setenv("XEYO_WSC", "0")
    working = WorkingSnapshot(session_id="pending-request")
    rows = [{"role": "assistant", "content": "历史 " + "x" * 1000} for _ in range(20)]
    rows += [msg_asst_use("compact", "Compact", {}), msg_tool("compact", "Compact", "accepted")]
    rows[-1]["content"][0]["execution"] = tool_receipt(ToolResult("accepted",
        metadata={"compaction_request": {"version": 1, "accepted": True}}))
    before = accepted_request(rows, working)
    project_for_model(rows, working, context_limit=1_000_000, capacity_managed=True,
                      include_memory_index=False, cwd=tmp_path)
    assert working.compact_cursor == 0 and accepted_request(rows, working) == before == "compact"
