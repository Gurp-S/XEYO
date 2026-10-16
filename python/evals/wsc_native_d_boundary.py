"""Actual native D validation boundaries, retaining existing safeguards."""
from copy import deepcopy
import json
from pathlib import Path

from evals.wsc_d_handoff_shell_control import extract_d
from memory.wsc_handoff_validation import validate
import evals.wsc_ad_experiment as e


ROOT=e.ROOT.parent/'wsc-elimination-229'


def run():
    ROOT.mkdir(exist_ok=True);report={'scope':'Native D validators on actual retained sources and checkpoint; controlled candidate mutations, no LLM.', 'cases':[]}
    for name in e.CASES:
        original=e.ORIGINAL/name
        rows=[json.loads(s) for s in (original/'source.jsonl').read_text(encoding='utf-8').splitlines()]
        native,decl,_,_,_=extract_d(original);sources=rows+decl
        for mutation in ('unchanged','invented_context','invented_quote','invented_verification','nonexistent_current_phase',
                         'phase_removed','active_constraint_omitted','task_constraint_downgraded','completed_step_reopened_without_event'):
            raw=deepcopy(native)
            if mutation=='invented_context':raw['checkpoint']['context_message_ids'].append('nonexistent-user')
            elif mutation=='invented_quote':raw['checkpoint']['constraints'][0]['quote']='This quote is absent from the actual source.'
            elif mutation=='invented_verification':raw['checkpoint']['verification_call_ids'].append('nonexistent-call')
            elif mutation=='nonexistent_current_phase':raw['checkpoint']['phase_state']['current_phase_id']='nonexistent-phase'
            elif mutation=='phase_removed':raw['checkpoint'].pop('phase_state')
            elif mutation=='active_constraint_omitted':
                raw['checkpoint']['constraints'].pop(0);raw['checkpoint']['phase_state']['fact_scopes']['constraints'].pop(0)
            elif mutation=='task_constraint_downgraded':
                raw['checkpoint']['phase_state']['fact_scopes']['constraints'][0]={'kind':'phase','phase_id':raw['checkpoint']['phase_state']['current_phase_id']}
            elif mutation=='completed_step_reopened_without_event':
                completed=[t for t in raw['todos'] if t['status']=='completed']
                if not completed:continue
                completed[0]['status']='in_progress'
            try:validate(raw,sources,require_phase=True);accepted=True;error=None
            except Exception as exc:accepted=False;error={'type':type(exc).__name__,'code':str(exc),'detail':getattr(exc,'detail',None)}
            report['cases'].append({'source_case':name,'mutation':mutation,'D_existing_accepted':accepted,'D_existing_error':error,
                'candidate':raw,'source_records':len(sources)})
    good=[c for c in report['cases'] if c['mutation']=='unchanged'];assert len(good)==2 and all(c['D_existing_accepted'] for c in good)
    bad=[c for c in report['cases'] if c['mutation']!='unchanged']
    report['summary']={'unchanged_valid_accepted':len(good),'invalid_mutations':len(bad),'already_rejected_by_D':sum(not c['D_existing_accepted'] for c in bad)}
    e.write(ROOT/'native-D-existing-guards.json',report)
    return report


if __name__=='__main__':
    report=run();print(json.dumps({'summary':report['summary'],'cases':[{k:v for k,v in c.items() if k not in {'candidate','source_records'}} for c in report['cases']]},ensure_ascii=False))
