"""Durable outbox: exporting bytes is not a host installation receipt."""
from dataclasses import asdict
from pathlib import Path
import json
from uuid import uuid4
from hashlib import file_digest
from contextlib import nullcontext
from functools import partial

from .contracts import HostReceipt, HostRejection, Snapshot, digest, encode, require
from .snapshots import validate_snapshot, view_record
from . import events, evidence, excerpts, references, understanding
from .store import getmeta, setmeta
from .settlement import check_committed_binding, record_lost_reply, record_unsettled_receipt


def operation(db, key):
    row = db.execute("SELECT * FROM operations WHERE id=?", (key,)).fetchone()
    require(row is not None, "operation_missing")
    value = json.loads(row["data"])
    if "package" in value:
        package = value["package"]
        unsigned = {k: v for k, v in package.items() if k != "package_digest"}
        require(digest(unsigned) == package["package_digest"], "package_integrity_mismatch")
    return {**value, "state": row["state"], "receipt": json.loads(row["receipt"]) if row["receipt"] else None}


def check_binding(db, core, data):
    require(getmeta(db, "mode") == "active", "component_not_active")
    binding = data["binding"]
    require(binding["generation"] == getmeta(db, "generation"), "stale_generation")
    require(binding["control_epoch"] == getmeta(db, "control_epoch"), "control_changed")
    require(binding["understanding_epoch"] == getmeta(db, "understanding_epoch"), "understanding_changed")
    if not data["detach"]:
        validate_snapshot(db, core.store, Snapshot(**binding, events=(), understandings=()),indexed=core.indexed_queries)
    else:
        require(digest(events.rows(db, binding["cut"])) == binding["source_digest"], "source_binding_changed")


def stage(core, view_id, *, directory, adapter, detach, archive_directory=None):
    require(not detach or archive_directory is None, "detach_requires_self_contained_archive")
    key = uuid4().hex
    with core.store.transaction() as db:
        require(getmeta(db, "mode") == "active", "component_not_active")
        require(not db.execute("SELECT 1 FROM operations WHERE state IN ('preparing','ready','installing','unknown','recovery_required')").fetchone(),
                "publication_pending")
        source = events.rows(db)
        view = view_record(db, view_id) if view_id else None
        if not detach:
            require(view is not None, "view_unavailable")
            binding = view["binding"]
            validate_snapshot(db, core.store, Snapshot(**binding, events=(), understandings=()),
                              indexed=core.indexed_queries, all_rows=source)
        else:
            # Switching is only possible after all observed calls have results.
            pending = {r["call_id"] for r in source if r["kind"] == "call"} - {
                r["call_id"] for r in source if r["kind"] == "result"}
            require(not pending, "pending_tool_results")
            cut = getmeta(db, "cursor")
            binding = {"session_id": core.store.session_id, "workspace": core.store.workspace,
                       "generation": getmeta(db, "generation"), "control_epoch": getmeta(db, "control_epoch"),
                       "understanding_epoch": getmeta(db, "understanding_epoch"),
                       "cut": cut, "source_digest": digest(source[:cut])}
        validate_adapter = getattr(adapter, "validate_binding", None)
        if validate_adapter is not None:
            validate_adapter(dict(binding))
        data = {"binding": binding, "detach": detach, "view_id": view_id}
        db.execute("INSERT INTO operations(id,kind,state,data) VALUES (?,?,?,?)",
                   (key, "detach" if detach else "publish", "preparing", encode(data)))
        records = understanding.all_records(db)
    try:
        io=core.resource_io
        default_writer = (evidence.write_once if core.evidence_sync
                          else partial(evidence.write_once, sync=False))
        with io.publication_writer() if io is not None else nullcontext(default_writer) as writer:
            root = Path(directory).resolve() / key
            if archive_directory is None:
                locators = evidence.export_sources(core.store, core.access, [r["id"] for r in source], root / "sources",write_object=writer)
            else:
                from .content_archive import export_sources
                locators = export_sources(core.store, core.access, [r["id"] for r in source], archive_directory,write_object=writer if io is not None else None)
            index = root / "sources.json"
            root.mkdir(parents=True, exist_ok=True)
            memories = root / "understandings.json"
            if core.bounded_catalog:
                from .publication_memory import write_catalog
                source_checksum=write_catalog(writer,index,locators)
                understanding_checksum=write_catalog(writer,memories,records)
                # Complete cold history is persisted; release its decoded duplicate.
                records=None
            else:
                writer(index, encode(locators).encode("utf-8"))
                writer(memories, encode(records).encode("utf-8"))
                source_checksum=digest(locators);understanding_checksum=digest(records)
            body = view["body"] if view else None
            if body and body.get('source_projection'):
                require(adapter.capabilities().get('source_projection')==body['source_projection'],
                        'adapter_source_projection_unsupported')
                from .source_reference_view import hydrate
                body=hydrate(body,source)
            excerpt_locators = excerpts.export(core.store, core.access,
                (body or {}).get("excerpts", []), root / "excerpts",write_object=writer)
            if excerpt_locators:
                body = {**body, "excerpt_locators": excerpt_locators}
            items = adapter.render(body, source, binding["cut"], locators,
                                   source_index=str(index), understanding_index=str(memories))
            through=len(source)
            if core.bounded_catalog:source=None
            package = {"format": "wsc.checkpoint/1", "operation_id": key, "action": "detach" if detach else "publish",
                       "binding": binding, "through": through,
                       "next_generation": binding["generation"] + (0 if detach else 1),
                       "adapter": adapter.capabilities(), "items": items,
                       "source_index": str(index), "source_index_sha256": source_checksum,
                       "understanding_index": str(memories), "understanding_index_sha256": understanding_checksum,
                       "evidence": locators, "semantic_status": "unverified"}
            if excerpt_locators:
                package["excerpt_evidence"] = excerpt_locators
                package["current_reference_bindings"] = [e["current_reference"] for e in body["excerpts"]
                                                         if "current_reference" in e]
            package["package_digest"] = digest(package)
            writer(root / "checkpoint.json", encode(package).encode("utf-8"))
        with core.store.transaction() as db:
            require(operation(db, key)["state"] == "preparing", "publication_cancelled")
            check_binding(db, core, data)
            data["package"] = package
            db.execute("UPDATE operations SET state='ready',data=? WHERE id=?", (encode(data), key))
        return key
    except BaseException:
        with core.store.transaction() as db:
            db.execute("UPDATE operations SET state='failed' WHERE id=? AND state='preparing'", (key,))
        raise


def check_evidence(core, package):
    io=core.resource_io
    def digest_file(path):
        if io is not None:
            return io.digest(path)
        with open(path, "rb") as stream:
            return file_digest(stream, "sha256").hexdigest()
    excerpts.check(core.store, core.access, package.get("excerpt_evidence", {}),resource_io=io)
    references.check(package.get("current_reference_bindings", []),resource_io=io)
    projection=package.get('adapter',{}).get('projection_evidence')
    if projection:
        require(digest_file(projection['file_path'])==projection['sha256'],
                'exported_projection_index_changed')
    for key, locator in package["evidence"].items():
        evidence.authorize(core.store, core.access, key, "export")
        path = Path(locator["file_path"])
        require(path.is_file(), "exported_source_unavailable")
        require(digest_file(path) == locator["sha256"], "exported_source_changed")
        if "readable_path" in locator:
            require(digest_file(locator["readable_path"]) == locator["readable_sha256"],
                    "exported_readable_changed")
    for name in ("source_index", "understanding_index"):
        actual=digest_file(package[name]) if io is not None else digest(json.loads(Path(package[name]).read_text(encoding="utf-8")))
        require(actual == package[name + "_sha256"],
                "exported_index_changed")


def confirm(core, key, receipt):
    require(isinstance(receipt, (HostReceipt, HostRejection)), "host_receipt_invalid")
    with core.store.transaction() as db:
        data = operation(db, key)
        if data["state"] in {"confirmed", "rejected"}:
            require(data["receipt"] == asdict(receipt), "host_receipt_conflict")
            return data["receipt"]
        require(data["state"] in {"installing", "unknown", "recovery_required"}, "installation_not_started")
        p = data["package"]
        if isinstance(receipt, HostRejection):
            require(receipt.operation_id == key and receipt.package_digest == p["package_digest"]
                    and receipt.session_id == core.store.session_id and receipt.workspace == core.store.workspace
                    and isinstance(receipt.reason, str) and bool(receipt.reason.strip())
                    and isinstance(receipt.receiver, str) and bool(receipt.receiver.strip()),
                    "host_receipt_binding_mismatch")
            db.execute("UPDATE operations SET state='rejected',receipt=? WHERE id=?",
                       (encode(asdict(receipt)), key))
            return asdict(receipt)
        require(receipt.operation_id == key and receipt.package_digest == p["package_digest"]
                and receipt.session_id == core.store.session_id and receipt.workspace == core.store.workspace
                and receipt.generation == p["next_generation"]
                and receipt.control_epoch == p["binding"]["control_epoch"]
                and receipt.installed_through == p["through"]
                and isinstance(receipt.receiver, str) and bool(receipt.receiver.strip())
                and receipt.evidence_accessible is True,
                "host_receipt_binding_mismatch")
        check_committed_binding(db, core.store, data,indexed=core.indexed_queries)
        if data["detach"]:
            setmeta(db, "mode", "detached")
        else:
            setmeta(db, "head", data["view_id"])
            setmeta(db, "cursor", p["binding"]["cut"])
            setmeta(db, "generation", p["next_generation"])
            db.execute("UPDATE views SET state='installed' WHERE id=?", (data["view_id"],))
        encoded = encode(asdict(receipt))
        db.execute("UPDATE operations SET state='confirmed',receipt=? WHERE id=?", (encoded, key))
        return asdict(receipt)


def install(core, key, host):
    if core.resource_io is None:
        return _install(core,key,host)
    with core.store.connect() as db:
        data=operation(db,key)
    if data['state'] in {'confirmed','rejected'}:return data['receipt']
    require(data['state']=='ready','installation_outcome_requires_reconciliation')
    with core.resource_io.lease(data['package']):
        return _install(core,key,host)


def _install(core, key, host):
    with core.store.transaction() as db:
        data = operation(db, key)
        if data["state"] in {"confirmed", "rejected"}:
            return data["receipt"]
        require(data["state"] == "ready", "installation_outcome_requires_reconciliation")
        check_binding(db, core, data)
        check_evidence(core, data["package"])
        db.execute("UPDATE operations SET state='installing' WHERE id=?", (key,))
    try:
        receipt = host.install(data["package"])
    except BaseException:
        with core.store.transaction() as db:
            record_lost_reply(db, key)
        raise
    try:
        return confirm(core, key, receipt)
    except BaseException:
        with core.store.transaction() as db:
            record_unsettled_receipt(db, key, receipt)
        raise


def reconcile(core, key, host):
    with core.store.connect() as db:
        data = operation(db, key)
    if data["state"] in {"confirmed", "rejected"}:
        return data["receipt"]
    require(data["state"] in {"installing", "unknown", "recovery_required"}, "installation_not_started")
    receipt = host.lookup(key)
    require(receipt is not None, "host_outcome_unknown")
    return confirm(core, key, receipt)


def discard(core, key):
    """Only a definitely unsubmitted package can be abandoned locally."""
    with core.store.transaction() as db:
        data = operation(db, key)
        require(data["state"] in {"preparing", "ready", "failed", "cancelled", "rejected"}, "publication_outcome_unknown")
        db.execute("UPDATE operations SET state='cancelled' WHERE id=?", (key,))
