"""Phase precheck A/B with retained 28 probes and legal transition controls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

from evals.wsc_ad_candidate import canonical, commit_candidate, evidence, initial
from evals.wsc_mechanical_guard_candidate import PhaseIdentitySnapshot, commit
import evals.wsc_d_guard_probes as probes

ROOT = Path('D:/lea/XenYon code/_wsc_out/wsc-phase-identity-272')
ORIGINAL = ROOT.parent / 'wsc-reliable-control-228'


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    ROOT.mkdir(exist_ok=False)
    old_report = (ORIGINAL / 'guard-probes.json').read_bytes()
    snapshots = {}
    for case in ('long_noise_task', 'completed_waiting_authority'):
        folder = ROOT / case
        folder.mkdir()
        old = ORIGINAL / case
        for pattern in ('source-*.jsonl', 'declaration-*.json', 'AD2-committed-cold-state.json'):
            for source in old.glob(pattern):
                shutil.copyfile(source, folder / source.name)
        native = json.loads((old / 'committed-native-checkpoint.json').read_text(encoding='utf-8'))['native']
        state = json.loads((old / 'AD2-committed-cold-state.json').read_text(encoding='utf-8'))['state']
        snapshots[case] = PhaseIdentitySnapshot.from_checkpoint(case, state['checkpoint_id'], native['checkpoint'])
    probes.ROOT = ROOT
    baseline = probes.probe()
    assert baseline == json.loads(old_report)
    (ROOT / 'guard-probes.json').rename(ROOT / 'baseline-probes.json')
    details = []

    def guarded(previous, candidate, store, mode, reference_policy):
        result = commit(previous, candidate, store, mode,
                        phases=snapshots[previous['goal_id']], reference_policy=reference_policy)
        details.append({k: v for k, v in result.items() if k != 'state'})
        return result['state'], result['errors'], result['accepted']

    probes.commit_candidate = guarded
    candidate = probes.probe()
    (ROOT / 'guard-probes.json').rename(ROOT / 'candidate-probes.json')
    paired = []
    for old, new, detail in zip(baseline['probes'], candidate['probes'], details):
        assert (old['case'], old['mode'], old['mutation']) == (new['case'], new['mode'], new['mutation'])
        semantic = new['mutation'] in {'unsupported_constraint_shortening', 'unrelated_user_terminal_reopen'}
        paired.append({'case': new['case'], 'mode': new['mode'], 'mutation': new['mutation'],
                       'class': 'semantic' if semantic else 'mechanical',
                       'before_target_preserved': old['target_preserved'],
                       'after_target_preserved': new['target_preserved'],
                       'before_accepted': old['accepted'], 'after_accepted': new['accepted'],
                       **detail})
    checks = []

    def check(name, value):
        checks.append({'name': name, 'passed': bool(value)})

    check('old_report_unchanged', (ORIGINAL / 'guard-probes.json').read_bytes() == old_report)
    mechanical = [row for row in paired if row['class'] == 'mechanical']
    semantic = [row for row in paired if row['class'] == 'semantic']
    check('all_22_mechanical_targets_protected', len(mechanical) == 22 and all(r['after_target_preserved'] for r in mechanical))
    check('semantic_acceptance_not_changed_or_claimed_verified', len(semantic) == 6 and all(
        r['before_accepted'] == r['after_accepted'] and r['semantic_status'] == 'SEMANTIC_UNVERIFIED' for r in semantic))
    store = evidence([{'id': 'source', 'role': 'user', 'content': 'Declared phase-specific constraint.'}])
    previous = initial('independent-task')
    fact = {'fact_id': 'fact', 'kind': 'constraint', 'content': 'Declared phase-specific constraint.',
            'status': 'ACTIVE', 'scope': {'kind': 'PHASE', 'id': 'implementation'},
            'evidence_refs': [{'event_id': 'source', 'content_hash': store['source']['hash']} ]}
    candidate = {'baseline': 0, 'goal_id': previous['goal_id'], 'source_cursor': 0, 'facts': [fact]}
    phase = PhaseIdentitySnapshot('independent-task', 0, ('implementation',))
    untouched = canonical((previous, candidate, store))
    result = commit(previous, candidate, store, 'AD2', phases=phase)
    check('legal_phase_commits_without_semantic_truth_claim', result['accepted'] and not result['errors']
          and result['mechanical_status'] == 'VALID' and result['semantic_status'] == 'SEMANTIC_UNVERIFIED'
          and result['state']['checkpoint_id'] == 1)
    check('inputs_immutable', canonical((previous, candidate, store)) == untouched)
    registered = PhaseIdentitySnapshot('independent-task', 0, ('implementation', 'new-phase'))
    changed = deepcopy(candidate)
    changed['facts'][0]['scope']['id'] = 'new-phase'
    check('externally_registered_new_phase_allowed', commit(previous, changed, store, 'AD2', phases=registered)['accepted'])
    changed['phase_registry'] = ['new-phase']
    denied = commit(previous, changed, store, 'AD2', phases=phase)
    check('candidate_cannot_register_own_phase', not denied['accepted'] and denied['state'] == previous)
    for label, snapshot in [('wrong_task', PhaseIdentitySnapshot('other-task', 0, ('implementation',))),
                            ('stale_baseline', PhaseIdentitySnapshot('independent-task', 1, ('implementation',))),
                            ('boolean_baseline', PhaseIdentitySnapshot('independent-task', False, ('implementation',))),
                            ('duplicate_phase', PhaseIdentitySnapshot('independent-task', 0, ('implementation', 'implementation'))),
                            ('empty_phase_id', PhaseIdentitySnapshot('independent-task', 0, ('',))),
                            ('missing_registry', None)]:
        result = commit(previous, candidate, store, 'AD2', phases=snapshot)
        check(label + '_rejects_without_checkpoint_advance', not result['accepted'] and result['state'] == previous)
    corrupt = deepcopy(candidate)
    corrupt['facts'][0]['evidence_refs'][0]['content_hash'] = '0' * 64
    check('existing_hash_guard_preserved', not commit(previous, corrupt, store, 'AD2', phases=phase)['accepted'])
    task_only = deepcopy(candidate)
    task_only['facts'][0]['scope'] = {'kind': 'TASK'}
    check('legacy_task_scope_without_phases_allowed', commit(previous, task_only, store, 'AD2',
          phases=PhaseIdentitySnapshot('independent-task', 0, ()))['accepted'])
    partial = {'baseline': 0, 'goal_id': 'independent-task', 'source_cursor': 0,
               'changes': [{'action': 'add', 'fact': deepcopy(fact)}, {'action': 'add', 'fact': {'fact_id': 'invalid'}}]}
    result = commit(previous, partial, store, 'AD1', phases=phase)
    check('partial_salvage_not_full_validity', result['accepted'] and result['errors']
          and result['mechanical_status'] == 'PARTIAL' and len(result['state']['facts']) == 1)
    report = {'api_calls': 0, 'production_changes': 0, 'paired_probes': paired, 'checks': checks,
              'contracts_passed': sum(c['passed'] for c in checks), 'contracts_total': len(checks),
              'mechanical_before': {'protected': sum(r['before_target_preserved'] for r in mechanical), 'total': len(mechanical)},
              'mechanical_after': {'protected': sum(r['after_target_preserved'] for r in mechanical), 'total': len(mechanical)},
              'semantic_unverified': len(semantic),
              'nonclaims': ['Not full runtime phase registry or per-phase versions',
                            'No execution/file-version scope improvement', 'No semantic correctness or task-success improvement']}
    save(ROOT / 'report.json', report)
    identities = []
    for path in [Path(__file__), Path('python/evals/wsc_mechanical_guard_candidate.py'), Path('python/evals/wsc_ad_candidate.py')]:
        raw = path.read_bytes()
        (ROOT / path.name).write_bytes(raw)
        identities.append({'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest()})
    save(ROOT / 'source-identities.json', identities)
    print(json.dumps({k: v for k, v in report.items() if k not in {'paired_probes', 'checks', 'nonclaims'}}))
    assert report['contracts_passed'] == report['contracts_total']


if __name__ == '__main__':
    main()
