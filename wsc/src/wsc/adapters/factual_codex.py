"""Optional factual presentation; exact evidence and installation proofs stay cold."""
from copy import deepcopy
import json

from .codex import CodexCheckpointAdapter
from ..contracts import encode


class FactualCodexCheckpointAdapter(CodexCheckpointAdapter):
    def __init__(self, *, execution_facts=None):
        self.execution_facts = deepcopy(execution_facts)

    @staticmethod
    def capabilities():
        return {**CodexCheckpointAdapter.capabilities(), "adapter": "codex_factual_checkpoint_v1"}

    def render(self, body, sources, cut, locators, *, source_index, understanding_index):
        items = super().render(body, sources, cut, locators,
                               source_index=source_index, understanding_index=understanding_index)
        index = sum(row["kind"] == "message" for row in (body or {}).get("sources", []))
        facts = json.loads(items[index]["content"][0]["text"])
        parts = ["Working state"]
        if self.execution_facts:
            parts.extend(["Current execution facts", encode(self.execution_facts)])

        def source_lines(locations):
            return [f"Source observed {loc.get('observed_at')}: {loc['path']}" for loc in locations]

        for record in facts["understandings"]:
            parts.extend([f"Understanding: {record['kind']} ({record['ref']})", record["text"]])
            if record["scope"] is not None:
                parts.append("Scope: " + encode(record["scope"]))
            parts.extend(source_lines(record["sources"]))
        for clue in facts["clues"]:
            parts.extend(["Recorded clue", clue["text"], *source_lines(clue["sources"])])
        for observation in facts["historical_excerpts"]:
            parts.extend([f"Historical {observation['kind']} ({observation['source_id']})",
                          f"Observed: {observation['observed_at']}",
                          observation["text"] if observation["text"] is not None else "Public text unavailable",
                          "Source: " + observation["source"].get("readable_path", observation["source"]["file_path"])])
        for observation in facts.get("observations", []):
            source = observation["source"]
            parts.append("Observation: " + observation["key"])
            if observation["historical_locator"] is not None:
                parts.append("Historical location: " + observation["historical_locator"])
            parts.extend([f"Observed: {source['observed_at']}", observation["text"],
                          "Exact archived excerpt: " + source["file_path"]])
            if "current_reference" in observation:
                # Byte identity remains in package.current_reference_bindings.
                omit = {"resource_sha256", "expected_resource_sha256", "matched_normalized_text_sha256",
                        "bytes_read", "historical_observation_retimed"}
                current = {k: v for k, v in observation["current_reference"].items() if k not in omit}
                parts.append("Observed current reference: " + encode(current))
        parts.extend(["Full source index: " + facts["archive"]["sources"],
                      "Full understanding index: " + facts["archive"]["understandings"]])
        items[index]["content"][0]["text"] = "\n\n".join(parts)
        return items
