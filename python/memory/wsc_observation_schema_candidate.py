"""Expose the existing model-selected exact-result slot in isolated handoffs.

No result selection, quote synthesis, semantic defaults, prompt addition,
or production switch changes. Native checkpoint/source validators still apply.
"""
from copy import deepcopy

from synaptic.task_observations import schema


class ObservationCalls:
    def __init__(self, calls):
        self.calls = calls

    async def call(self, body, label):
        wire = deepcopy(body)
        tools = [t['function'] for t in wire.get('tools', [])
                 if t.get('function', {}).get('name') == 'TodoWrite']
        if len(tools) != 1:
            raise ValueError('observation_tool_boundary_invalid')
        checkpoint = tools[0]['parameters']['properties']['checkpoint']
        if 'observations' in checkpoint['properties']:
            raise ValueError('observation_candidate_already_present')
        checkpoint['properties']['observations'] = schema()
        return await self.calls.call(wire, label)
