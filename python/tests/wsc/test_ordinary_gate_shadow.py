from types import SimpleNamespace

import pytest

from evals.wsc_ordinary_gate import ordinary_gate
from memory import runtime
from memory.wsc_source_layout import APPEND, LEGACY


def test_shadow_changes_only_proxy_readers_and_restores_after_failure():
    rows = [{"role": "user", "content": "ordinary"},
            {"role": "system", "content": "state" * 100, "note_key": "world_state"}]
    names = ("_region_tokens", "_region_chars", "c2_summary_extension")
    original = {name: getattr(runtime, name) for name in names}
    expected = original["_region_tokens"](rows[:1])
    with pytest.raises(RuntimeError, match="probe"):
        with ordinary_gate(SimpleNamespace(compression_source_layout=APPEND), True):
            assert runtime._region_tokens(rows) == expected
            assert runtime._region_chars(rows) == len("ordinary")
            assert runtime.c2_summary_extension(rows) == original["c2_summary_extension"](rows[:1])
            assert rows[1]["content"] == "state" * 100
            raise RuntimeError("probe")
    for name, function in original.items():
        assert getattr(runtime, name) is function


@pytest.mark.parametrize("layout,enabled", [(LEGACY, True), (APPEND, False)])
def test_shadow_is_inert_for_legacy_and_disabled(layout, enabled):
    original = runtime._region_tokens
    with ordinary_gate(SimpleNamespace(compression_source_layout=layout), enabled):
        assert runtime._region_tokens is original
