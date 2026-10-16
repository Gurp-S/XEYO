"""Fresh311 timeline with one evidence-role change; idempotent scoring separate."""
import asyncio
from copy import deepcopy
from pathlib import Path
import sys

import evals.wsc_ten_generation_task as t
from evals.wsc_task_actor_candidate import grade as strict_grade

ROOT=t.ROOT.parent/'wsc-ten-generation-observation-role-313'


def observational_carrier(row):
    if row['role']=='user':return {'role':'user','content':row['content']}
    # An external observation is not a new assistant action. All original
    # speaker/call/result identity remains literal data inside the capsule.
    return {'role':'user','content':t.p.e.canonical({'source_record':row})}


def idempotent_grade(sink,expected,before_hash=None):
    result=strict_grade(sink,expected,before_hash)
    if expected is not None and not sink.attempts and result['strict_format'].get('artifact_correct'):
        path=sink.root/'result.json'
        if path.exists() and before_hash==t.p.sha(path.read_bytes()):
            result['idempotent_completion']=True
            result['task_success']=True
    return result


async def prepare():
    t.ROOT=ROOT
    if not ROOT.exists():
        await t.prepare()
    else:
        assert not (ROOT/'run-report.json').exists() and not (ROOT/'free-scores').exists()
    plan=t.p.load(ROOT/'preflight-manifest.json')
    plan.update(evidence_role='External source_record outer role user; original inner roles/contents unchanged.',
        scoring='Strict score retained; behavior accepts correct unchanged artifact without writes. Explicit no-write stages remain strict.',
        wrapper_code_sha256=t.p.sha(Path(__file__).read_bytes()),parent='311',preparation_only=True)
    # Free execution-boundary and idempotence checks; no model or gold enters
    # the working branches.
    sink=t.ExactArtifactSink(ROOT/'free-scores')
    sink.call({'file_path':'result.json','content':'{"value":23}\n'})
    before=t.p.sha((sink.root/'result.json').read_bytes())
    fresh=t.ExactArtifactSink(sink.root)
    assert not strict_grade(fresh,{'value':23},before)['task_success']
    assert idempotent_grade(fresh,{'value':23},before)['task_success']
    assert not idempotent_grade(fresh,{'value':24},before)['task_success']
    assert idempotent_grade(fresh,None,before)['task_success']
    fresh.call({'file_path':'result.json','content':'{"value":23}\n'})
    assert not idempotent_grade(fresh,None,before)['task_success']
    rows=[{'id':'u','role':'user','content':'new request'}, {'id':'r','role':'tool','content':[{'type':'tool_result','tool_use_id':'c','content':'exact result'}]}]
    for row in rows:
        old=t.carrier(row);new=observational_carrier(row)
        assert old['content']==new['content']
        assert row['role']=='user' or (old['role']=='assistant' and new['role']=='user')
    plan['free_score_checks']={'correct_existing_file_idempotent':True,'wrong_existing_file_rejected':True,
        'explicit_no_write_preserves_hash_and_zero_attempts':True,'same_byte_write_still_violates_no_write':True,
        'only_carrier_outer_role_changes':True}
    t.p.e.write(ROOT/'preflight-manifest.json',plan)
    print(t.p.e.canonical({'checks':plan['free_score_checks'],'API':0}),flush=True)


async def execute():
    plan=t.p.load(ROOT/'preflight-manifest.json')
    assert plan['wrapper_code_sha256']==t.p.sha(Path(__file__).read_bytes())
    t.ROOT=ROOT;t.carrier=observational_carrier;t.artifact_grade=idempotent_grade
    await t.execute()


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');asyncio.run(prepare() if sys.argv[1]=='prepare' else execute())
