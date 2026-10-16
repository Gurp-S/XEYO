"""Isolated model wrapper retaining original completed handoff assistant frames.

Native recall/rejection loops construct tool-only assistant messages. This
adapter restores text and provider reasoning for the exact same call frame;
it does not modify tool arguments, validation, prompts or frozen task context.
"""
from copy import deepcopy
import json

from msgtypes.message import assistant_text_message
from synaptic.textutil import tool_use_blocks


class ReplayModel:
    def __init__(self, model, *, frames=None):
        self.model=model
        self.frames={} if frames is None else frames

    def __getattr__(self,name):
        return getattr(self.model,name)

    @property
    def last_usage(self):
        return self.model.last_usage

    @last_usage.setter
    def last_usage(self,value):
        self.model.last_usage=value

    def for_handoff(self,*,max_tokens):
        from memory.wsc_handoff_generation import limited_client
        return ReplayModel(limited_client(self.model,max_tokens),frames=self.frames)

    async def stream(self,messages,tools,abort):
        request=deepcopy(messages)
        for row in request:
            uses=list(tool_use_blocks(row)) if row.get('role')=='assistant' else []
            key=tuple(u['id'] for u in uses)
            if not key or key not in self.frames:continue
            entry=self.frames[key]
            actual=json.dumps(uses,ensure_ascii=False,sort_keys=True,separators=(',',':'))
            if actual!=entry['tool_blocks']:
                raise ValueError('handoff_replay_frame_mismatch')
            row['content']=deepcopy(entry['content'])
        text,reasoning,blocks,uses=[],[],[],[]
        completed=False
        stream=self.model.stream(request,tools,abort)
        try:
            async for chunk in stream:
                if chunk.kind=='text_delta':text.append(chunk.text)
                elif chunk.kind=='reasoning_delta':reasoning.append(chunk.text)
                elif chunk.kind=='reasoning_block':
                    from engine.reasoning_blocks import validate_reasoning_block
                    validate_reasoning_block(chunk.block);blocks.append(deepcopy(chunk.block))
                elif chunk.kind=='tool_use' and chunk.tool_use:uses.append(deepcopy(chunk.tool_use))
                yield chunk
            completed=True
        finally:
            await stream.aclose()
            if completed and uses:
                row=assistant_text_message(''.join(text),uses,reasoning=''.join(reasoning),reasoning_blocks=blocks)
                key=tuple(u.id for u in uses)
                if key in self.frames:raise ValueError('handoff_replay_call_identity_conflict')
                self.frames[key]={'content':deepcopy(row.content),
                    'tool_blocks':json.dumps(list(tool_use_blocks({'role':'assistant','content':row.content})),ensure_ascii=False,sort_keys=True,separators=(',',':'))}
