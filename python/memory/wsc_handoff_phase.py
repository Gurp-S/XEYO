"""Verify phase provenance and transition witnesses, without judging semantics."""
from synaptic.task_fact_sources import source_text
from synaptic.todo_snapshot import latest_todo_snapshot
from synaptic.textutil import tool_use_blocks, tool_result_blocks


class PhaseError(ValueError):
    def __init__(self, code, **facts):
        super().__init__(code)
        self.detail = {"error": code, **facts}


def observed_source(sources, index):
    if any(sources[index].get(key) for key in ('note_key', 'note_kind', 'note_retracted')):
        return False
    if source_text(sources[index]) is not None:
        return True
    receipts = list(tool_result_blocks(sources[index]))
    if len(receipts) != 1:
        return False
    receipt = receipts[0]
    uid = receipt.get("tool_use_id")
    if not isinstance(uid, (str, int)) or not uid:
        return False
    execution = receipt.get("execution")
    if isinstance(execution, dict) and (execution.get("complete") is False or execution.get("status") == "cancelled"):
        return False
    origins = [i for i, row in enumerate(sources) for use in tool_use_blocks(row) if use.get("id") == uid]
    replies = [i for i, row in enumerate(sources) for result in tool_result_blocks(row) if result.get("tool_use_id") == uid]
    return len(origins) == len(replies) == 1 and origins[0] < replies[0] == index


def validate(raw, sources, *, required=False):
    checkpoint = raw["checkpoint"]
    phase = checkpoint.get("phase_state")
    active = any(item.get("status") != "completed" for item in raw.get("todos", []))
    prior = latest_todo_snapshot(sources)
    if phase is None:
        if active and (required or prior.active_count and (prior.checkpoint or {}).get('phase_state') is not None):
            raise PhaseError("handoff_phase_state_required", field="checkpoint.phase_state")
        return
    indices = {}
    for index, row in enumerate(sources):
        uid = row.get("message_id") or row.get("id")
        if uid:
            indices.setdefault(str(uid), []).append(index)
    for record in phase["phases"]:
        for uid in record["source_message_ids"]:
            matches = indices.get(uid, [])
            if len(matches) != 1 or not observed_source(sources, matches[0]):
                raise PhaseError("handoff_phase_source_invalid", phase_id=record["id"], source_message_id=uid)
    before = (prior.checkpoint or {}).get("phase_state") if prior.active_count else None
    phase_changed = before is not None and before["current_phase_id"] != phase["current_phase_id"]
    # A phase ID alone cannot authorize changing the objective or reopening
    # a terminal task. These declarations need a source after the latest
    # committed state, including legacy checkpoints without phase metadata.
    objective_changed = prior.checkpoint is not None and (
        checkpoint.get("objective", "") != prior.checkpoint.get("objective", ""))
    reactivated = active and prior.observed and not prior.active_count
    goal_event = active and prior.observed and (reactivated or objective_changed)
    if phase_changed or goal_event:
        current = next(item for item in phase["phases"] if item["id"] == phase["current_phase_id"])
        witnesses = [indices[uid][0] for uid in current["source_message_ids"]]
        base = prior.source if goal_event else prior.checkpoint_source
        if not any(index > base and observed_source(sources, index) for index in witnesses):
            raise PhaseError("handoff_phase_transition_source_missing",
                             from_phase_id=before["current_phase_id"] if before is not None else None,
                             to_phase_id=phase["current_phase_id"], base_checkpoint_source=base,
                             objective_changed=bool(objective_changed), task_reactivated=bool(reactivated))
    from memory.wsc_handoff_applicability import validate as validate_applicability
    if active:
        validate_applicability(checkpoint, sources, prior, indices, observed_source)
