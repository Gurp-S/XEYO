"""Opt-in generation from a previous model-selected view and its new source tail.

The full source remains the compiler's authority. The previous view is historical
model selection, not evidence of installation, completion or current validity.
"""
from pathlib import Path
from hashlib import sha256

from . import evidence, understanding
from .contracts import Generated, Usage, WSCError, digest, encode, require
from .projection import public_material
from .quote_selection import SelectionDraft
from .selection_facts import describe
from .snapshots import validate_snapshot, view_record
from .span_selection import compile_spans, span_material
from .view_budget import mandatory_sources


class FrontierSpanSelectionGenerator:
    def __init__(self, core, snapshot, previous_view, generate_draft, *, archive_directory,
                 mode="frontier", max_chars=1024, max_material_bytes=524288, boundary_policy="fixed"):
        require(mode in {"full", "frontier"}, "frontier_mode_invalid")
        self.core, self.snapshot, self.generate_draft = core, snapshot, generate_draft
        self.archive_directory = Path(archive_directory).resolve()
        self.mode, self.max_chars, self.max_material_bytes = mode, max_chars, max_material_bytes
        self.boundary_policy = boundary_policy
        with core.store.connect() as db:
            prefix = validate_snapshot(db, core.store, snapshot,indexed=core.indexed_queries)
            records = understanding.all_records(db)
            require(list(snapshot.events) == prefix and list(snapshot.understandings) == records,
                    "frontier_snapshot_content_changed")
            self.previous = view_record(db, previous_view)
        binding = self.previous["binding"]
        require(binding["session_id"] == snapshot.session_id and binding["workspace"] == snapshot.workspace,
                "frontier_previous_identity_changed")
        cut = binding["cut"]
        require(type(cut) is int and 0 < cut <= snapshot.cut
                and digest(snapshot.events[:cut]) == binding["source_digest"], "frontier_source_prefix_changed")
        kept = {r["id"] for r in self.previous["body"]["sources"]}
        require(kept <= {r["id"] for r in snapshot.events[:cut]}, "frontier_previous_source_missing")
        require({r["id"] for r in mandatory_sources(snapshot.events[:cut])} <= kept,
                "frontier_previous_control_missing")
        # A source selected as an exact excerpt is also part of the previous
        # working set, even when its full record was not selected. This version
        # exposes that source in full; it does not silently drop the observation.
        kept.update(e["source_id"] for e in self.previous["body"].get("excerpts", []))
        self.kept = kept
        self.full_material = None
        self.preparation = None

    def offer(self, material):
        expected = {"session_id": self.snapshot.session_id, "source_boundary": self.snapshot.cut,
                    **public_material(self.snapshot.events, self.snapshot.understandings)}
        if "selection_facts" in material:
            facts = material["selection_facts"]
            limit = facts.get("serialized_view_limit_bytes") if isinstance(facts, dict) else None
            require(type(limit) is int and limit > 0, "frontier_selection_facts_invalid")
            expected["selection_facts"] = describe(self.snapshot.events, limit)
        require(material == expected, "frontier_generation_material_changed")
        with self.core.store.connect() as db:
            validate_snapshot(db, self.core.store, self.snapshot,indexed=self.core.indexed_queries)
        full = span_material(material, max_chars=self.max_chars, boundary_policy=self.boundary_policy)
        root = self.archive_directory
        root.mkdir(parents=True, exist_ok=True)
        # The ordinary source export enforces the same live per-source export
        # authorization as publication, including opaque records kept cold.
        locators = evidence.export_sources(self.core.store, self.core.access,
            [r["id"] for r in self.snapshot.events], root / "sources")
        evidence.write_once(root / "sources.json", encode(locators).encode("utf-8"))
        catalog = []
        for event in full["events"]:
            path = root / (event["id"] + ".spans.jsonl")
            chunks = [{"source": event["id"], "observed_at": event["observed_at"],
                       "call_id": event["call_id"], **span} for span in event["spans"]]
            raw = "".join(encode(chunk) + "\n" for chunk in chunks).encode("utf-8")
            evidence.write_once(path, raw)
            catalog.append({**{k: v for k, v in event.items() if k != "spans"},
                            "span_file": str(path), "span_file_sha256": sha256(raw).hexdigest()})
        evidence.write_once(root / "catalog.jsonl", "".join(encode(e) + "\n" for e in catalog).encode("utf-8"))
        cut = self.previous["binding"]["cut"]
        aliases = {f"s{e['seq']}" for e in self.snapshot.events if e["id"] in self.kept}
        selected = [e for e in full["events"] if e["seq"] > cut or e["id"] in aliases]
        basis = {"previous_view": self.previous["id"], "previous_source_boundary": cut,
                 "previous_source_digest": self.previous["binding"]["source_digest"],
                 "previous_understanding_refs": [r["ref"] for r in self.previous["body"]["understandings"]],
                 "status": "historical_model_selection; installation_and_current_semantic_applicability_not_asserted"}
        common = {"generation_basis": basis,
                  "archive": {"catalog": str(root / "catalog.jsonl"),
                              "catalog_sha256": sha256((root / "catalog.jsonl").read_bytes()).hexdigest(),
                              "source_index": str(root / "sources.json"), "source_boundary": self.snapshot.cut},
                  "source_catalog": catalog}
        self.full_material = {**full, **common}
        offered = {**self.full_material, "events": full["events"] if self.mode == "full" else selected}
        require(len(encode(offered).encode("utf-8")) <= self.max_material_bytes,
                "frontier_material_byte_budget_exhausted")
        self.preparation = {"mode": self.mode, "previous_cut": cut,
            "full_public_events": len(full["events"]), "inline_public_events": len(offered["events"]),
            "full_material_bytes": len(encode(self.full_material).encode("utf-8")),
            "offered_material_bytes": len(encode(offered).encode("utf-8")),
            "source_count": len(locators), "cold_catalog_sha256": common["archive"]["catalog_sha256"]}
        return offered

    def __call__(self, material):
        try:
            offered = self.offer(material)
        except Exception as exc:
            exc.usage = Usage(0, 0, 0)
            raise
        result = self.generate_draft(offered)
        require(isinstance(result, SelectionDraft) and isinstance(result.usage, Usage),
                "frontier_generation_result_invalid")
        try:
            selection = compile_spans(material, result.selection, max_chars=self.max_chars,
                                      boundary_policy=self.boundary_policy)
        except WSCError as exc:
            exc.usage = result.usage
            raise
        return Generated(selection, result.usage)
