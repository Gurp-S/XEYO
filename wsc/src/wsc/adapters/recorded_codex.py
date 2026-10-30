"""Opt-in presentation of stored model records and unchanged source observations."""
from .covered_codex import CoveredCodexCheckpointAdapter
from ..recorded_understandings import recorded_items


class RecordedCodexCheckpointAdapter(CoveredCodexCheckpointAdapter):
    @staticmethod
    def capabilities():
        return {**CoveredCodexCheckpointAdapter.capabilities(), "adapter": "codex_recorded_checkpoint_v1"}

    def render(self, body, sources, cut, locators, *, source_index, understanding_index):
        items = super().render(body, sources, cut, locators,
                               source_index=source_index, understanding_index=understanding_index)
        index = sum(row["kind"] == "message" for row in (body or {}).get("sources", []))
        return recorded_items(items, (body or {}).get("understandings", []), working_state_index=index)
