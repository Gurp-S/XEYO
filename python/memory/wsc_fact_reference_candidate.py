"""Eligibility-bound fact retirement references, compiled to native validation.

The model chooses retirements and their event sources. Runtime owns the base
checkpoint and the exact prior field/quote identities. No semantic defaults.
"""
from copy import deepcopy
import hashlib
import json

from memory.wsc_handoff_fact_disposition import basis
from memory.wsc_semantic_coverage_candidate import declaration_row


def fact_id(fact):
    raw=json.dumps(fact,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    return 'fact_'+hashlib.sha256(raw).hexdigest()


class FactReferences:
    def __init__(self,sources):
        self.prior=basis(sources)
        self.by_id={}
        for fact in (self.prior or {}).get('task_facts',[]):
            identity=fact_id(fact)
            if identity in self.by_id:raise ValueError('fact_reference_identity_conflict')
            self.by_id[identity]=deepcopy(fact)

    def compile(self,raw):
        result=deepcopy(raw)
        value=result.get('fact_disposition')
        if value is None:return result
        if self.prior is None:raise ValueError('fact_reference_without_base')
        if not isinstance(value,dict) or set(value)!={'retired_facts'} or not isinstance(value['retired_facts'],list):
            raise ValueError('fact_reference_schema_invalid')
        retired=[];seen=set()
        for item in value['retired_facts']:
            if not isinstance(item,dict) or set(item)!={'fact_id','event_message_ids'}:
                raise ValueError('fact_reference_schema_invalid')
            identity=item['fact_id']
            if not isinstance(identity,str) or identity not in self.by_id:raise ValueError('fact_reference_not_eligible')
            if identity in seen:raise ValueError('fact_reference_duplicate')
            seen.add(identity)
            retired.append({**deepcopy(self.by_id[identity]),'event_message_ids':deepcopy(item['event_message_ids'])})
        result['fact_disposition']={'base_checkpoint_message_id':self.prior['base_checkpoint_message_id'],'retired_facts':retired}
        return result

    def wire(self,body):
        result=deepcopy(body);declaration_row(result)
        if self.prior is None:return result
        function=next(t['function'] for t in result['tools'] if t['function']['name']=='TodoWrite')
        properties=function['parameters']['properties'];disposition=properties['fact_disposition']
        events=deepcopy(disposition['properties']['retired_facts']['items']['properties']['event_message_ids'])
        properties['fact_disposition']={'type':'object','additionalProperties':False,
            'description':'Retirements selected from previously declared task-wide fact identities; the transaction binds the current base checkpoint.',
            'properties':{'retired_facts':{'type':'array','maxItems':len(self.by_id),'items':{
                'type':'object','additionalProperties':False,'properties':{
                    'fact_id':{'type':'string','enum':list(self.by_id)},'event_message_ids':events},
                'required':['fact_id','event_message_ids']}}},'required':['retired_facts']}
        marker=' Previous declared task-wide facts='
        prefix,separator,payload=function['description'].partition(marker)
        if not separator or json.loads(payload)!=self.prior:raise ValueError('fact_reference_schema_basis_mismatch')
        mapped={**self.prior,'task_facts':[{'fact_id':identity,**fact} for identity,fact in self.by_id.items()]}
        function['description']=prefix+marker+json.dumps(mapped,ensure_ascii=False)
        return result


class FactReferenceCalls:
    def __init__(self,calls,sources):
        self.calls=calls;self.references=FactReferences(sources)
        self.wire_arguments={};self.audit=[]

    async def call(self,body,label):
        wire=self.references.wire(body)
        for row in wire['messages']:
            for use in row.get('tool_calls') or []:
                if use['function']['name']=='TodoWrite' and use['id'] in self.wire_arguments:
                    use['function']['arguments']=self.wire_arguments[use['id']]
        response=await self.calls.call(wire,label);native=deepcopy(response)
        for choice in native.get('choices',[]):
            for use in choice['message'].get('tool_calls') or []:
                if use['function']['name']!='TodoWrite':continue
                raw=use['function']['arguments'];self.wire_arguments[use['id']]=raw
                try:decoded=json.loads(raw)
                except json.JSONDecodeError:continue  # Native invalid-JSON feedback owns this failure.
                # Invalid reference dialects are rejected, never repaired or
                # passed through to a native validator accepting legacy quotes.
                try:compiled=self.references.compile(decoded)
                except ValueError as exc:
                    self.audit.append({'call_id':use['id'],'encoding_error':str(exc)})
                    raise
                use['function']['arguments']=json.dumps(compiled,ensure_ascii=False)
                self.audit.append({'call_id':use['id'],'base_runtime_owned':True,
                    'retired_count':len((compiled.get('fact_disposition') or {}).get('retired_facts',[]))})
        return native
