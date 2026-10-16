"""Isolated E candidate: existing TodoWrite receipts, durable cursor, frozen view.

No production imports of this candidate. A presentation cursor is not a claim
of semantic completeness. Source events after a declaration remain visible.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from engine.turn_snapshot import _atomic_write
from memory.wsc_handoff_validation import validate
from memory.wsc_handoff_facts import validate_facts
from synaptic.todo_snapshot import latest_todo_snapshot
from synaptic.task_verification import collect
from tools.todo_write_tool.todo_write_tool import TodoWriteTool


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


class PersistentState:
    def __init__(self,path,session_id,*,restore=False):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.session_id=session_id
        if restore:
            envelope=json.loads(self.path.read_text(encoding='utf-8'))
            data=envelope['data']
            if data['session_id']!=session_id:raise ValueError('state_owner_mismatch')
            if hashlib.sha256(canonical(data).encode()).hexdigest()!=envelope['sha256']:raise ValueError('state_digest_mismatch')
            self.data=data
        else:
            if self.path.exists():raise ValueError('state_already_exists')
            self.data={'session_id':session_id,'rows':[],'state_version':0,'commit':None,'frozen_head':None,'generation':0,'published_after':0}
            self._publish(self.data)

    @property
    def rows(self):return self.data['rows']

    def _publish(self,data):
        envelope={'data':data,'sha256':hashlib.sha256(canonical(data).encode()).hexdigest()}
        _atomic_write(self.path,canonical(envelope),durable=True)
        self.data=data

    def append(self,row):
        if not row.get('id') or any(r['id']==row['id'] for r in self.rows):raise ValueError('source_identity_not_unique')
        data=deepcopy(self.data);data['rows'].append(deepcopy(row));self._publish(data)

    def commit(self,raw,call_id,*,expected_version,presented_before,declared_input=None):
        if expected_version!=self.data['state_version']:raise ValueError('state_revision_conflict')
        from synaptic.textutil import tool_use_blocks,tool_result_blocks
        calls=[(i,b) for i,row in enumerate(self.rows) for b in tool_use_blocks(row) if b.get('id')==call_id]
        receipts=[b for row in self.rows for b in tool_result_blocks(row) if b.get('tool_use_id')==call_id]
        submitted=raw if declared_input is None else declared_input
        if len(calls)!=1 or calls[0][1].get('name')!='TodoWrite' or canonical(calls[0][1].get('input'))!=canonical(submitted):raise ValueError('state_invocation_mismatch')
        if receipts:raise ValueError('state_call_already_receipted')
        if not isinstance(presented_before,int) or not 0<=presented_before<=calls[0][0]:raise ValueError('state_presentation_boundary_invalid')
        sources=self.rows[:presented_before]
        try:parsed=validate(raw,sources,require_phase=True)
        except ValueError as exc:
            if str(exc)=='handoff_verification_incomplete':
                from session.recovery_result_chain import supersessions
                replaced={(i,uid) for (_later,uid),i in supersessions(sources).items()}
                incomplete=[{'call_id':b['tool_use_id'],'source_message_id':row['id'],'execution':b.get('execution')} for i,row in enumerate(sources) for b in tool_result_blocks(row) if b.get('tool_use_id') in raw['checkpoint']['verification_call_ids'] and (i,str(b['tool_use_id'])) not in replaced and isinstance(b.get('execution'),dict) and (b['execution'].get('complete') is False or b['execution'].get('status')=='cancelled')]
                exc.detail={'error':str(exc),'incomplete_verifications':incomplete}
            raise
        validate_facts(raw,sources,require_citations=True)
        writer=TodoWriteTool(cwd=str(self.path.parent))
        out=writer.call(parsed)
        uid=f'{self.session_id}-receipt-{len(self.rows)}'
        content='source_message_id='+uid+'\n'+writer.map_tool_result_to_content(out)
        row={'id':uid,'role':'tool','tool_call_id':call_id,'content':[{'type':'tool_result','tool_use_id':call_id,'content':content,'is_error':False,'execution':{'status':'ok','complete':True}}]}
        data=deepcopy(self.data);data['rows'].append(row);data['state_version']+=1
        data['commit']={'receipt_index':len(data['rows'])-1,'presented_before':presented_before,'source_sha256':hashlib.sha256(canonical(sources).encode()).hexdigest(),'version':data['state_version']}
        self._publish(data)
        return row

    def fold(self):
        snapshot=latest_todo_snapshot(self.rows)
        if not snapshot.observed or snapshot.checkpoint is None or not self.data['commit']:raise ValueError('complete_committed_state_missing')
        receipts,unknown,_=collect(self.rows,snapshot.checkpoint['verification_call_ids'],len(self.rows),inline_bytes=8192)
        source=canonical(self.rows);digest=hashlib.sha256(source.encode()).hexdigest();archive=self.path.parent/('source-'+digest+'.json')
        if archive.exists():
            if archive.read_text(encoding='utf-8')!=source:raise ValueError('archive_identity_conflict')
        else:_atomic_write(archive,source,durable=True)
        from evals.wsc_state_patch_protocol import registry
        from session.recovery_result_chain import supersessions
        superseded={(i,uid) for (_later,uid),i in supersessions(self.rows).items()}
        from synaptic.textutil import tool_result_blocks
        pending=[{'call_id':b.get('tool_use_id'),'source_message_id':row['id'],'execution':b.get('execution')} for i,row in enumerate(self.rows) for b in tool_result_blocks(row) if (i,str(b.get('tool_use_id'))) not in superseded and isinstance(b.get('execution'),dict) and b['execution'].get('complete') is False]
        head=canonical({'todos':list(snapshot.records),'checkpoint':snapshot.checkpoint,'terminal':snapshot.terminal,'progress_basis':'declared','verification_receipts':receipts,'unknown_verification':unknown,'pending_executions':pending,'fact_registry':registry(snapshot.checkpoint),'source_archive':str(archive),'source_sha256':digest,'state_version':self.data['state_version'],'commit_source_message_id':self.rows[snapshot.source]['id']})
        data=deepcopy(self.data);data['frozen_head']=head;data['generation']+=1;data['published_after']=snapshot.source+1
        self._publish(data)
        return head

    def view(self):
        from session.late_result_projection import project
        projected=project(self.rows)
        if self.data['frozen_head'] is None:return projected
        # Folded declarations may be stale. Every subsequent event is appended;
        # no live prefix rewrite and no inference of a new objective from prose.
        tail=projected[self.data['published_after']:]
        for i,row in enumerate(tail):
            if row.get('role')=='tool':
                call_ids={b.get('id') for p in tail[:i] if p.get('role')=='assistant' for b in (p.get('content') or []) if isinstance(b,dict) and b.get('type')=='tool_use'}
                ids=[b.get('tool_use_id') for b in (row.get('content') or []) if isinstance(b,dict) and b.get('type')=='tool_result']
                if any(uid not in call_ids for uid in ids):
                    tail[i]={'id':row['id'],'role':'user','content':'Recorded source event: '+canonical(row)}
        return [{'role':'assistant','content':self.data['frozen_head']},*tail]

    def pending_count(self):
        if not self.data['commit']:return len(self.rows)
        return len(self.rows)-1-self.data['commit']['receipt_index']
