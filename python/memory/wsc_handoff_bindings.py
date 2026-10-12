"""Previously committed context may leave a handoff only by explicit disposition."""
from copy import deepcopy
from synaptic.todo_snapshot import latest_todo_snapshot
from synaptic.task_fact_sources import source_text


class BindingError(ValueError):
    def __init__(self, code, **facts):
        super().__init__(code)
        self.detail = {"error": code, **facts}


def basis(sources):
    snapshot = latest_todo_snapshot(sources)
    if not snapshot.observed or not snapshot.active_count or snapshot.checkpoint is None:
        return None
    index = snapshot.checkpoint_source
    if not 0 <= index < len(sources):
        return None
    identity = sources[index].get("message_id") or sources[index].get("id")
    bound = []
    aliases = {}
    for uid in snapshot.checkpoint["context_message_ids"]:
        if uid == "@latest_user":
            alias = uid
            eligible = [row for row in sources[:index] if row.get("role") in {"user", "human"}
                        and not any(row.get(key) for key in ("note_key", "note_kind", "note_retracted"))
                        and source_text(row) is not None]
            if eligible:
                uid = eligible[-1].get("message_id") or eligible[-1].get("id") or uid
                aliases[alias] = uid
        if uid not in bound:
            bound.append(uid)
    result = {"base_checkpoint_message_id": identity, "bound_context_message_ids": bound}
    if "phase_state" in snapshot.checkpoint:
        phase = deepcopy(snapshot.checkpoint["phase_state"])
        phase["active_context_message_ids"] = [aliases.get(uid, uid) for uid in phase["active_context_message_ids"]]
        for item in phase["phases"]:
            item["source_message_ids"] = [aliases.get(uid, uid) for uid in item["source_message_ids"]]
        result["phase_state"] = phase
    return result


def validate(raw, sources):
    prior = basis(sources)
    disposition = raw.get("context_disposition")
    if prior is None:
        if disposition is not None:
            raise BindingError("handoff_context_disposition_without_base")
        return
    # An explicit empty/completed checklist is a task-state barrier. It does
    # not carry an active objective that could silently discard its sources.
    active = any(item.get("status") != "completed" for item in raw.get("todos", []))
    old = set(prior["bound_context_message_ids"])
    new = set(raw["checkpoint"].get("context_message_ids", [])) if active else set()
    # A verified quote chain still carries its actual original source link.
    # Counting the ancestry avoids requiring obsolete intermediate receipt
    # IDs when the projected committed fact already links that same source.
    if active:
        from synaptic.task_fact_sources import resolve
        for field in ("decisions", "constraints"):
            for fact in raw["checkpoint"].get(field, []):
                if not isinstance(fact, dict):
                    continue
                ancestry = resolve(sources, fact["source_message_id"], field, fact["quote"])
                if ancestry is not None:
                    new.update(str(sources[i].get("message_id") or sources[i].get("id")) for i in ancestry)
    missing = old - new if active else set()
    if disposition is None:
        if missing:
            raise BindingError("handoff_bound_context_disposition_missing", **prior,
                               omitted_context_message_ids=sorted(missing))
        return
    if (not isinstance(disposition, dict)
            or set(disposition) != {"base_checkpoint_message_id", "retired_context_message_ids"}
            or not isinstance(disposition["base_checkpoint_message_id"], str)
            or not isinstance(disposition["retired_context_message_ids"], list)
            or any(not isinstance(uid, str) for uid in disposition["retired_context_message_ids"])):
        raise BindingError("handoff_context_disposition_invalid")
    base = prior["base_checkpoint_message_id"]
    if not base or disposition["base_checkpoint_message_id"] != base:
        raise BindingError("handoff_context_disposition_stale_base", **prior)
    retired = disposition["retired_context_message_ids"]
    if len(retired) != len(set(retired)) or set(retired) != missing:
        raise BindingError("handoff_context_disposition_mismatch", **prior,
                           omitted_context_message_ids=sorted(missing))
