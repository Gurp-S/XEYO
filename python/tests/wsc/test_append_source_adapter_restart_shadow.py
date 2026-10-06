import importlib
from pathlib import Path

from session.compression_source import compression_messages
from evals.wsc_source_contract import APPEND
import asyncio
import pytest
from memory import working as state_store
from memory.runtime import force_compact, project_for_model
from memory.working import WorkingSnapshot
from msgtypes.message import user_message, system_note, assistant_text_message
from session.message_store import MessageStore


@pytest.mark.parametrize("memory_mode", ["project", "v61"])
def test_native_append_restart_preserves_projection_and_readable_cold(monkeypatch, tmp_path, mem_switch, memory_mode):
    for key, value in {"XEYO_HOME": str(tmp_path / "home"),
                       "XEYO_SESSIONS_DIR": str(tmp_path / "sessions"),
                       "XEYO_WSC": "1", "XEYO_WSC_FROZEN_HEAD": "1",
                       "XEYO_WSC_HEAD_STORE": "1", "XEYO_WSC_OFFLINE": "1",
                       "XEYO_WSC_CADENCE_ABSORB": "0"}.items():
        monkeypatch.setenv(key, value)
    mem_switch(XEYO_L5=memory_mode)
    wp = importlib.import_module("memory.wsc_projection")
    store = MessageStore([user_message("Keep API v1. Investigate AssertionError timeout.")])
    for i in range(40):
        store.append(system_note(f"old state {i}", key="world_state", fp=str(i)))
        store.append(assistant_text_message(f"observed fact {i}: " + "result " * 100))
    snapshot = WorkingSnapshot(session_id="append-adapter-restart")
    snapshot.compression_source_layout = APPEND
    wp._STATE.clear()
    try:
        force_compact(compression_messages(store, snapshot), snapshot, cwd=str(tmp_path))
        before = project_for_model(compression_messages(store, snapshot), snapshot,
                                   cwd=str(tmp_path), include_memory_index=False)
        cached = wp._STATE[wp._state_key(snapshot.session_id, str(tmp_path))]
        cold = Path(cached.view_path)
        saved_cold = cold.read_bytes()
        state_store.flush(snapshot.session_id, snapshot)
        wp._STATE.clear()
        resumed = state_store.hydrate(snapshot.session_id, source_layout=APPEND)
        assert resumed.compression_source_layout == APPEND
        after = project_for_model(compression_messages(store, resumed), resumed,
                                  cwd=str(tmp_path), include_memory_index=False)
        assert after == before
        assert resumed.compact_cursor == snapshot.compact_cursor
        assert cold.read_bytes() == saved_cold
        # Check real Read against a published archive, not just bytes-on-disk.
        from engine.abort import AbortController
        from tools.file_read_tool.file_read_tool import FileReadTool
        monkeypatch.setenv("XEYO_TOOL_OFFLOAD", "0")
        receipt = asyncio.run(FileReadTool(cwd=str(tmp_path)).execute(
            dict(file_path=str(cold), offset=1, limit=2000), AbortController()))
        assert not receipt.is_error
        archive = saved_cold.decode("utf-8")
        for line in archive.splitlines():
            if line.strip():
                assert line in receipt.content
        assert "observed fact" in receipt.content
    finally:
        wp._STATE.clear()
