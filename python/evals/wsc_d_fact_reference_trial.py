"""Fact eligibility representation A/B; one change, no semantic prompt addition."""
import asyncio
import hashlib
import os
from pathlib import Path

import evals.wsc_d_semantic_ablation as previous
from memory.wsc_fact_reference_candidate import FactReferenceCalls
from memory.wsc_semantic_coverage_candidate import FullStateCalls

ROOT=previous.ROOT.parent/'wsc-D-fact-reference-254'
ARMS=('A1','D_slot','D_factrefs')


def prepare():
    previous.ROOT=ROOT;previous.ARMS=ARMS
    plan=previous.prepare();plan.pop('sentence',None)
    plan.update(hypothesis='Eligible fact identities and runtime-bound base reduce invalid retirement declarations without deciding semantic state.',
        single_change='Both D arms have identical complete-state/observations interface. D_factrefs only encodes prior task-fact retirement choices by ID and compiles them to original quotes/base.',
        semantic_sentence_enabled=False,prior_253='Preserved incomplete payment-stopped experiment; no completed/failed HTTP request resent.')
    for p in [__file__,'python/memory/wsc_fact_reference_candidate.py']:
        plan['code_sha256'][p]=hashlib.sha256(Path(p).read_bytes()).hexdigest()
    previous.base.e.write(ROOT/'preflight-manifest.json',plan);return plan


def transport(calls,sources,arm):
    candidate=calls
    if arm=='D_factrefs':candidate=FactReferenceCalls(candidate,sources)
    candidate=previous.base.ObservationCalls(FullStateCalls(candidate))
    return previous.base.DeltaCalls(previous.base.DeclarationCalls(candidate),sources)


async def execute(plan):
    previous.ROOT=ROOT;previous.ARMS=ARMS
    previous.base.ROOT=ROOT;previous.base.ARMS=ARMS
    await previous.base.execute(plan,transport_factory=transport,seed_factory=previous.seeds)


if __name__=='__main__':
    if os.environ.get('WSC_D_FACT_REFERENCE_EXECUTE')=='1':
        try:asyncio.run(execute(previous.base.f.c.load(ROOT/'preflight-manifest.json')))
        except previous.base.f.EvaluationStop as exc:print(previous.base.f.c.canonical({'evaluation_stopped':str(exc)}),flush=True)
    else:print(previous.base.f.c.canonical({'prepared':prepare()['arms']}))
