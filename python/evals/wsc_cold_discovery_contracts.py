"""Directory preview fidelity, budgets and transport exposure; zero API."""
import hashlib
import json
from pathlib import Path
import tempfile

from memory.wsc_cold_discovery_candidate import DiscoverableSources
from memory.wsc_cold_source_candidate import ColdSources
import evals.wsc_ad_experiment as e

ROOT=e.ROOT.parent/'wsc-D-cold-discovery-contracts-243'


def main():
    ROOT.mkdir(exist_ok=True);assert not (ROOT/'contracts.json').exists()
    checks=[]
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'source.jsonl'
        rows=[{'id':'u'+str(i),'role':'user','content':'中文原文'+str(i)+' '+('x'*300)+' 金额947'} for i in range(20)]
        rows.append({'id':'tool','role':'tool','content':[{'type':'tool_result','tool_use_id':'probe','content':'字段 value=947\n原始回执'}]})
        raw=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows).encode();path.write_bytes(raw)
        seal=hashlib.sha256(raw).hexdigest();new=DiscoverableSources(path,seal);old=ColdSources(path,seal)
        page=new.catalog({'start':0,'limit':16})
        assert [{k:v for k,v in r.items() if k!='text_preview'} for r in page['records']]==old.catalog({'start':0,'limit':16})['records'];checks.append('same_order_and_metadata')
        for r in page['records']:
            preview=r['text_preview'];text=rows[r['source']]['content']
            assert preview['content']==text[preview['offset']:preview['offset']+len(preview['content'])] and len(preview['content'])<=240
        checks.append('prefix_exact_offsets_unicode')
        query=new.catalog({'start':0,'limit':16,'query':'金额947'})
        for r in query['records']:
            for p in r['text_preview']['passages']:assert p['content']==rows[r['source']]['content'][p['offset']:p['end_offset']] and '金额947' in p['content']
        checks.append('literal_query_exact_passages')
        t=new.catalog({'start':20,'limit':1})['records'][0]['text_preview']
        assert t['content']==rows[-1]['content'][0]['content'] and t['tool_call_id']=='probe';checks.append('decoded_result_preview')
        new.PAGE_BYTES=900;found=[];cursor=0
        for _ in range(30):
            page=new.catalog({'start':cursor,'limit':16})
            assert len(json.dumps(page,ensure_ascii=False,separators=(',',':')).encode())<=900
            found.extend(r['source'] for r in page['records'])
            if page['next_source'] is None:break
            assert page['next_source']>cursor;cursor=page['next_source']
        assert found==list(range(len(rows)));checks.append('byte_budget_pagination_no_skips')
        assert path.read_bytes()==raw;checks.append('archive_unmodified')
    # Real-source target text must be in the next wire input, not merely logged.
    report=json.loads((ROOT.parent/'wsc-D-cold-candidate-241/run-report.json').read_text(encoding='utf-8'))
    gold=json.loads((e.OLD/'gold.json').read_text(encoding='utf-8'));exposure=[]
    for observation in report['observations']:
        target=gold[observation['case']]['cold_excerpt'];seen=False
        for n in range(4):
            path=ROOT.parent/'wsc-D-cold-candidate-241'/f"{observation['case']}-{observation['arm']}-cold-{n}-request.json"
            if not path.exists():continue
            body=json.loads(path.read_text(encoding='utf-8'))
            for message in body['messages']:
                if message['role']!='tool':continue
                try:value=json.loads(message.get('content') or '')
                except ValueError:continue
                if value.get('message_id')==target['source_message_id'] and str(value.get('content','')).startswith(target['expected']):seen=True
        exposure.append({'case':observation['case'],'arm':observation['arm'],'target_in_successful_next_request':seen})
    assert sum(x['target_in_successful_next_request'] for x in exposure)==3
    checks.append('three_target_payloads_reached_next_wire_request')
    e.write(ROOT/'contracts.json',{'checks':checks,'exposure':exposure,'api_calls':0})
    print(e.canonical({'checks':len(checks),'target_exposures':3,'api_calls':0}))


if __name__=='__main__':main()
