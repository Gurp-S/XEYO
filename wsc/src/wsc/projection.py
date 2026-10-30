"""Pure public-material and checkpoint-binding projections; no source authority."""


def snapshot_binding(snapshot, *, understanding_epoch):
    # Snapshot's public history fields remain available to callers. A binding
    # contains only identity/version scalars and never needs to copy that history.
    return {"session_id": snapshot.session_id, "workspace": snapshot.workspace,
            "generation": snapshot.generation, "control_epoch": snapshot.control_epoch,
            "understanding_epoch": understanding_epoch, "cut": snapshot.cut,
            "source_digest": snapshot.source_digest}


def public_material(prefix, records):
    source_ids = {row["id"] for row in prefix}
    return {"events": [{key: row[key] for key in
                       ("id", "seq", "kind", "role", "call_id", "text", "observed_at")}
                      for row in prefix if row["kind"] != "opaque"],
            "understandings": [record for record in records if set(record["sources"]) <= source_ids]}
