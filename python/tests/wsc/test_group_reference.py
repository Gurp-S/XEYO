"""Published card references survive growth, regrouping and legacy cold data."""
from dataclasses import replace

import pytest

from synaptic.coldstore import ColdStore, branch_handle
from synaptic.group_reference import group_reference
from synaptic.project import project
from synaptic.prune import cards_handle
from synaptic.types import PruneCard, WscParams
from tests.wsc._fixtures import synth_session


def test_same_root_with_changed_members_cannot_replace_an_old_reference():
    old = PruneCard("B1", "Attempt complete", nodes=(1, 2))
    new = replace(old, nodes=(1, 2, 3))
    store = ColdStore()
    store.put_nodes([(idx, f"record-{idx}", {}) for idx in (1, 2, 3)])
    store.bind(old.handle, old.nodes)
    original = store.expand(old.handle)
    store.bind(new.handle, new.nodes)
    assert old.handle != new.handle
    assert store.expand(old.handle) == original == ("record-1", "record-2")
    assert store.expand(new.handle) == ("record-1", "record-2", "record-3")


def test_card_group_identity_uses_members_and_preserves_their_order():
    first = PruneCard("B1", "Done", nodes=(1, 3))
    second = PruneCard("B2", "Done", nodes=(5, 8))
    assert cards_handle([first, second]) == group_reference((1, 3, 5, 8))
    assert cards_handle([first]) == first.handle
    assert cards_handle([first, second]) != cards_handle([second, first])
    assert first.handle != replace(first, nodes=(3, 1)).handle


@pytest.mark.parametrize("style", ["read", "expand"])
def test_previous_cold_references_and_ranges_survive_growth(tmp_path, style):
    history = synth_session(turns=12, user_every=3)
    end = len(history) // 2
    params = replace(WscParams(), main_segment_budget_tokens=100, max_cards=1, handle_style=style)
    view = tmp_path / ".xeyo_offload" / "wsc" / "cold.txt"
    first = project(history[:end], region_end=end, params=params, view_path=view)
    assert first.result.hot.cards
    old = {handle: first.cold.expand(handle) for handle in first.cold.handles}
    old_view, old_ranges = first.cold.render_text_view()
    # A published legacy alias remains authoritative after loading old data.
    card = first.result.hot.cards[0]
    legacy = branch_handle(card.card_id)
    first.cold.bind(legacy, card.nodes)
    old[legacy] = first.cold.expand(legacy)
    cold = ColdStore.from_json(first.cold.to_json())
    second = project(history, region_end=len(history), params=params, view_path=view, prev=first.state, cold=cold)
    assert second.text.startswith(first.text)
    assert all(second.cold.expand(handle) == value for handle, value in old.items())
    new_view, new_ranges = second.cold.render_text_view()
    assert new_view.startswith(old_view)
    assert all(new_ranges[handle] == extent for handle, extent in old_ranges.items())


def test_large_membership_uses_a_bounded_reference_without_losing_members():
    nodes = tuple(range(100))
    reference = group_reference(nodes)
    assert len(reference) <= 77
    assert reference != group_reference(nodes[:-1] + (101,))
    store = ColdStore()
    store.put_nodes([(idx, f"record-{idx}", {}) for idx in nodes])
    store.bind(reference, nodes)
    loaded = ColdStore.from_json(store.to_json())
    assert loaded.expand(reference) == tuple(f"record-{idx}" for idx in nodes)
