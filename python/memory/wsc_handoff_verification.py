"""Verification bindings persist for the lifetime of an active task phase.

An additional receipt does not prove replacement of any prior verification.
Phase/terminal transitions are validated by their existing contracts.
"""
from synaptic.todo_snapshot import latest_todo_snapshot


class VerificationError(ValueError):
    def __init__(self, code, **facts):
        super().__init__(code)
        self.detail = {"error": code, **facts}


def validate(raw, sources):
    prior = latest_todo_snapshot(sources)
    if not prior.observed or not prior.active_count or prior.checkpoint is None:
        return
    checkpoint = raw['checkpoint']
    before_phase = prior.checkpoint.get('phase_state')
    after_phase = checkpoint.get('phase_state')
    if before_phase is None or after_phase is None:
        return  # Legacy states do not declare a task phase lifecycle.
    if not any(item.get('status') != 'completed' for item in raw.get('todos', [])):
        return  # The existing progress contract validates terminal transitions.
    if before_phase['current_phase_id'] != after_phase['current_phase_id']:
        return  # The existing phase contract validates phase transitions first.
    old = set(prior.checkpoint.get('verification_call_ids', []))
    new = set(checkpoint.get('verification_call_ids', []))
    missing = old - new
    if not missing:
        return
    base = sources[prior.checkpoint_source]
    raise VerificationError('handoff_active_phase_verification_bindings_omitted',
        base_checkpoint_message_id=base.get('message_id') or base.get('id'),
        active_phase_id=before_phase['current_phase_id'],
        prior_verification_call_ids=sorted(old), omitted_verification_call_ids=sorted(missing),
        declared_verification_call_ids=sorted(new))
