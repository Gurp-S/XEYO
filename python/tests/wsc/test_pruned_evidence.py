"""Omitted originals survive outside selection/card coverage and later folds."""
from dataclasses import replace

from synaptic.project import project
from synaptic.coldstore import node_handle
from synaptic.types import WscParams
from tests.wsc._fixtures import synth_session
from tests.wsc.test_cold_read_view import FileReadTool, _read, _strip_line_numbers


def test_every_pruned_original_survives_even_when_cards_are_bounded(tmp_path):
    history = synth_session(turns=16, user_every=3)
    params = replace(WscParams(), main_segment_budget_tokens=100, max_cards=1, handle_style="read")
    view = tmp_path / ".xeyo_offload" / "wsc" / "cold.txt"
    before = project(history, region_end=len(history), params=params, view_path=view)
    kept = set(before.result.hot.kept_nodes)
    omitted = {node.idx for node in before.graph.nodes if node.idx not in kept}
    represented = {idx for card in before.result.hot.cards for idx in card.nodes}
    excluded = omitted - represented - set(before.result.hot.pruned_nodes)
    assert excluded
    assert all(before.cold.texts[idx] == before.graph.node(idx).text for idx in omitted)
    old_text, old_ranges = before.cold.render_text_view()
    idx = min(excluded)
    start, end = old_ranges[node_handle(idx)]
    read = _strip_line_numbers(_read(FileReadTool(cwd=str(tmp_path)), view, offset=start, limit=end - start + 1))
    assert before.graph.node(idx).text in read
    restored = type(before.cold).from_json(before.cold.to_json())
    assert restored.texts == before.cold.texts
    history += synth_session(turns=3, include_todo=False)
    after = project(history, region_end=len(history), params=params, view_path=view,
                    prev=before.state, cold=restored)
    new_text, new_ranges = after.cold.render_text_view()
    assert new_text.startswith(old_text)
    assert all(new_ranges[handle] == extent for handle, extent in old_ranges.items())
    assert all(after.cold.texts[idx] == before.graph.node(idx).text for idx in omitted)
