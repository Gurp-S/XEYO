"""Work elimination must preserve source truth, ordering and retention scope."""
import json
import sqlite3
import threading
from dataclasses import replace
from pathlib import Path

import pytest


def make_note(note_id="one", **extra):
    from memory.governance import parse_and_validate
    return parse_and_validate(dict(id=note_id, type="project", source={"kind": "user"},
                                   confidence=1, status="active", **extra), "persistent evidence")


def test_connection_closes_and_rolls_back(tmp_path, monkeypatch):
    from memory import memindex
    monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path))
    with pytest.raises(RuntimeError):
        with memindex._connect("workspace") as conn:
            conn.execute("INSERT INTO meta VALUES ('rollback','yes')")
            raise RuntimeError("abort transaction")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
    with memindex._connect("workspace") as reopened:
        assert reopened.execute("SELECT v FROM meta WHERE k='rollback'").fetchone() is None


def test_single_file_update_does_not_scan_or_delete_siblings(tmp_path, monkeypatch):
    from memory import memdir, memindex
    monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path))
    first = memdir.write_note(make_note(), wsid="workspace")
    second = memdir.write_note(make_note("two"), wsid="workspace")
    def no_scan(*args, **kwargs):
        pytest.fail("single-file write-through scanned the directory")
    monkeypatch.setattr(memindex, "_sync_table", no_scan)
    first.write_text(first.read_text(encoding="utf-8").replace("persistent evidence", "changed evidence"), encoding="utf-8")
    memindex.upsert_note_file("workspace", first)
    with memindex._connect("workspace") as conn:
        rows = dict(conn.execute("SELECT path,body FROM notes"))
    assert "changed evidence" in rows[first.name]
    assert "persistent evidence" in rows[second.name]


def test_touch_skips_same_day_and_preserves_deleted_note(tmp_path, monkeypatch):
    from memory import memdir
    from memory.governance import today_iso
    monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path))
    note = make_note(last_used_at=today_iso())
    path = memdir.write_note(note, wsid="workspace")
    before = path.stat().st_mtime_ns, path.read_bytes()
    def no_scan(*args, **kwargs):
        pytest.fail("canonical identity read scanned the memory directory")
    monkeypatch.setattr(memdir, "load_notes", no_scan)
    assert memdir.touch_last_used(note, wsid="workspace") == note
    assert (path.stat().st_mtime_ns, path.read_bytes()) == before
    memdir.write_note(replace(note, status="deleted"), wsid="workspace")
    memdir.touch_last_used(note, wsid="workspace")
    assert memdir.find_note("workspace", note.id).status == "deleted"


def test_write_through_preserves_crlf_loader_semantics_and_hash(tmp_path, monkeypatch):
    from memory import memdir, memindex, memindex_sig_shadow
    monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path))
    path = memdir.write_note(make_note(), wsid="workspace")
    raw = path.read_bytes().replace(b"\n", b"\r\n")
    path.write_bytes(raw)
    monkeypatch.setattr(memindex, "_sync_table", memindex_sig_shadow._sync_table_content_hash)
    memindex.upsert_note_file("workspace", path)
    with memindex._connect("workspace") as conn:
        sha, fm, body = conn.execute("SELECT sha,fm_json,body FROM notes WHERE path=?", (path.name,)).fetchone()
    assert (fm, body) == memindex._load_note_file(path)
    assert sha == memindex._sha(raw.decode("utf-8"))


def test_touch_first_use_keeps_index_text_and_avoids_migration_scan(tmp_path, monkeypatch):
    from memory import memdir, memindex
    monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path))
    note = make_note(last_used_at="2000-01-01")
    path = memdir.write_note(note, wsid="workspace")
    index = path.parent.parent / "MEMORY.md"
    before = index.read_bytes()
    def no_glob(*args, **kwargs):
        pytest.fail("touch enumerated legacy files")
    monkeypatch.setattr(Path, "glob", no_glob)
    updated = memdir.touch_last_used(note, wsid="workspace")
    assert updated.last_used_at != note.last_used_at
    assert updated.updated_at == note.updated_at
    assert index.read_bytes() == before
    with memindex._connect("workspace") as conn:
        fm = json.loads(conn.execute("SELECT fm_json FROM notes WHERE path=?", (path.name,)).fetchone()[0])
    assert fm["last_used_at"] == updated.last_used_at


def test_deleted_writer_waits_for_touch_read_modify_write(tmp_path, monkeypatch):
    from memory import memdir, note_access
    monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path))
    note = make_note(last_used_at="2000-01-01")
    memdir.write_note(note, wsid="workspace")
    entered, release, deleted = threading.Event(), threading.Event(), threading.Event()
    original = note_access.find_in_domain
    def paused(*args):
        result = original(*args)
        entered.set()
        assert release.wait(5)
        return result
    monkeypatch.setattr(note_access, "find_in_domain", paused)
    toucher = threading.Thread(target=lambda: memdir.touch_last_used(note, wsid="workspace"))
    def delete():
        memdir.write_note(replace(note, status="deleted"), wsid="workspace")
        deleted.set()
    writer = threading.Thread(target=delete)
    toucher.start()
    try:
        assert entered.wait(5)
        writer.start()
        assert not deleted.wait(.05)
    finally:
        release.set()
        toucher.join(5)
        if writer.ident is not None:
            writer.join(5)
    assert not toucher.is_alive() and not writer.is_alive()
    assert original("workspace", note.id).status == "deleted"


def test_journal_noop_preserves_generation_and_repairs_missing_index(tmp_path, monkeypatch):
    from memory import journal
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    journal.record_change("workspace", journal.ChangeRecord(seq=0, agent_id="test", path="source.py", action="edit", file_hash_after="hash", ts=journal._now()))
    source, index = journal._changes_path("workspace"), journal._index_path("workspace")
    before = (source.stat().st_mtime_ns, index.stat().st_mtime_ns)
    assert journal.gc("workspace") == 0
    assert before == (source.stat().st_mtime_ns, index.stat().st_mtime_ns)
    index.unlink()
    assert journal.gc("workspace") == 0
    assert source.stat().st_mtime_ns == before[0]
    assert journal._journal_fresh("workspace", source)


def test_search_hard_limit(tmp_path):
    from server.workspace_fs import search_entries
    for i in range(12):
        (tmp_path / f"match{i}").write_text("data")
    result = search_entries(str(tmp_path), "match", 3)
    assert len(result["hits"]) == 3 and result["truncated"]


def test_dense_glob_metadata_keeps_ties_and_missing_file_order(tmp_path):
    import os
    from tools.fileio.path_metadata import sort_by_mtime
    files = [f"match{i}.txt" for i in range(16)]
    for name in files:
        path = tmp_path / name
        path.write_text("file")
        os.utime(path, (1000, 1000))
    files.append("missing.txt")
    probes = []
    def stat(path):
        probes.append(path)
        try:
            return os.stat(path).st_mtime
        except OSError:
            return 0.0
    expected = sorted(files[:-1], reverse=True) + ["missing.txt"]
    sort_by_mtime(files, str(tmp_path), stat)
    assert files == expected
    if os.name == "nt":
        assert probes == [str(tmp_path / "missing.txt")]


def test_journal_gc_still_repairs_invalid_bytes_and_malformed_rows(tmp_path, monkeypatch):
    from memory import journal
    monkeypatch.setenv("XEYO_JOURNAL_DIR", str(tmp_path))
    source = journal._changes_path("workspace")
    valid = json.dumps(dict(seq=1, path="file.py", ts=journal._now())).encode()
    source.write_bytes(valid + b"\xff\r\n[]\ninvalid\n")
    assert journal.gc("workspace") == 0
    assert source.read_bytes() == valid + b"\n"
    assert journal._journal_fresh("workspace", source)


def test_projection_inspection_keeps_nested_text_and_detects_mutations():
    from engine.projection_scan import inspect_projection
    message = {"role": "assistant", "content": [{"type": "tool_use", "id": "call"}, {}, [[], None, "full output:"]]}
    canonical = [message, {"content": [{"type": "tool_result", "tool_use_id": "call"}]}]
    projected = [message]
    assert inspect_projection(canonical, projected) == ({"call"}, {"call"}, {"call"}, set(), "assistant tool_use call    full output:")
    message["content"][0]["id"] = "changed"
    assert inspect_projection(canonical, projected)[2] == {"changed"}


def test_spill_cleanup_is_coalesced_and_off_the_caller_thread(tmp_path, monkeypatch):
    from tools.spill_maintenance import schedule
    monkeypatch.chdir(tmp_path)
    root = Path("relative-spill-root")
    expected_root = root.resolve()
    entered, release = threading.Event(), threading.Event()
    calls = []
    def cleanup(root):
        assert root == expected_root and root.is_absolute()
        calls.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
    worker = schedule(root, cleanup)
    try:
        assert entered.wait(5)
        assert schedule(root, cleanup) is worker
        assert calls == [worker.ident] and worker.ident != threading.get_ident()
    finally:
        release.set()
        worker.join(5)
    assert schedule(root, cleanup) is None


def test_spill_hint_has_no_advice_and_no_hook(tmp_path, monkeypatch):
    from sidecar.upgrade import _HOOKED
    from tools.spill import save_text
    monkeypatch.setenv("XEYO_SPILL_DIR", str(tmp_path))
    monkeypatch.setattr("tools.spill_maintenance.schedule", lambda *args, **kw: None)
    ref = save_text("session", "evidence")
    assert ref.hint == f"full output: {ref.path} ({ref.bytes} bytes)"
    assert "tools.spill_shadow" not in _HOOKED
    assert len(list(tmp_path.rglob("*.txt"))) == 1
