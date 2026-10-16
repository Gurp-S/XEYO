"""Atomic quote/scope declaration representation; no semantic scope defaults.

Compiles losslessly to the existing checkpoint format, keeping scope attached
to each model-owned fact instead of independently generated parallel arrays.
Not connected to production or a model request until independently validated.
"""
from copy import deepcopy
import json


def pack(native):
    result=deepcopy(native);cp=result['checkpoint'];phase=cp['phase_state']
    scopes=phase.pop('fact_scopes')
    for field in ('decisions','constraints'):
        facts=cp[field];tags=scopes[field]
        if len(facts)!=len(tags):raise ValueError('scoped_fact_cardinality_invalid')
        cp[field]=[{**fact,'scope':deepcopy(tag)} for fact,tag in zip(facts,tags)]
    return result


def unpack(atomic):
    result=deepcopy(atomic);cp=result['checkpoint'];phase=cp['phase_state']
    if 'fact_scopes' in phase:raise ValueError('scoped_fact_authority_duplicated')
    tags={}
    for field in ('decisions','constraints'):
        facts=cp[field]
        if not isinstance(facts,list):raise ValueError('scoped_fact_list_invalid')
        if any(not isinstance(fact,dict) or set(fact)!={'source_message_id','quote','scope'} for fact in facts):
            raise ValueError('scoped_fact_schema_invalid')
        tags[field]=[deepcopy(fact['scope']) for fact in facts]
        cp[field]=[{key:fact[key] for key in ('source_message_id','quote')} for fact in facts]
    phase['fact_scopes']=tags
    return result


def schema(native_schema):
    result=deepcopy(native_schema);cp=result['input_schema']['properties']['checkpoint']
    phase=cp['properties']['phase_state']
    scopes=phase['properties'].pop('fact_scopes');phase['required'].remove('fact_scopes')
    for field in ('decisions','constraints'):
        item=cp['properties'][field]['items']
        item['properties']['scope']=scopes['properties'][field]['items']
        item['required'].append('scope')
    return result


class ScopedCalls:
    """Wire-only encoding; native validation and durable API evidence stay intact."""
    def __init__(self, calls):
        self.calls = calls
        self.wire_arguments = {}
        self.audit = []

    async def call(self, body, label):
        wire = deepcopy(body)
        matches = [tool['function'] for tool in wire.get('tools', [])
                   if tool.get('function', {}).get('name') == 'TodoWrite']
        if len(matches) != 1:
            raise ValueError('scoped_fact_tool_boundary_invalid')
        function = matches[0]
        function['parameters'] = schema({'input_schema': function['parameters']})['input_schema']
        # Rejected declarations are repeated in the generator's conversation.
        # Preserve their original wire representation, not the native adapter form.
        for message in wire['messages']:
            for use in message.get('tool_calls') or []:
                if use['function']['name'] == 'TodoWrite' and use['id'] in self.wire_arguments:
                    use['function']['arguments'] = self.wire_arguments[use['id']]
        response = await self.calls.call(wire, label)
        native_response = deepcopy(response)
        for choice in native_response.get('choices', []):
            for use in choice['message'].get('tool_calls') or []:
                if use['function']['name'] != 'TodoWrite':
                    continue
                raw = use['function']['arguments']
                self.wire_arguments[use['id']] = raw
                try:
                    converted = unpack(json.loads(raw))
                except (ValueError, KeyError, TypeError) as exc:
                    # No fabricated scope or repair: the native generator sees
                    # the invalid declaration and applies its existing feedback.
                    self.audit.append({'call_id': use['id'], 'encoding_error': str(exc)})
                    continue
                use['function']['arguments'] = json.dumps(converted, ensure_ascii=False)
                self.audit.append({'call_id': use['id'], 'roundtrip_exact': pack(converted) == json.loads(raw)})
        return native_response
