"""Native tool frames for the existing eval actor; legacy payloads unchanged."""
from copy import deepcopy
import inspect
import json

from engine.abort import AbortController
from msgtypes.message import tool_result_message
from tools.base_tool import ToolResult


def legacy_message(use, value, error):
    return {'role': 'tool', 'content': [{'type': 'tool_result', 'tool_use_id': use.id,
            'content': json.dumps(value, ensure_ascii=False), 'is_error': error}]}


async def execute(use, sink, cold):
    if use.name == 'ArtifactWrite':
        value = sink.call(use.input)
    elif callable(getattr(cold, 'execute', None)):
        value = cold.execute(use, AbortController())
    else:
        value = cold.call(use.name, use.input)
    if inspect.isawaitable(value):
        value = await value
    if not isinstance(value, ToolResult):
        return value, False, legacy_message(use, value, False)
    execution = value.execution_metadata()
    row = tool_result_message(use.id, use.name, value.content, is_error=value.is_error,
                              images=value.images, status=value.status, execution=execution)
    observed = {'content': value.content, 'images': deepcopy(value.images),
                'status': value.status, 'execution': execution, 'metadata': deepcopy(value.metadata)}
    error = bool(value.is_error or value.status == 'cancelled')
    return observed, error, {'role': row.role, 'name': row.name,
                           'tool_call_id': row.tool_call_id, 'content': row.content}
