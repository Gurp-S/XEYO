"""Offline audit of archived D/V3/V3.1 requests. No model or network calls."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import evals.wsc_ad_experiment as e
from evals.wsc_ad_candidate import canonical


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def tokens(value):
    text=value if isinstance(value,str) else canonical(value)
    return e.tokens([{'role':'assistant','content':text}])


def review(root):
    out=root/'_wsc_out';report={'scope':'Offline saved-wire and renderer audit. No fresh model responses, no production changes.',
        'cases':[],'rubric':'Original bool grades unchanged; UNKNOWN vs explicit false is reported separately, never silently rescored.'}
    for name in e.CASES:
        original=out/'wsc-four-arm-206'/name
        native_text=read(original/'D-runtime-messages.json')[1]['content']
        native,end=json.JSONDecoder().raw_decode(native_text)
        native_prefix=native_text[:end]
        head224={label:read(out/'wsc-D-shell-224'/name/f'{label}-head.txt') for label in ('D1','D2')}
        state=head224['D2']['work_state'];facts=state['facts'];byid={f['fact_id']:f for f in facts}
        cp=native['checkpoint']
        assert byid['d:objective']['content']==cp['objective']
        assert json.loads(byid['d:phase']['content'])['declared_phase_state']==cp['phase_state']
        assert json.loads(byid['d:verification']['content'])['declared_verification_call_ids']==cp['verification_call_ids']
        for todo in native['todos']:
            assert json.loads(byid['d:todo:'+todo['id']]['content'])['todo']==todo
        for field in ('constraints','decisions'):
            assert Counter(f['content'] for f in facts if f['kind']==field[:-1])==Counter(f['quote'] for f in cp[field])
        context_ids=cp['context_message_ids']
        active_ids=cp['phase_state']['active_context_message_ids']
        old=read(out/'wsc-AD-222'/f'{name}-D-matched-0-request.json')
        new=read(out/'wsc-D-shell-224'/f'{name}-D2-matched-0-request.json')
        assert old['messages'][0]==new['messages'][0]
        assert old['messages'][-1]==new['messages'][-1]
        assert old['messages'][2:]==new['messages'][2:]
        parameters=('model','thinking','temperature','max_tokens','stream')
        assert all(old.get(k)==new.get(k) for k in parameters)
        parts225={}
        for label in ('D1','D2'):
            text=(out/'wsc-D-shell-225'/name/f'{label}-head.txt').read_text(encoding='utf-8')
            assert text.startswith(native_prefix)
            blocks=[json.loads(line) for line in text.splitlines()]
            parts={'full_hot':tokens(text),'native_semantic':tokens(native_prefix),'cold_address_envelope':tokens(blocks[1]),
                'native_semantic_literal_bytes_equal':True}
            if label=='D1':
                parts.update(raw_anchors=tokens(blocks[2]['protected_raw_anchors']),tiny_map=tokens(blocks[2]['evidence_map']))
            parts225[label]=parts
        source_sha=hashlib.sha256((original/'source.jsonl').read_bytes()).hexdigest()
        shown_sha=re.search(r'source_sha256=([a-f0-9]{64})',native_text[end:]).group(1)
        item={'case':name,'same_wire_system_query_tail_parameters_D_vs224D2':True,
            'all_objective_phase_todos_decisions_constraints_verification_content_preserved224':True,
            'context_ids_carried_in_phase':all(uid in active_ids for uid in context_ids),
            'context_ids_not_carried224':sorted(set(context_ids)-set(active_ids)),
            'context_message_ids_top_level_field_not_carried224':True,
            'native225':parts225,
            '224_status_counts':dict(Counter(f['status'] for f in facts)),
            '224_hot_implementation_notes':['All durable facts are directly serialized into hot work_state, including resolved todo details.',
                'Structured phase/todos are encoded inside string Fact.content, then JSON encoded again.',
                'Goal fact UNKNOWN is an adapter status; native D objective does not declare a lifecycle.'],
            'native_D_locator_hash':{'shown':shown_sha,'current_source':source_sha,'matches':shown_sha==source_sha},
            'parts_are_independent_token_estimates_not_additive':True}
        report['cases'].append(item)
    return report


if __name__=='__main__':
    root=Path(__file__).resolve().parents[2];folder=root/'_wsc_out/wsc-D-shell-review-227';folder.mkdir(exist_ok=True)
    report=review(root)
    (folder/'offline-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
