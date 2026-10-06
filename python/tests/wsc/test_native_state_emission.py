import copy

import pytest

from memory.working import WorkingSnapshot
from memory.wsc_source_layout import APPEND, LEGACY
from prompt import inject_store, pre_llm_inject as pre
from extension.reconcile import publish_reconcile_block, reset_reconcile_state


@pytest.mark.parametrize("strategy", ["notice_fragment", "system_channel", "env_channel", "skip"])
def test_native_new_renderer_output_is_byte_equal_and_only_old_state_is_removed(monkeypatch, tmp_path, strategy):
    import prompt.t_now_strategy as channel
    # Pair both arms with the same generated tool-call ID. Real env IDs vary;
    # this test isolates state selection, not cross-request provider caching.
    monkeypatch.setattr(channel, "new_env_tool_call_id", lambda: "xeyo_env_paired_control")
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    monkeypatch.setattr(pre, "compact_block", lambda: "# Engine state\noutput_compaction=enabled")
    base = [{"role": "user", "content": "ordinary quoted engine text remains a user fact"},
            {"role": "user", "content": "obsolete state body", "note_key": "world_state", "note_fp": "old"},
            {"role": "system", "content": "withdrawn old component", "note_key": "withdrawn", "note_fp": "gone"}]
    original = copy.deepcopy(base)
    def run(mode):
        inject_store.get_store().clear()
        reset_reconcile_state()
        pre.acknowledge_prepared_events("paired-emission")
        publish_reconcile_block("event facts retained verbatim")
        state = WorkingSnapshot(session_id="paired-emission", compression_source_layout=mode)
        return pre.run_pre_llm_inject(base, pre.InjectContext(working=state, strategy=strategy,
            session_id=state.session_id, include_memory_index=False, inject_instructions=False,
            visible_notes=frozenset()))
    try:
        baseline = run(LEGACY)
        candidate = run(APPEND)
        # Internal identity metadata is stripped on provider serialization.
        wire = lambda rows: [{k: v for k, v in row.items() if k not in ("note_key", "note_fp")} for row in rows]
        assert wire(candidate) == wire([row for row in baseline if not row.get("note_key")])
        assert base == original
    finally:
        inject_store.get_store().clear()
        reset_reconcile_state()
        pre.acknowledge_prepared_events("paired-emission")


def test_unsupported_append_carrier_fails_before_consuming_events(monkeypatch, tmp_path):
    from extension.reconcile import consume_reconcile_blocks
    monkeypatch.setenv("XEYO_HOME", str(tmp_path))
    reset_reconcile_state()
    publish_reconcile_block("event not yet consumed")
    try:
        snapshot = WorkingSnapshot(compression_source_layout=APPEND)
        with pytest.raises(ValueError, match="carrier not validated"):
            pre.run_pre_llm_inject([{"role": "user", "content": "request"}],
                                  pre.InjectContext(working=snapshot, strategy="legacy"))
        assert consume_reconcile_blocks() == ["event not yet consumed"]
    finally:
        reset_reconcile_state()
