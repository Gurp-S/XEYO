"""Explicit projection adapter; original archive and source bindings unchanged."""
from copy import deepcopy
import json
from .codex import CodexCheckpointAdapter
from ..contracts import encode,require
from ..context_projection import MODE
from ..control_sources import is_control_source


class ContextCheckpointAdapter(CodexCheckpointAdapter):
    def __init__(self,context):self.context=context

    def capabilities(self):
        return {**super().capabilities(),'adapter':'context_checkpoint_v1','source_projection':MODE,
                'context_store_binding':self.context.references.store_binding}

    def render(self,body,sources,cut,locators,*,source_index,understanding_index):
        display=[];known={row['id']:row for row in sources}
        for row in body['sources']:
            if row['kind']=='message' or is_control_source(row):display.append(row);continue
            link=self.context.references.get(source_id=row['id'])
            if link:self.context.references.validate(link)
            display.append({**row,'text':encode(link['visible_view']) if link else None})
        items=super().render({**body,'sources':display},sources,cut,locators,source_index=source_index,understanding_index=understanding_index)
        facts_index=sum(row['kind']=='message' for row in body['sources'])
        facts=json.loads(items[facts_index]['content'][0]['text'])
        for entry in facts['historical_excerpts']:
            row=known[entry['source_id']]
            if is_control_source(row):continue
            link=self.context.references.get(source_id=row['id'])
            entry['reference']='source:s'+str(row['seq'])
            if link:
                self.context.references.validate(link)
                entry['text']=encode(link['visible_view']);entry['representation']='runtime_projection'
                entry['result_reference']='result:'+link['result_id']
            else:
                entry['text']=None;entry['representation']='historical_source_reference'
        facts['format']='wsc.context_state/1'
        items[facts_index]['content'][0]['text']=encode(facts)
        tail=[row for row in sources if row['seq']>cut]
        for i,row in enumerate(tail,start=len(items)-len(tail)):
            if row['kind']!='result' or is_control_source(row):continue
            delivery=self.context.delivery(row['id'])
            if delivery and delivery.get('external'):
                item=deepcopy(items[i])
                require(item.get('type') in {'function_call_output','custom_tool_call_output'}
                        and type(item.get('output')) is str,'context_tail_text_projection_unavailable')
                item['output']=encode(delivery);items[i]=item
        return items
