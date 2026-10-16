"""One content-scope sentence ablation using the existing own-state evaluator."""
import asyncio
import hashlib
import os
from pathlib import Path

import evals.wsc_d_observation_continuity as base
from memory.wsc_semantic_coverage_candidate import FullStateCalls,SemanticCoverageCalls,CONTENT_SCOPE

ROOT=base.ROOT.parent/'wsc-D-semantic-ablation-253'
ARMS=('A1','D_slot','D_semantic')


def prepare():
    base.ROOT=ROOT;base.ARMS=ARMS
    plan=base.prepare()
    plan.update(hypothesis='One generic semantic content scope improves chosen working evidence and continuation beyond the same complete-state/observations interface.',branch_parallelism=2,
        single_change='D_slot and D_semantic both use required declaration channel, exact delta, merge=false schema and native optional observations; only D_semantic appends CONTENT_SCOPE.',
        common_protocol_change='Full-state schema and result slot differ from oldD; do not attribute their combination to the semantic sentence.',
        sentence=CONTENT_SCOPE,old_D_comparison='251 retained as historical, not a new matched semantic ablation arm.')
    for p in [__file__,'python/memory/wsc_semantic_coverage_candidate.py',
            'python/evals/wsc_d_observation_continuity.py','python/evals/wsc_d_combined_continuity.py',
            'python/evals/wsc_api_budget.py']:
        plan['code_sha256'][p]=hashlib.sha256(Path(p).read_bytes()).hexdigest()
    base.e.write(ROOT/'preflight-manifest.json',plan);return plan


def seeds(plan):
    base.combined.ROOT=ROOT
    branches={}
    for case in plan['cases']:
        name=case['case']
        for arm in ARMS:
            branch=base.combined.recover_seed(name,arm,prior_arm='A1' if arm=='A1' else 'D_delta')
            branches[name,arm]=base.combined.restart(branch,1)
        d_arms=[arm for arm in ARMS if arm!='A1']
        assert len(d_arms)==2
        left,right=(branches[name,arm] for arm in d_arms)
        assert all(left[k]==right[k] for k in ('hot','sources','native','consumed','pending','accepted_fold'))
        base.e.write(ROOT/name/'seed-proof.json',{'paired_seed_identical':True,'hot_sha256':base.f.c.digest(left['hot']),
            'source_bytes_identical':(left['folder']/'source.jsonl').read_bytes()==(right['folder']/'source.jsonl').read_bytes()})
    return branches


def transport(calls,sources,arm):
    candidate=base.ObservationCalls(FullStateCalls(calls))
    if arm=='D_semantic':candidate=SemanticCoverageCalls(candidate)
    return base.DeltaCalls(base.DeclarationCalls(candidate),sources)


async def execute(plan):
    base.ROOT=ROOT;base.ARMS=ARMS
    await base.execute(plan,transport_factory=transport,seed_factory=seeds)


if __name__=='__main__':
    if os.environ.get('WSC_D_SEMANTIC_EXECUTE')=='1':
        try:asyncio.run(execute(base.f.c.load(ROOT/'preflight-manifest.json')))
        except base.f.EvaluationStop as exc:print(base.f.c.canonical({'evaluation_stopped':str(exc)}),flush=True)
    else:print(base.f.c.canonical({'prepared':prepare()['arms']}))
