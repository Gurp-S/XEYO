"""Same native candidate through existing D checks and then current D2 bridge.

Native failures count as existing-D protection, never incremental D2 wins.
Actual TodoWrite receipts are confined to fresh in-memory stores.
"""
from copy import deepcopy
import json

from evals.wsc_native_d_boundary import ROOT
from evals.wsc_d_handoff_shell_control import extract_d, candidate_from_d
from evals.wsc_ad_candidate import evidence, commit_candidate, read_state, digest
from memory.wsc_handoff_validation import validate
from tools.todo_write_tool.todo_write_tool import TodoWriteTool
import evals.wsc_ad_experiment as e


def run(*, corrected=False):
    source_report=json.loads((ROOT/'native-D-existing-guards.json').read_text(encoding='utf-8'))
    pairs=[]
    for name in e.CASES:
        original=e.ORIGINAL/name
        rows=[json.loads(s) for s in (original/'source.jsonl').read_text(encoding='utf-8').splitlines()]
        native,decl,_,oldreceipt,_=extract_d(original);base=rows+decl
        prior=read_state(e.ROOT.parent/'wsc-D-shell-224'/name/'D2-state.json')
        trials=[{'name':c['mutation'],'candidate':deepcopy(c['candidate']),'sources':deepcopy(base),'legality':'valid' if c['mutation']=='unchanged' else 'invalid'}
            for c in source_report['cases'] if c['source_case']==name]
        completed=[t for t in native['todos'] if t['status']=='completed']
        if completed:
            copy=deepcopy(native);copy['todos']=[t for t in copy['todos'] if t['id']!=completed[0]['id']]
            trials.append({'name':'omit_completed_step_hot_detail','candidate':copy,'sources':deepcopy(base),'legality':'valid',
                'rationale':'Completed step remains in exact prior declaration; unfinished steps and constraints unchanged. Native D permits this compaction.'})
        copy=deepcopy(native);fact=copy['checkpoint']['constraints'].pop(0)
        copy['checkpoint']['phase_state']['fact_scopes']['constraints'].pop(0)
        uid='controlled-retirement-'+name
        new={'id':uid,'role':'user','content':'本次受控状态事件：明确撤销此前这一条约束：'+fact['quote']+'。其余约束保持，继续当前任务。'}
        copy['checkpoint']['context_message_ids'].append(uid)
        copy['checkpoint']['phase_state']['active_context_message_ids'].append(uid)
        copy['fact_disposition']={'base_checkpoint_message_id':oldreceipt['id'],
            'retired_facts':[{'field':'constraints','quote':fact['quote'],'event_message_ids':[uid]}]}
        trials.append({'name':'explicit_supported_constraint_retirement','candidate':copy,'sources':deepcopy(base)+[new],'legality':'valid',
            'rationale':'Fresh explicit user retirement with native fact_disposition, preserving all other state.'})
        if corrected:
            for mutation,authorized in [('unrelated_user_objective_reinterpretation',False),('completed_step_reopened_after_unrelated_user',False),('explicit_supported_step_reopen',True)]:
                if 'step' in mutation and not completed:continue
                copy=deepcopy(native);uid='controlled-'+mutation+'-'+name
                text=('明确重开已完成步骤 '+completed[0]['id']+'，重新执行这一项，其他事项不变。') if authorized else '只报告当前进度；没有新的执行授权，当前任务及完成状态不变。'
                event={'id':uid,'role':'user','content':text}
                copy['checkpoint']['context_message_ids'].append(uid)
                copy['checkpoint']['phase_state']['active_context_message_ids'].append(uid)
                if mutation=='unrelated_user_objective_reinterpretation':copy['checkpoint']['objective']='重新执行此前已结束的历史修复任务'
                else:next(t for t in copy['todos'] if t['id']==completed[0]['id'])['status']='in_progress'
                trials.append({'name':mutation,'candidate':copy,'sources':deepcopy(base)+[event],'legality':'valid' if authorized else 'invalid',
                    'rationale':'Explicit user authorization exists.' if authorized else 'New evidence exists but explicitly preserves current objective/completed status.'})
        for i,trial in enumerate(trials):
            raw=trial['candidate'];sources=trial['sources']
            entry={'case':name,'mutation':trial['name'],'legality':trial['legality'],'rationale':trial.get('rationale'),
                'D_accepted':False,'D_error':None,'D2_accepted':False,'D2_added_errors':[], 'current_bridge_not_full_V3':True}
            try:parsed=validate(raw,sources,require_phase=True);entry['D_accepted']=True
            except Exception as exc:entry['D_error']=str(exc)
            if entry['D_accepted']:
                # The D branch actually stores the declaration in a private store.
                tool=TodoWriteTool();out=tool.call(parsed);content=tool.map_tool_result_to_content(out)
                call_id=f'controlled-native-{name}-{i}';receipt_id=call_id+'-receipt'
                events=[{'id':call_id+'-invocation','role':'assistant','content':[{'type':'tool_use','id':call_id,'name':'TodoWrite','input':raw}]},
                    {'id':receipt_id,'role':'tool','content':[{'type':'tool_result','tool_use_id':call_id,'content':content,'is_error':False,
                        'execution':{'status':'ok','complete':True}}]}]
                store=evidence(sources+events)
                candidate=candidate_from_d(name,{'todos':raw['todos'],'checkpoint':raw['checkpoint']},store,receipt_id)
                if corrected:candidate['baseline']=prior['checkpoint_id']
                after,errors,accepted=commit_candidate(prior,candidate,store,'AD2',reference_policy='event')
                entry.update(D2_accepted=accepted,D2_added_errors=errors,candidate_ir=candidate,
                    prior_state_sha256=digest(prior),after_state_sha256=digest(after),private_receipt_id=receipt_id)
                if not accepted and trial['legality']=='valid':entry['failure_owner']='current native-to-WorkState bridge or additional guard contract; not model failure'
            entry['incremental_illegal_block']=bool(entry['D_accepted'] and not entry['D2_accepted'] and trial['legality']=='invalid')
            entry['incremental_valid_reject']=bool(entry['D_accepted'] and not entry['D2_accepted'] and trial['legality']=='valid')
            pairs.append(entry)
    summary={'paired_candidates':len(pairs),'invalid_candidates':sum(p['legality']=='invalid' for p in pairs),
        'existing_D_invalid_blocks':sum(p['legality']=='invalid' and not p['D_accepted'] for p in pairs),
        'D_accepted_invalid_candidates':sum(p['legality']=='invalid' and p['D_accepted'] for p in pairs),
        'additional_D2_illegal_blocks':sum(p['incremental_illegal_block'] for p in pairs),
        'D_accepted_valid_candidates':sum(p['legality']=='valid' and p['D_accepted'] for p in pairs),
        'additional_D2_valid_rejects':sum(p['incremental_valid_reject'] for p in pairs)}
    destination=ROOT.parent/'wsc-elimination-230' if corrected else ROOT
    destination.mkdir(exist_ok=True)
    e.write(destination/'incremental-D-D2-control.json',{'scope':__doc__,'corrected_version_binding':corrected,'pairs':pairs,'summary':summary})
    return summary


if __name__=='__main__':
    import os
    print(json.dumps(run(corrected=os.environ.get('WSC_GUARD_CORRECTED')=='1'),ensure_ascii=False))
