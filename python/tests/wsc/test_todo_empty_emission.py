"""Observed zero closes stale pending state without a full TODO snapshot."""
from synaptic.project import project
from memory.wsc_projection import production_params
from tests.wsc._fixtures import msg_user, msg_asst_use, msg_tool
from tests.wsc.test_todo_snapshot import event, item


def test_clear_reopen_clear_preserves_prefix_and_emits_latest_state(tmp_path):
    history = [msg_user("Complete the work")]
    before = None
    for uid, tasks in [("a", [item("a", "Build")]), ("b", []),
                       ("c", [item("c", "Verify")]), ("d", [])]:
        history += event(uid, tasks, tasks)
        after = project(history, region_end=len(history), params=production_params(),
                        prev=before.state if before else None, cold=before.cold if before else None,
                        view_path=tmp_path / "cold.txt")
        if before:
            assert after.text.startswith(before.text)
            assert after.cold.render_text_view()[0].startswith(before.cold.render_text_view()[0])
        todo_rows = [line for line in after.text.splitlines() if line.startswith("[TODO]")]
        assert todo_rows
        assert ("observed active=0" in todo_rows[-1]) == (not tasks)
        if not tasks:
            assert any(p.text == "observed active=0" and p.nodes for p in after.result.hot.pins)
        before = after


def test_failed_or_unobserved_empty_write_does_not_emit_clear(tmp_path):
    for suffix in [[], [msg_asst_use("unobserved", "TodoWrite", {"todos": []})],
                   [msg_asst_use("failed", "TodoWrite", {"todos": []}),
                    msg_tool("failed", "TodoWrite", "Permission denied", is_error=True)]]:
        history = [msg_user("Finish work")] + event("initial", [item("a", "Build")], [item("a", "Build")]) + suffix
        after = project(history, region_end=len(history), params=production_params(), view_path=tmp_path / "cold.txt")
        assert "observed active=0" not in after.text
        assert "[pending] Build" in after.text
