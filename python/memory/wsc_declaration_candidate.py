"""Side-path transport policy for isolated structured handoff transactions.

Not wired into task requests or production model clients. Semantic contents
remain model-owned; this policy only constrains the transaction output channel.
"""
from copy import deepcopy

TOOLS=frozenset({'TodoWrite','HandoffSource','HandoffCatalog'})


def body_for_declaration(body):
    tools=body.get('tools') or []
    names={tool.get('function',{}).get('name') for tool in tools}
    if 'TodoWrite' not in names or not names<=TOOLS:
        raise ValueError('declaration_tool_boundary_invalid')
    # This candidate is provider-specific, not a claim about all providers.
    if body.get('thinking',{}).get('type')!='disabled':
        raise ValueError('declaration_tool_choice_unavailable')
    result=deepcopy(body)
    result['tool_choice']='required'
    return result


class DeclarationCalls:
    """Apply the boundary on every generation/recall/validation continuation."""
    def __init__(self,calls):self.calls=calls
    async def call(self,body,label):
        return await self.calls.call(body_for_declaration(body),label)
