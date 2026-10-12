from pathlib import Path

from evals.wsc_unfolded_source_ab import environment


def test_actual_offline_force_keeps_existing_usage_ledgers_unchanged(tmp_path, monkeypatch):
    from memory.runtime import force_compact
    from memory.working import WorkingSnapshot
    from usage.ledger import usage_dir
    shared = tmp_path / "shared-usage"
    shared.mkdir()
    paths = [shared / name for name in ("events.jsonl", "c2_events.jsonl", "fold_events.jsonl")]
    for path in paths: path.write_bytes(b'{"existing":true}\n')
    before = {path: path.read_bytes() for path in paths}
    monkeypatch.setenv("XEYO_USAGE_DIR", str(shared))
    output = tmp_path / "offline"
    output.mkdir()
    with environment(output):
        assert usage_dir() == output / "usage"
        rows = [{"id": f"a{i}", "role": "assistant", "content": "已观察档案 " + "x" * 500} for i in range(25)]
        working = WorkingSnapshot(session_id="offline-force")
        force_compact(rows, working, cwd=output)
        assert working.compact_cursor > 0
        assert (output / "usage" / "c2_events.jsonl").is_file()
    assert usage_dir() == shared
    assert all(path.read_bytes() == data for path, data in before.items())
