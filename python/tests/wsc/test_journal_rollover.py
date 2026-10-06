"""日志换头保留旧信息入口；默认策略和非折叠冻结不改变。"""

from dataclasses import replace

from synaptic.coldstore import ColdStore, head_handle
from synaptic.handles import HandleRenderer
from synaptic.journal_rollover import rebase_journal
from synaptic.project import project
from synaptic.types import WscParams


def test_rebase_requires_archive_and_preserves_read_range(tmp_path):
    old = "constraint: keep API\nerror: RuntimeError\n"
    cold = ColdStore(session="s")
    handle = head_handle(old)
    cold.put_snapshot(handle, old)
    path = tmp_path / "cold.txt"
    ranges = cold.write_text_view(path)
    renderer = HandleRenderer(style="read", path="cold.txt", node_ranges=ranges)
    fresh = (("[WORKING SET]", "a.py current"),)
    assert rebase_journal(fresh, old_head_handle="", handles=renderer) is None
    rebased = rebase_journal(fresh, old_head_handle=handle, handles=renderer)
    assert rebased[:-1] == fresh
    assert renderer.extract(rebased[-1][1]) == (handle,)
    assert cold.snapshots[handle] == old


def test_rebase_is_opt_in_and_for_level_preserves_choice():
    assert not WscParams().journal_rebase
    assert WscParams(journal_rebase=True).for_level("Medium+").journal_rebase


def test_threshold_rebase_drops_stale_line_and_archives_previous_head():
    from synaptic.assemble import AssemblyState
    messages = [{"role": "user", "content": "keep existing API"},
                {"role": "assistant", "content": "current implementation"}]
    cold = ColdStore(session="s")
    stale = "[WORKING SET] stale-version-that-is-no-longer-current"
    prev = AssemblyState(level="Medium+", mode="closure", full_text=stale,
                         journal=(("[WORKING SET]", "stale-version-that-is-no-longer-current"),))
    params = replace(WscParams(journal_rebase=True), journal_growth_tokens=1)
    folded = project(messages, region_end=2, params=params, prev=prev, cold=cold)
    assert folded.result.rebuilt
    assert "stale-version-that-is-no-longer-current" not in folded.text
    assert head_handle(stale) in folded.text
    assert cold.snapshots[head_handle(stale)] == stale
