"""Exact post-checkpoint text evidence for isolated handoff requests.

Chronology selects evidence, never authorization or semantic state. Whole
records exceeding the byte budget remain explicitly discoverable by identity.
"""
from copy import deepcopy
import json

from synaptic.todo_snapshot import latest_todo_snapshot
from synaptic.task_fact_sources import source_text
from memory.wsc_handoff_generation import REQUEST


def materialize(sources,*,max_bytes=16000):
    if type(max_bytes) is not int or max_bytes<=0:raise ValueError('handoff_delta_budget_invalid')
    snapshot=latest_todo_snapshot(sources)
    base=snapshot.checkpoint_source if snapshot.observed and snapshot.checkpoint_source>=0 else -1
    ids=[str(row.get('message_id') or row.get('id')) for row in sources if row.get('message_id') or row.get('id')]
    if len(ids)!=len(set(ids)):raise ValueError('handoff_delta_source_ambiguous')
    candidates=[]
    for index,row in enumerate(sources[base+1:],base+1):
        if any(row.get(key) for key in ('note_key','note_kind','note_retracted')):continue
        text=source_text(row);uid=row.get('message_id') or row.get('id')
        if text is None or not uid:continue
        candidates.append({'source':index,'message_id':str(uid),'role':row.get('role'),'content':text,'text_complete':True})
    selected=[];deferred=[];used=0
    for record in reversed(candidates):
        size=len(json.dumps(record,ensure_ascii=False,separators=(',',':')).encode())
        if used+size>max_bytes:deferred.append(record['message_id']);continue
        selected.append(record);used+=size
    return {'base_checkpoint_message_id':sources[base].get('message_id') or sources[base].get('id') if base>=0 else None,
            'sources':list(reversed(selected)),'deferred_message_ids':list(reversed(deferred)),
            'source_records_after_checkpoint':len(sources)-base-1}


class DeltaCalls:
    def __init__(self,calls,sources):
        self.calls=calls
        self.payload=materialize(sources)
    async def call(self,body,label):
        candidate=deepcopy(body)
        matches=[row for row in candidate['messages'] if row.get('role')=='user'
                 and isinstance(row.get('content'),str) and row['content'].startswith(REQUEST)]
        if len(matches)!=1:raise ValueError('handoff_delta_request_boundary_invalid')
        matches[0]['content']+='\n提交后的来源增量='+json.dumps(self.payload,ensure_ascii=False,separators=(',',':'))
        return await self.calls.call(candidate,label)
