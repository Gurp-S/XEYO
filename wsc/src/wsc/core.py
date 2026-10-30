"""Independent WSC service. No task execution, implicit model calls or globals."""
from __future__ import annotations

from dataclasses import replace
import json
from time import monotonic
from uuid import uuid4

from . import accounting, events, evidence, excerpts, understanding
from .contracts import (AccessCheck, Event, Generated, GeneratorPort, Limits, Selection,
                        Snapshot, Understanding, Usage, digest, encode, require)
from .store import Store, getmeta, getmetas
from .snapshots import semantic_writes_allowed, validate_snapshot
from .projection import public_material, snapshot_binding
from .material_v2 import MaterialView
from .view_budget import admit_generation, mandatory_sources


class WSC:
    def __init__(self, store: Store, *, access: AccessCheck, resource_io=None,query_policy=None,publication_policy=None,
                 evidence_sync: bool = True):
        self.store, self.access = store, access
        self.resource_io = resource_io
        require(query_policy in (None,'prefix_index_v1'),'query_policy_unsupported')
        self.indexed_queries=query_policy=='prefix_index_v1'
        require(publication_policy in (None,'bounded_catalog_v1'),'publication_policy_unsupported')
        self.bounded_catalog=publication_policy=='bounded_catalog_v1'
        require(type(evidence_sync) is bool,'evidence_sync_policy_invalid')
        self.evidence_sync=evidence_sync

    def ingest(self, batch: list[Event]) -> list[str]:
        with self.store.transaction() as db:
            return events.ingest(db, batch)

    def presented(self, request_id: str, source_ids: tuple[str, ...], *, receiver: str) -> None:
        with self.store.transaction() as db:
            require(getmeta(db, "mode") != "detached", "component_detached")
            events.presented(db, request_id, source_ids, receiver)

    def presented_many(self, receipts) -> None:
        """Record several presentation receipts in one transaction.

        Each receipt is (request_id, source_ids, receiver) and carries exactly the
        same meaning as a separate presented() call.
        """
        with self.store.transaction() as db:
            require(getmeta(db, "mode") != "detached", "component_detached")
            for request_id, source_ids, receiver in receipts:
                events.presented(db, request_id, source_ids, receiver)

    def remember(self, record: Understanding, *, producer: str) -> dict:
        with self.store.transaction() as db:
            semantic_writes_allowed(db)
            known=None
            if self.indexed_queries:
                from .scoped_queries import existing_sources
                known=existing_sources(db,record.sources)
            return understanding.write(db, record, producer=producer,allowed_sources=known)

    def capture(self, *, cut: int | None = None) -> Snapshot:
        with self.store.transaction() as db:
            semantic_writes_allowed(db)
            if cut is None:
                cut = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            prefix = events.safe_boundary(db, cut,indexed=self.indexed_queries)
            return Snapshot(self.store.session_id, self.store.workspace,
                            getmeta(db, "generation"), getmeta(db, "control_epoch"),
                            getmeta(db, "understanding_epoch"), cut, digest(prefix),
                            tuple(prefix), tuple(understanding.all_records(db)))

    def material(self, snapshot: Snapshot) -> dict:
        return self.material_view(snapshot).public()

    def material_view(self, snapshot: Snapshot):
        """Opt-in lazy projection: rows stay by reference until a page is asked for."""
        with self.store.transaction() as db:
            prefix = validate_snapshot(db, self.store, snapshot,indexed=self.indexed_queries)
            for row in prefix:
                evidence.authorize(self.store, self.access, row["id"])
            return MaterialView(prefix, understanding.all_records(db),
                                session_id=snapshot.session_id, cut=snapshot.cut)

    def generate(self, snapshot: Snapshot, generator: GeneratorPort, *, producer: str,
                 limits: Limits = Limits(), include_selection_facts: bool = False) -> str:
        view = self.material_view(snapshot)
        require(view.text_bytes() <= limits.max_material_bytes,
                "generation_material_byte_budget_exhausted")
        require(view.byte_size() <= limits.max_material_bytes,
                "generation_material_byte_budget_exhausted")
        material = view.public()
        phase = "generation:" + digest({"source": snapshot.source_digest,
                                        "generation": snapshot.generation})
        attempt = uuid4().hex
        with self.store.transaction() as db:
            semantic_writes_allowed(db)
            prefix = validate_snapshot(db, self.store, snapshot,indexed=self.indexed_queries)
            admit_generation(prefix, limits.max_view_bytes)
            if include_selection_facts:
                from .selection_facts import describe
                material = {**material, "selection_facts": describe(prefix, limits.max_view_bytes)}
                require(len(encode(material).encode("utf-8")) <= limits.max_material_bytes,
                        "generation_material_byte_budget_exhausted")
            count = db.execute("SELECT COUNT(*) FROM usage WHERE phase=?", (phase,)).fetchone()[0]
            require(count < limits.max_generation_calls, "generation_budget_exhausted")
            accounting.begin(db, attempt, phase)
        start = monotonic()
        try:
            result = generator(material)
            require(isinstance(result, Generated), "generation_result_invalid")
            require(isinstance(result.selection, Selection) and isinstance(result.usage, Usage),
                    "generation_result_invalid")
        except BaseException as exc:
            usage = getattr(exc, "usage", Usage())
            if not isinstance(usage, Usage):
                usage = Usage()
            with self.store.transaction() as db:
                accounting.finish(db, attempt, replace(usage, elapsed_ms=(monotonic()-start)*1000),
                                  status="failed")
            raise
        with self.store.transaction() as db:
            accounting.finish(db, attempt, replace(result.usage, elapsed_ms=(monotonic()-start)*1000))
        return self.prepare(snapshot, result.selection, producer=producer, limits=limits)

    def prepare(self, snapshot: Snapshot, selection: Selection, *, producer: str,
                limits: Limits = Limits(), source_projection: str | None = None) -> str:
        """No implicit generation. Supplied semantic content has explicit provenance."""
        with self.store.transaction() as db:
            semantic_writes_allowed(db)
            prefix = validate_snapshot(db, self.store, snapshot,indexed=self.indexed_queries)
            known = {r["id"]: r for r in prefix}
            selected = set(selection.source_ids)
            require(selected <= known.keys(), "selected_source_missing")
            selected.update(r["id"] for r in mandatory_sources(prefix))
            refs = list(dict.fromkeys(selection.understanding_refs))
            for value in selection.new_understandings:
                record = understanding.write(db, value, producer=producer, allowed_sources=known)
                refs.append(record["ref"])
            records = [understanding.resolve(db, ref) for ref in dict.fromkeys(refs)]
            require(all(set(r["sources"]) <= known.keys() for r in records), "understanding_outside_snapshot")
            clues = []
            for clue in selection.clues:
                require(isinstance(clue, dict) and set(clue) == {"text", "sources"}, "clue_shape_invalid")
                require(isinstance(clue["text"], str) and bool(clue["text"].strip()), "clue_text_empty")
                require(isinstance(clue["sources"], (list, tuple)) and bool(clue["sources"])
                        and set(clue["sources"]) <= known.keys(), "clue_source_missing")
                clues.append(json.loads(encode(clue)))
            require(all(known[key]["kind"] != "opaque" for key in selected), "opaque_hot_selection_unavailable")
            for key in selected | {key for r in records for key in r["sources"]} | {
                    key for c in clues for key in c["sources"]} | {
                    item.source_id for item in selection.excerpts if isinstance(item, excerpts.Excerpt)}:
                evidence.authorize(self.store, self.access, key)
            body = {"sources": [r for r in prefix if r["id"] in selected],
                    "understandings": records, "clues": clues}
            if selection.excerpts:
                body["excerpts"] = excerpts.resolve(selection.excerpts, known,resource_io=self.resource_io)
            if source_projection is not None:
                from .source_reference_view import project
                body['sources']=project(body['sources'],source_projection)
                body['source_projection']=source_projection
            require(len(encode(body).encode("utf-8")) <= limits.max_view_bytes, "view_byte_budget_exhausted")
            binding = snapshot_binding(snapshot, understanding_epoch=getmeta(db, "understanding_epoch"))
            key = uuid4().hex
            view = {"id": key, "binding": binding, "body": body, "digest": digest(body),
                    "producer": producer, "semantic_status": "unverified"}
            db.execute("INSERT INTO views VALUES (?,?,?)", (key, "prepared", encode(view)))
            return key

    def read(self, source_id: str, *, offset=0, limit=None) -> dict:
        return evidence.read(self.store, self.access, source_id, offset=offset, limit=limit)

    def stage(self, view_id: str, *, directory, adapter, archive_directory=None) -> str:
        from .publication import stage
        return stage(self, view_id, directory=directory, adapter=adapter, detach=False,
                     archive_directory=archive_directory)

    def stage_detach(self, *, directory, adapter) -> str:
        from .publication import stage
        with self.store.connect() as db:
            head = getmeta(db, "head")
        return stage(self, head, directory=directory, adapter=adapter, detach=True)

    def install(self, operation_id: str, host) -> dict:
        from .publication import install
        return install(self, operation_id, host)

    def reconcile(self, operation_id: str, host) -> dict:
        from .publication import reconcile
        return reconcile(self, operation_id, host)

    def discard(self, operation_id: str) -> None:
        from .publication import discard
        discard(self, operation_id)

    def begin_usage(self, attempt_id: str, *, phase: str) -> None:
        """Host calls, evidence expansion and failed attempts can share this ledger."""
        with self.store.transaction() as db:
            accounting.begin(db, attempt_id, phase)

    def finish_usage(self, attempt_id: str, usage: Usage, *, status="completed") -> None:
        with self.store.transaction() as db:
            accounting.finish(db, attempt_id, usage, status=status)

    def package(self, operation_id: str) -> dict:
        from .publication import operation
        with self.store.connect() as db:
            return operation(db, operation_id)["package"]

    def status(self) -> dict:
        with self.store.connect() as db:
            return {**getmetas(db, ("binding", "mode", "generation", "cursor", "head")),
                    "source_count": db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                    "operations": [dict(r) for r in db.execute("SELECT id,kind,state FROM operations")],
                    "usage": accounting.summary(db)}

    def metrics(self) -> dict:
        """One call that reads every counter this store and process expose.

        ``usage`` totals are durable; ``io_bytes_read`` is the live counter of
        the configured :class:`ResourceIO`; ``operations`` counts persisted
        operations. Keeping the assembly here means a new counter is added once
        instead of being rediscovered by each caller.
        """
        with self.store.connect() as db:
            usage = accounting.summary(db)["totals"]
            operations = db.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
        io = self.resource_io
        return {"usage": usage,
                "io_bytes_read": int(getattr(io, "bytes_read", 0)) if io is not None else 0,
                "operations": operations}
