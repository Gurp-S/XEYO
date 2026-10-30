"""Preserve an externally obtained native checkpoint and add explicit evidence.

The opaque item is never decoded. Its source prefix and position are bound by
the caller; native acceptance and semantic value are separate host evidence.
"""
from copy import deepcopy
from pathlib import Path

from .factual_codex import FactualCodexCheckpointAdapter
from ..contracts import digest, require


class NativeCarrierCheckpointAdapter(FactualCodexCheckpointAdapter):
    def __init__(self, carrier, *, source_count, source_digest, workspace):
        require(isinstance(carrier, dict) and carrier.get("type") == "compaction",
                "native_compaction_carrier_required")
        require(type(source_count) is int and source_count > 0, "native_carrier_source_count_invalid")
        require(isinstance(workspace, str) and Path(workspace).is_absolute(),
                "native_carrier_workspace_required")
        super().__init__()
        self.carrier = deepcopy(carrier)
        self.source_count, self.source_digest = source_count, source_digest
        self.workspace = str(Path(workspace).resolve())

    def validate_binding(self, binding):
        require(Path(binding["workspace"]).resolve() == Path(self.workspace),
                "native_carrier_workspace_mismatch")

    @staticmethod
    def capabilities():
        return {**FactualCodexCheckpointAdapter.capabilities(),
                "adapter": "codex_native_carrier_with_facts_v1",
                "opaque_prefix": "registered_native_compaction_preserved",
                "workspace_migration": "unsupported"}

    def render(self, body, sources, cut, locators, *, source_index, understanding_index):
        require(cut == self.source_count + 1 and len(sources) >= cut, "native_carrier_boundary_mismatch")
        require(digest([row["payload"] for row in sources[:self.source_count]]) == self.source_digest,
                "native_carrier_source_mismatch")
        row = sources[self.source_count]
        require(row["kind"] == "opaque" and row["payload"] == self.carrier, "native_carrier_identity_mismatch")
        require(all(r["kind"] == "message" and r["role"] in {"system", "developer", "user"}
                    for r in (body or {}).get("sources", [])), "native_carrier_control_prefix_required")
        items = super().render(body, sources, cut, locators,
                               source_index=source_index, understanding_index=understanding_index)
        items.insert(len((body or {}).get("sources", [])), deepcopy(self.carrier))
        return items
