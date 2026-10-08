"""Lost cold state must never overwrite a previously published Read range."""
from dataclasses import replace
from pathlib import Path

import pytest

from memory.wsc_continuation import resume_inputs
from tests.wsc.test_head_store import store, _W
from tests.wsc._fixtures import synth_session
from engine.compact import keep_tail_cut


@pytest.mark.parametrize("rebase", [False, True])
@pytest.mark.parametrize("advance_before_restore", [False, True])
def test_restart_then_fold_preserves_old_source(store, monkeypatch, rebase, advance_before_restore):
    _, wp = store
    original = wp.production_params
    monkeypatch.setattr(wp, "production_params", lambda: replace(original(), journal_rebase=rebase))
    messages = synth_session(turns=26, error_turn=4)
    working = _W(int(keep_tail_cut(messages)))
    first = wp.project_c2_messages(messages, working)
    assert first
    previous = next(iter(wp._STATE.values()))
    old_path = Path(previous.view_path)
    old_bytes = old_path.read_bytes()
    old_ranges = previous.cold.render_text_view()[1]
    wp._STATE.clear()
    messages += synth_session(turns=8, error_turn=2)
    next_cursor = int(keep_tail_cut(messages))
    assert next_cursor > working.compact_cursor
    if not advance_before_restore:
        reused = wp.project_c2_messages(messages, working)
        assert reused[0]["content"] == first[0]["content"]
    working.compact_cursor = next_cursor
    second = wp.project_c2_messages(messages, working)
    assert second
    current = next(iter(wp._STATE.values()))
    assert Path(current.view_path) != old_path
    assert old_path.read_bytes() == old_bytes
    assert len(old_ranges) > 0
    from tests.wsc._recovery_contract import parse_read_refs
    from tests.wsc.test_cold_read_view import FileReadTool, _read, _strip_line_numbers

    reference = parse_read_refs(previous.head)[0]
    receipt = _read(FileReadTool(cwd=previous.cwd), old_path,
                    offset=reference.offset, limit=reference.limit)
    source_lines = old_bytes.decode("utf-8").replace("\r\n", "\n").split("\n")
    assert _strip_line_numbers(receipt) == "\n".join(source_lines[reference.offset-1:reference.offset-1+reference.limit])
    # The old emission is either a strict prefix or an exact archived snapshot.
    assert current.head.startswith(previous.head) or previous.head in current.cold.snapshots.values()
    # Subsequent folds with known cold layout append in that same generation.
    raw, ranges = current.cold.render_text_view()
    messages += synth_session(turns=4, error_turn=1)
    working.compact_cursor = int(keep_tail_cut(messages))
    assert wp.project_c2_messages(messages, working)
    latest = next(iter(wp._STATE.values()))
    assert latest.view_path != current.view_path
    assert Path(current.view_path).read_text(encoding="utf-8") == raw
    assert latest.cold.render_text_view()[0].startswith(raw)
    assert all(latest.cold.render_text_view()[1][h] == span for h, span in ranges.items())


def test_old_generation_large_receipt_survives_emit_and_other_files_do_not(tmp_path):
    from memory.wsc_projection import _emit
    from tests.wsc.test_cold_read_view import FileReadTool, _read

    current = tmp_path / "s.g-0123456789abcdef-0.txt"
    for path, preserved in [(tmp_path / "s.txt", True),
                            (tmp_path / "s.g-fedcba9876543210-4.txt", True),
                            (tmp_path / "other.txt", False),
                            (tmp_path / "s.g-invalid-0.txt", False),
                            (tmp_path / "another" / "s.txt", False)]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x" * 9000, encoding="utf-8")
        raw = _read(FileReadTool(cwd=str(tmp_path)), path, offset=1, limit=1)
        messages = [dict(role="assistant", content=[dict(type="tool_use", id="r", name="Read", input=dict(file_path=str(path)))]),
                    dict(role="user", content=[dict(type="tool_result", tool_use_id="r", is_error=False, content=raw)])]
        emitted = _emit("[HEAD] recovery", messages, 0, 0, cwd=str(tmp_path), view_path=current)
        # Main timing retains every unfolded receipt, regardless of path family.
        assert emitted[-1]["content"][0]["content"].split("\n", 1)[1] == raw


def test_multiple_restarts_keep_one_session_family(tmp_path):
    from types import SimpleNamespace
    from memory.wsc_continuation import prior_generation

    original = tmp_path / "s.txt"
    paths = [original]
    for _ in range(3):
        paths[-1].write_text("published cold source\n", encoding="utf-8")
        cached = SimpleNamespace(prev=None, cold=None, head="[WORKING SET] state")
        previous, _, path = resume_inputs(cached, paths[-1], mode="closure", level="Medium+")
        assert previous.full_text == "\n".join(f"{h} {line}" for h, line in previous.journal)
        assert path.stem.count(".g-") == 1
        assert all(prior_generation(str(path), str(old)) for old in paths)
        paths.append(path)


def test_existing_untracked_source_is_preserved_without_saved_head(tmp_path):
    path = tmp_path / "cold.txt"
    path.write_text("old arbitrary layout\n", encoding="utf-8")
    previous, cold, generated = resume_inputs(None, path, mode="closure", level="Medium+")
    assert previous is cold is None
    assert generated != path and not generated.exists()
    assert path.read_text(encoding="utf-8") == "old arbitrary layout\n"
