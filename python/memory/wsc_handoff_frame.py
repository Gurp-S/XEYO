"""Content of one dedicated assistant frame, using the main-message contract.

This collector has no cross-request cache and no task-state authority. Only
normally completed streams may be emitted by the generation caller.
"""
from copy import deepcopy


class HandoffFrame:
    def __init__(self):
        self.text = []
        self.reasoning = []
        self.blocks = []

    def observe(self, chunk):
        if chunk.kind == 'text_delta':
            self.text.append(chunk.text)
        elif chunk.kind == 'reasoning_delta':
            self.reasoning.append(chunk.text)
        elif chunk.kind == 'reasoning_block':
            from engine.reasoning_blocks import validate_reasoning_block
            validate_reasoning_block(chunk.block)
            self.blocks.append(deepcopy(chunk.block))

    def message(self, uses):
        from msgtypes.message import assistant_text_message
        message = assistant_text_message(''.join(self.text), uses,
            reasoning=''.join(self.reasoning), reasoning_blocks=self.blocks)
        return {'role': message.role, 'content': message.content}
