"""Bounded selected-result grounding, real-head audit; no model/API calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from memory.wsc_verification_result_candidate import materialize, canonical, MAX_PACKET_BYTES

ROOT=Path('D:/lea/XenYon code/_wsc_out/wsc-D-selected-results-262')


def main():
    assert not ROOT.exists();ROOT.mkdir()
    checks=[]
    sources=[{'id':'u','role':'user','content':'Task'},
        {'id':'a','role':'assistant','content':[{'type':'tool_use','id':'chosen','name':'Probe','input':{}}]},
        {'id':'r','role':'tool','content':[{'type':'tool_result','tool_use_id':'chosen','content':'{"units":17}',
            'is_error':False,'execution':{'id':'opaque','late':True,'complete':False}}]},
        {'id':'other','role':'tool','content':[{'type':'tool_result','tool_use_id':'unselected','content':'not selected'}]}]
    cp={'objective':'Task','context_message_ids':['u'],'verification_call_ids':['chosen']}
    before=deepcopy((sources,cp)); packet=materialize(sources,cp)
    assert len(packet['results'])==1 and packet['results'][0]['result']==sources[2]['content'][0]['content']
    assert packet['results'][0]['receipt_metadata']['execution']==sources[2]['content'][0]['execution']
    assert (sources,cp)==before
    checks.append('only_model_selected_results_and_literal_execution_metadata')
    packet['results'][0]['receipt_metadata']['execution']['late']=False
    assert sources[2]['content'][0]['execution']['late'] is True
    checks.append('returned_payload_and_metadata_do_not_mutate_sources')
    ambiguous=deepcopy(sources);ambiguous.append(deepcopy(sources[2]))
    bad=materialize(ambiguous,cp);assert not bad['results'] and bad['unresolved'][0]['reason']=='missing_or_ambiguous'
    checks.append('ambiguous_receipt_not_silently_selected')
    oversized=deepcopy(sources);oversized[2]['content'][0]['content']='大'*2048
    bounded=materialize(oversized,cp);assert bounded['results']==[] and bounded['deferred_call_ids']==['chosen']
    checks.append('whole_oversize_result_deferred_not_truncated')
    missing=deepcopy(cp);missing['verification_call_ids']=['missing']
    assert materialize(sources,missing)['unresolved'][0]['call_id']=='missing'
    checks.append('missing_binding_explicit_not_invented')
    audits=[];base=ROOT.parent/'wsc-D-fact-reference-254'
    for case in ['long_noise_task','completed_waiting_authority']:
        folder=base/case/'D_slot';state=json.loads((folder/'restart-3.json').read_text(encoding='utf-8'))['state']
        source=Path(state['source_locator']['path']);raw=source.read_bytes();assert hashlib.sha256(raw).hexdigest()==state['source_locator']['sha256']
        rows=[json.loads(s) for s in raw.decode('utf-8').splitlines() if s.strip()]
        cp=state['native']['checkpoint'];packet=materialize(rows,cp)
        assert len(canonical(packet).encode())<=MAX_PACKET_BYTES
        assert all(x['call_id'] in cp['verification_call_ids'] for x in packet['results'])
        for result in packet['results']:
            payload=next(b['content'] for b in rows[result['source_index']]['content'] if b.get('tool_use_id')==result['call_id'])
            assert result['result']==payload and hashlib.sha256(canonical(payload).encode()).hexdigest()==result['payload_sha256']
        (ROOT/(case+'-packet.json')).write_text(json.dumps(packet,ensure_ascii=False,indent=2),encoding='utf-8')
        audits.append({'case':case,'selected_bindings':len(cp['verification_call_ids']),'materialized':len(packet['results']),
            'packet_bytes':len(canonical(packet).encode()),'current_result_materialized':any(x['call_id']==case+'-probe-call-r2' for x in packet['results']),
            'late_result_materialized':any(x['call_id']==case+'-probe-call-r1' for x in packet['results']),
            'source_sha256':state['source_locator']['sha256']})
    checks.append('sealed_real_sources_payload_hashes_and_packet_budget')
    (ROOT/'contracts.json').write_text(json.dumps({'checks':checks,'audits':audits,'api_calls':0,
        'nonclaim':'No semantic current-result choice, consumer success or production admission.'},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':len(checks),'audits':audits,'api_calls':0},ensure_ascii=False))


if __name__=='__main__':main()
