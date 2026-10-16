"""Independent full-new-event reference for chain231, no compaction.

Uses the same observer and engine safety. This is not a repair of prior answers.
"""
import asyncio
from copy import deepcopy
import os

import evals.wsc_ad_experiment as e
import evals.wsc_elimination_chain as chain


ROOT=e.ROOT.parent/'wsc-elimination-reference-232'


async def main():
    ROOT.mkdir(exist_ok=True);assert not (ROOT/'run-report.json').exists(),'No paid rerun'
    plan=chain.load(chain.ROOT/'preflight-manifest.json')
    # Branches and tool access remain under chain231, matching original observer.
    calls=e.Calls();e.ROOT=ROOT;os.environ['WSC_AD_TRANSPORT']='httpx-direct';calls.semaphore=asyncio.Semaphore(1)
    calls.report.update(protocol='Uncompacted controlled future events, same two D seed states, same query/tool limits. Separate reference, not merged with chain231.',observations=[])
    for case in plan['cases']:
        name=case['case'];branch=chain.start_branch(name,'RAW_REFERENCE')
        for n,events in enumerate(case['events']):
            branch['sources'].extend(deepcopy(events));branch['pending'].extend(deepcopy(events));chain.persist_sources(branch)
            observation=await chain.observe(calls,branch,name,'RAW_REFERENCE',n,case['expected'][n])
            calls.report['observations'].append(observation);calls.save()
            print(e.canonical({'case':name,'fold':n+1,'grade':observation.get('grade'),'error':observation.get('error')}),flush=True)
    calls.report['completed']=True;calls.save()


if __name__=='__main__':asyncio.run(main())
