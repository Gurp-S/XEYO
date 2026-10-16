"""Isolated V3/V3.1 evaluation core; never imported by the agent runtime.

Checks identity and witnessed transitions, not natural-language entailment.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from engine.turn_snapshot import _atomic_write


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def source_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join(source_text(v) for v in value)
    if isinstance(value, dict):
        return '\n'.join(source_text(value[k]) for k in ['text', 'content'] if k in value)
    return ''


def evidence(rows):
    result = {}
    for seq, row in enumerate(rows):
        uid = row.get('id') or row.get('message_id')
        if not uid or uid in result:
            raise ValueError('ambiguous_evidence_identity')
        result[uid] = {'sequence': seq, 'hash': digest(row), 'row': row,
                       'text': source_text(row.get('content'))}
    return result


def denoise(rows, archive):
    """Only identical execution payload dedup and reversible long-result excerpts.

    Identity wrappers, errors, user text and assistant text stay intact.
    No heuristic resolution, file version or semantic stale inference.
    """
    seen = {}; output = []; reductions = []
    for seq, row in enumerate(rows):
        item = deepcopy(row)
        if isinstance(item.get('content'), list):
            for block in item['content']:
                if block.get('type') != 'tool_result' or not isinstance(block.get('content'), str):
                    continue
                raw = block['content']; key = hashlib.sha256(raw.encode()).hexdigest()
                locator = {'path': str(archive), 'line': seq+1, 'payload_sha256': key}
                if key in seen:
                    block['content'] = canonical({'duplicate_of': seen[key], 'exact_evidence': locator})
                    reductions.append({'sequence': seq, 'kind': 'exact_execution_duplicate'})
                elif len(raw) > 12000:
                    block['content'] = canonical({'excerpt_start': raw[:4500], 'excerpt_end': raw[-1500:],
                                                  'original_characters': len(raw), 'exact_evidence': locator})
                    reductions.append({'sequence': seq, 'kind': 'reversible_execution_excerpt'})
                seen[key] = seq
        output.append(item)
    return output, reductions


ACTIVE = {'ACTIVE', 'OPEN', 'REOPENED', 'UNKNOWN', 'AMBIGUOUS', 'NEEDS_EVIDENCE'}
STATUSES = {
    'request': {'OPEN', 'RESOLVED', 'CANCELLED', 'REOPENED', 'UNKNOWN', 'NEEDS_EVIDENCE'},
    'constraint': {'ACTIVE', 'SUPERSEDED', 'RETIRED', 'UNKNOWN', 'NEEDS_EVIDENCE'},
    'decision': {'ACTIVE', 'SUPERSEDED', 'UNKNOWN', 'NEEDS_EVIDENCE'},
    'failure': {'OPEN', 'RESOLVED', 'REOPENED', 'UNKNOWN', 'NEEDS_EVIDENCE'},
    'progress': {'ACTIVE', 'RESOLVED', 'UNKNOWN', 'NEEDS_EVIDENCE'},
}


def validate_fact(fact, store, old=None, action='add', reference_policy='quote'):
    required = {'fact_id', 'kind', 'content', 'status', 'scope', 'evidence_refs'}
    if not isinstance(fact, dict) or not required <= set(fact):
        raise ValueError('fact_schema_invalid')
    if not all(isinstance(fact[k], str) and fact[k] for k in ['fact_id', 'kind', 'content', 'status']):
        raise ValueError('fact_field_invalid')
    if fact['status'] not in STATUSES.get(fact['kind'], set()):
        raise ValueError('fact_status_invalid')
    scope = fact['scope']
    if not isinstance(scope, dict) or scope.get('kind') not in {'TASK', 'PHASE', 'EXECUTION', 'FILE_VERSION'}:
        raise ValueError('fact_scope_invalid')
    if scope['kind'] != 'TASK' and not scope.get('id'):
        raise ValueError('fact_scope_identity_missing')
    refs = fact['evidence_refs']
    if not isinstance(refs, list) or not refs:
        raise ValueError('fact_evidence_missing')
    sequences = []
    for ref in refs:
        if not isinstance(ref, dict) or ref.get('event_id') not in store:
            raise ValueError('fact_evidence_missing')
        record = store[ref['event_id']]
        if ref.get('content_hash') and ref['content_hash'] != record['hash']:
            raise ValueError('corrupt_evidence_reference')
        if reference_policy == 'quote':
            quote = ref.get('quote')
            if not isinstance(quote, str) or not quote or quote not in record['text']:
                raise ValueError('fact_quote_not_in_source')
        elif reference_policy != 'event':
            raise ValueError('reference_policy_invalid')
        sequences.append(record['sequence'])
    if old:
        if old['kind'] != fact['kind']:
            raise ValueError('fact_identity_contradiction')
        changed = any(old[k] != fact[k] for k in ['content', 'status', 'scope'])
        if changed and max(sequences) <= old['updated_at']:
            raise ValueError('transition_without_new_evidence')
        if old['status'] not in ACTIVE and fact['status'] in ACTIVE and action != 'reopen':
            raise ValueError('terminal_fact_revival')
        if old['status'] not in ACTIVE and fact['status'] in ACTIVE:
            if not any(store[r['event_id']]['row']['role'] == 'user' and store[r['event_id']]['sequence'] > old['updated_at'] for r in refs):
                raise ValueError('reopen_without_new_user_evidence')
    result = deepcopy(fact)
    result['introduced_at'] = old['introduced_at'] if old else min(sequences)
    result['updated_at'] = max(sequences)
    return result


def commit_candidate(previous, candidate, store, mode, reference_policy='quote'):
    """AD1 item salvage; AD2 whole-state validation. No semantic auto-repair."""
    previous = deepcopy(previous)
    if not isinstance(candidate, dict) or candidate.get('baseline') != previous['checkpoint_id']:
        return previous, ['checkpoint_baseline_mismatch'], False
    if candidate.get('goal_id') != previous['goal_id']:
        return previous, ['goal_identity_contradiction'], False
    cursor = candidate.get('source_cursor')
    if type(cursor) is not int or cursor < previous['source_cursor'] or cursor >= len(store):
        return previous, ['source_cursor_invalid'], False
    old = {f['fact_id']: f for f in previous['facts']}; errors = []; merged = deepcopy(old) if mode == 'AD1' else {}
    entries = candidate.get('changes' if mode == 'AD1' else 'facts')
    if not isinstance(entries, list):
        return previous, ['candidate_schema_invalid'], False
    identities = set()
    for entry in entries:
        action = entry.get('action', 'update') if isinstance(entry, dict) else ''
        fact = entry.get('fact') if mode == 'AD1' and isinstance(entry, dict) else entry
        try:
            if mode == 'AD1' and action not in {'add', 'update', 'retire', 'reopen'}:
                raise ValueError('candidate_action_invalid')
            uid = fact['fact_id']
            if uid in identities:
                raise ValueError('duplicate_fact_identity')
            identities.add(uid)
            if mode == 'AD1' and ((action == 'add' and uid in old) or (action != 'add' and uid not in old)):
                raise ValueError('fact_action_identity_invalid')
            if mode == 'AD2' and uid in old and old[uid]['status'] not in ACTIVE and fact['status'] in ACTIVE:
                action = 'reopen' if fact.get('reopen') is True else 'update'
            valid = validate_fact(fact, store, old.get(uid), action, reference_policy)
            if valid['updated_at'] > cursor:
                raise ValueError('evidence_after_candidate_cursor')
            if action == 'retire' and valid['status'] in ACTIVE:
                raise ValueError('retire_status_invalid')
            merged[uid] = valid
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(str(exc))
            if str(exc) in {'corrupt_evidence_reference', 'fact_identity_contradiction'}:
                return previous, errors, False
    if mode == 'AD2':
        for uid, fact in old.items():
            if uid not in merged:
                errors.append('active_fact_omitted' if fact['status'] in ACTIVE else 'terminal_fact_tombstone_omitted')
        if errors:
            return previous, errors, False
    result = deepcopy(previous)
    result.update(checkpoint_id=previous['checkpoint_id']+1, source_cursor=cursor, facts=list(merged.values()))
    return result, errors, True


def persist_state(path, state):
    _atomic_write(Path(path), canonical({'state': state, 'sha256': digest(state)}), durable=True)


def read_state(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if digest(data['state']) != data['sha256']:
        raise ValueError('state_digest_mismatch')
    return data['state']


def initial(goal_id):
    return {'checkpoint_id': 0, 'goal_id': goal_id, 'source_cursor': -1, 'facts': []}


def prompt(mode, state, cursor):
    fact = {'fact_id': 'stable ID', 'kind': 'request|constraint|decision|failure|progress',
            'content': 'semantic current state', 'status': 'kind-specific uppercase lifecycle status',
            'scope': {'kind': 'TASK|PHASE|EXECUTION|FILE_VERSION', 'id': 'required except TASK'},
            'evidence_refs': [{'event_id': 'actual source ID', 'quote': 'exact substring from that source'}]}
    output = {'baseline': state['checkpoint_id'], 'goal_id': state['goal_id'], 'source_cursor': cursor}
    output['changes' if mode == 'AD1' else 'facts'] = ([{'action': 'add|update|retire|reopen', 'fact': fact}] if mode == 'AD1' else [fact])
    return ('CONTEXT CHECKPOINT COMPACTION. Produce only a JSON candidate work state, no tools. '
            'Describe current goal, phase, requests, constraints, decisions, failures, progress, unresolved issues and important concrete values as source-grounded facts. '
            'Differentiate reported verification from runtime execution. No invented evidence IDs or quotations. '
            'Request states OPEN/RESOLVED/CANCELLED/REOPENED; constraints ACTIVE/SUPERSEDED/RETIRED; '
            'decisions ACTIVE/SUPERSEDED; failures OPEN/RESOLVED/REOPENED; progress ACTIVE/RESOLVED. '
            'UNKNOWN and NEEDS_EVIDENCE are permitted. A later phase does not silently retire TASK constraints. '
            'AD1 declares changes only; unmentioned facts persist. AD2 declares the entire state including terminal facts; '
            'terminal reopening needs reopen:true and a newer user citation. '
            'Execution identities and file versions are external runtime facts, never candidate-owned. '
            'All citations must refer to original source events. Output shape: '+canonical(output)+
            '\nPrevious committed state: '+canonical(state))
