from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from memory import working
from memory.working import WorkingSnapshot, CompactCheckpoint
from memory.wsc_source_layout import APPEND, LEGACY


def saved(monkeypatch, tmp_path, layout):
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    snapshot = WorkingSnapshot(session_id="native-source-working", compact_cursor=4,
        c1_frozen_until=4, c2_gap_shots=17, agent_mode="ask",
        todos=[{"content": "verify task", "status": "pending"}],
        read_file_state={"src/config.py": {"offset": 1, "limit": 20}},
        compact_checkpoint=CompactCheckpoint(anchor_cursor=6, anchor_frozen_until=6))
    snapshot.compression_source_layout = layout
    working.flush(snapshot.session_id, snapshot)
    return snapshot


def test_default_serialization_preserves_legacy_format_and_checkpoint(monkeypatch, tmp_path):
    snapshot = saved(monkeypatch, tmp_path, LEGACY)
    payload = json.loads(working.path_for(snapshot.session_id).read_text())
    assert "compression_source_layout" not in payload
    resumed = working.hydrate(snapshot.session_id)
    assert resumed.compact_cursor == resumed.c1_frozen_until == 6
    assert not resumed.compression_source_rebuilt
    assert resumed.todos == snapshot.todos


def test_unconfigured_entrypoint_rebuilds_foreign_coordinates_without_losing_user_state(monkeypatch, tmp_path):
    snapshot = saved(monkeypatch, tmp_path, APPEND)
    original_file = working.path_for(snapshot.session_id).read_bytes()
    history = tmp_path / "raw-history.jsonl"
    history.write_text('unchanged raw source\n', encoding="utf-8")
    cold = tmp_path / "old-cold.txt"
    cold.write_text('unchanged cold original\n', encoding="utf-8")
    resumed = working.hydrate(snapshot.session_id)
    assert resumed.compression_source_layout == LEGACY
    assert resumed.compression_source_rebuilt
    assert resumed.compact_cursor == resumed.c1_frozen_until == resumed.c2_gap_shots == 0
    assert resumed.compact_checkpoint is None
    assert resumed.agent_mode == snapshot.agent_mode
    assert resumed.todos == snapshot.todos and resumed.read_file_state == snapshot.read_file_state
    assert working.path_for(snapshot.session_id).read_bytes() == original_file
    assert history.read_text() == 'unchanged raw source\n'
    assert cold.read_text() == 'unchanged cold original\n'


def test_concurrent_restore_has_explicit_independent_source_contract(monkeypatch, tmp_path):
    snapshot = saved(monkeypatch, tmp_path, APPEND)
    persisted = working.path_for(snapshot.session_id).read_bytes()
    def read(layout):
        result = working.hydrate(snapshot.session_id, source_layout=layout)
        assert result.compression_source_layout == layout
        assert result.todos == snapshot.todos
        assert result.compact_cursor == (6 if layout == APPEND else 0)
        assert result.compression_source_rebuilt == (layout != APPEND)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(read, [APPEND, LEGACY] * 12))
    assert working.path_for(snapshot.session_id).read_bytes() == persisted
    with pytest.raises(ValueError, match="unknown compression source"):
        working.hydrate(snapshot.session_id, source_layout="unrecognized")
