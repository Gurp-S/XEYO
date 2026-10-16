"""Aggregate immutable335 receipts; no paid requests or source modifications."""
import json
from pathlib import Path
from evals.wsc_recall_projection import ROOT


def main():
    load = lambda path: json.loads(path.read_text(encoding='utf-8'))
    before, after = (load(ROOT/(arm+'-projection.json')) for arm in ('before','after'))
    projection=[]
    for old,new in zip(before['cases'],after['cases']):
        assert old['case']==new['case'] and old['source_fingerprint']==new['source_fingerprint']
        assert old['semantic']==new['semantic'] and old['hot'][1:]==new['hot'][1:]
        assert old['hot'][0]['content'].split('\n\n',1)[0]==new['hot'][0]['content'].split('\n\n',1)[0]
        originals=lambda row:{p:h for p,h in row['objects'].items() if '-evidence-index.' not in p}
        assert originals(old)==originals(new)
        old_index=next(Path(p) for p in old['objects'] if '-evidence-index.' in p)
        new_index=next(Path(p) for p in new['objects'] if '-evidence-index.' in p)
        assert old_index.read_bytes().split(b'\n')[1:]==new_index.read_bytes().split(b'\n')[1:]
        projection.append({'case':new['case'],'head_bytes_before':old['head_bytes'],'head_bytes_after':new['head_bytes'],
            'reduction_pct':round(100*(1-new['head_bytes']/old['head_bytes']),2),
            'head_tokens_estimate_before':old['head_tokens_estimate'],'head_tokens_estimate_after':new['head_tokens_estimate'],
            'semantic_tail_originals_and_index_rows_equal':True,'cold_reads':new['actual_reads'],
            'grep_ok':new['grep_ok'],'restart_equal':new['restart_equal'],'frozen_equal':new['frozen_equal']})
    quality=load(ROOT/'api/run-report.json'); cold=load(ROOT/'cold-api/run-report.json')
    arms=[]
    for arm in ('semantic_before','semantic_after'):
        records=[r for r in quality['branches'] if r['arm']==arm]
        calls=[r for r in quality['calls'] if r['label'].startswith(arm+'-g')]
        state=lambda key:sum(r.get('answer',{}).get(key) is False for r in records)
        arms.append({'arm':arm,'events':len(records),'native_folds':sum(r['accepted'] for r in records),
            'task_success':sum(r['task_success'] for r in records),'state_correct':sum(r['state_correct'] for r in records),
            'state_total':sum(r['state_total'] for r in records),'restarts':sum(r.get('restart_equal',False) for r in records),
            'hot_tokens_estimate_sum':sum(r.get('hot_tokens',0) for r in records),
            'full_request_tokens_estimate_sum':sum(r.get('request_tokens',0) for r in records),
            'requests':len(calls),'cost_peak_estimate':sum(r['cost_estimate'] for r in calls),
            'stale_question_wrong':sum(r.get('answer',{}).get('old_question_open') is not (r['stage']==10) for r in records),
            'long_term_constraints_correct':sum(state(k) for k in ('publish_authorized','git_authorized','database_write_authorized'))})
    all_calls=quality['calls']+cold['calls']
    usages=[x['response']['usage'] for x in all_calls if x.get('usage_observed')]
    totals={key:sum(u.get(key,0) for u in usages) for key in ('prompt_tokens','completion_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens')}
    report={'projection':projection,'multi_generation':arms,
        'cold_generation':[{'arm':r['arm'],'requests':r['requests'],'exact_recovered':r['account_retained'] and r['exact_value_retained']} for r in quality['cold_generation']],
        'cold_consumer':[{k:r[k] for k in ('arm','correct','requests','actual_read','actual_grep')} for r in cold['cold_consumer']],
        'scope_fact_diagnostic':{k:cold['scope_diagnostic'][k] for k in ('requests','account_retained','exact_value_retained')},
        'api':{'calls':len(all_calls),'observed_usage_calls':len(usages),'unknown_cost_reserved':sum(x['cost_estimate'] for x in all_calls if not x.get('usage_observed')),
               'peak_cny_estimate':sum(x['cost_estimate'] for x in all_calls),**totals,
               'cache_hit_rate':totals['prompt_cache_hit_tokens']/totals['prompt_tokens'] if totals['prompt_tokens'] else None},
        'limits':['10 events include7 actual folds; three retained boundaries are not successful folds',
                  'runner logged orphan late-result removal; API evidence does not prove use of that receipt',
                  'same-product uses fixed neutral text, not new real-chat semantic quality evidence',
                  'two cold trigger specimens failed; scope-fact hypothesis not admitted',
                  'overall natural default switch and original228 acceptance remain open']}
    (ROOT/'result-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
