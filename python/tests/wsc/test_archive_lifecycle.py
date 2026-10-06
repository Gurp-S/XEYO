"""A head needs an archive when replaced, not when still fully visible."""
from dataclasses import replace

from synaptic.coldstore import head_handle
from synaptic.project import project
from synaptic.types import WscParams
from tests.wsc._fixtures import synth_session


def _first(tmp_path):
    messages = synth_session(turns=8, user_every=1)
    params = replace(WscParams(), handle_style="read", journal_growth_tokens=1)
    mid = len(messages) // 2
    path = tmp_path / "cold.txt"
    first = project(messages[:mid], region_end=mid, params=params, view_path=path)
    return messages, params, path, first


def test_append_has_no_redundant_archive_and_preserves_old_ranges(tmp_path):
    messages, params, path, first = _first(tmp_path)
    old_ranges = first.cold.render_text_view()[1]
    later = project(messages, region_end=len(messages), params=params,
                    prev=first.state, cold=first.cold, view_path=path)
    assert later.result.journal_refroze and not later.result.rebuilt
    assert later.text.startswith(first.text)
    assert "[HEAD] previous=" not in later.text
    assert not later.cold.snapshots
    new_ranges = later.cold.render_text_view()[1]
    assert old_ranges and all(new_ranges[k] == v for k, v in old_ranges.items())


def test_rebase_after_append_archives_the_actual_displaced_head(tmp_path):
    messages, params, path, first = _first(tmp_path)
    later = project(messages, region_end=len(messages), params=replace(params, journal_rebase=True),
                    prev=first.state, cold=first.cold, view_path=path)
    assert later.result.rebuilt
    handle = head_handle(first.text)
    assert later.cold.expand(handle) == (first.text,)
    assert handle in later.cold.render_text_view()[1]
    assert "[HEAD] previous=" in later.text


def test_existing_archive_and_its_read_range_survive_an_append(tmp_path):
    messages, params, path, first = _first(tmp_path)
    handle = head_handle("legacy archived head")
    first.cold.put_snapshot(handle, "legacy archived head")
    old_ranges = first.cold.render_text_view()[1]
    later = project(messages, region_end=len(messages), params=params,
                    prev=first.state, cold=first.cold, view_path=path)
    assert later.cold.expand(handle) == ("legacy archived head",)
    assert later.cold.snapshots == {handle: "legacy archived head"}
    new_ranges = later.cold.render_text_view()[1]
    assert all(new_ranges[k] == v for k, v in old_ranges.items())


def test_layout_switch_preserves_previous_archive_behavior(tmp_path):
    messages, params, path, first = _first(tmp_path)
    later = project(messages, region_end=len(messages), params=replace(params, journal_layout=False),
                    prev=first.state, cold=first.cold, view_path=path)
    assert later.cold.expand(head_handle(first.text)) == (first.text,)
