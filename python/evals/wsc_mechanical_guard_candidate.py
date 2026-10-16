"""Eval-only phase identity precheck; no semantic truth or runtime registration.

The caller supplies identities from an already committed native checkpoint.
This module neither trusts candidate-owned registries nor registers new phases.
Original AD checks and partial salvage remain unchanged after the precheck.
"""
from copy import deepcopy
from dataclasses import dataclass

from evals.wsc_ad_candidate import commit_candidate


@dataclass(frozen=True)
class PhaseIdentitySnapshot:
    task_id: str
    checkpoint_id: int
    phase_ids: tuple[str, ...]

    @classmethod
    def from_checkpoint(cls, task_id, checkpoint_id, checkpoint):
        from synaptic.task_checkpoint import validate
        normalized = validate(checkpoint)
        phase = normalized.get('phase_state') or {}
        return cls(task_id, checkpoint_id,
                   tuple(record['id'] for record in phase.get('phases', [])))


def _outcome(state, errors, accepted):
    return {'state': state, 'errors': errors, 'accepted': accepted,
            'mechanical_status': 'INVALID' if not accepted else 'PARTIAL' if errors else 'VALID',
            'semantic_status': 'SEMANTIC_UNVERIFIED'}


def commit(previous, candidate, store, mode, *, phases, reference_policy='event'):
    """Return mechanical acceptance separately from unverified semantics.

    A phase failure preserves the whole old checkpoint. This narrow prototype
    does not certify EXECUTION/FILE_VERSION scopes or authenticate its caller.
    """
    errors = []
    if not isinstance(phases, PhaseIdentitySnapshot):
        errors.append('phase_snapshot_missing')
    else:
        if phases.task_id != previous['goal_id']:
            errors.append('phase_snapshot_task_mismatch')
        if type(phases.checkpoint_id) is not int or phases.checkpoint_id != previous['checkpoint_id']:
            errors.append('phase_snapshot_baseline_mismatch')
        if (not isinstance(phases.phase_ids, tuple)
                or any(not isinstance(uid, str) or not uid.strip() for uid in phases.phase_ids)
                or len(set(phases.phase_ids)) != len(phases.phase_ids)):
            errors.append('phase_snapshot_identities_invalid')
    if not errors and isinstance(candidate, dict):
        entries = candidate.get('changes' if mode == 'AD1' else 'facts')
        if isinstance(entries, list):
            for entry in entries:
                fact = entry.get('fact') if mode == 'AD1' and isinstance(entry, dict) else entry
                scope = fact.get('scope') if isinstance(fact, dict) else None
                if isinstance(scope, dict) and scope.get('kind') == 'PHASE':
                    if scope.get('id') not in phases.phase_ids:
                        errors.append('fact_phase_identity_not_registered')
    if errors:
        return _outcome(deepcopy(previous), errors, False)
    after, errors, accepted = commit_candidate(previous, candidate, store, mode,
                                               reference_policy=reference_policy)
    return _outcome(after, errors, accepted)
