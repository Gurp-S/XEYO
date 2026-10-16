"""Isolated declaration schema boundary and one semantic coverage principle."""
from copy import deepcopy

from memory.wsc_handoff_generation import REQUEST
from memory.wsc_declaration_candidate import TOOLS

CONTENT_SCOPE = '交接内容范围：继续当前工作所需的结果事实、具体值及其依据。'


def declaration_row(body):
    names={t.get('function',{}).get('name') for t in body.get('tools',[])}
    rows=[row for row in body['messages'] if row.get('role')=='user'
          and isinstance(row.get('content'),str) and row['content'].startswith(REQUEST)]
    if 'TodoWrite' not in names or not names<=TOOLS or len(rows)!=1:
        raise ValueError('semantic_coverage_request_boundary_invalid')
    return rows[0]


class FullStateCalls:
    """Dedicated handoff transaction cannot request an incremental merge."""
    def __init__(self, calls):self.calls=calls

    async def call(self, body, label):
        wire=deepcopy(body)
        declaration_row(wire)
        matches=[t['function'] for t in wire.get('tools',[])
                 if t.get('function',{}).get('name')=='TodoWrite']
        if len(matches)!=1:raise ValueError('full_state_tool_boundary_invalid')
        matches[0]['parameters']['properties']['merge']={'type':'boolean','const':False,'default':False}
        return await self.calls.call(wire,label)


class SemanticCoverageCalls:
    """One high-level content scope; no task-specific values or source selection."""
    def __init__(self, calls):self.calls=calls

    async def call(self, body, label):
        wire=deepcopy(body)
        declaration_row(wire)['content']+='\n'+CONTENT_SCOPE
        return await self.calls.call(wire,label)
