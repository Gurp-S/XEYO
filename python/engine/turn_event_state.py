"""Recovery facts carried by the runner's existing SSE event protocol."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
	from engine.turn_runner import _DetachedTurn


def payload(frame: bytes) -> dict[str, Any]:
	"""Decode one complete SSE event (not an arbitrary network read)."""
	try:
		lines = frame.decode('utf-8').splitlines()
		data = '\n'.join(line[5:].lstrip(' ') for line in lines if line.startswith('data:'))
		value = json.loads(data or frame)
		return value if isinstance(value, dict) else {}
	except (ValueError, UnicodeError):
		return {}


def apply_event(turn: _DetachedTurn, kind: str, frame: bytes) -> bool:
	"""Return whether recovery facts changed; text deltas need no JSON parsing."""
	if kind not in {'permission_pending', 'permission_resolved', 'tool_call', 'tool_result',
		'multi_agent_task', 'multi_agent_progress', 'error', 'stopped', 'task_state_changed'}:
		return False
	body = payload(frame)
	xy = body.get('xy')
	xy = xy if isinstance(xy, dict) else {}
	if kind == 'error':
		error = body.get('error')
		turn.outcome = 'failed'
		turn.outcome_reason = str(error.get('type') or 'model_error') if isinstance(error, dict) else 'model_error'
	elif kind == 'stopped':
		if turn.outcome != 'failed':
			turn.outcome, turn.outcome_reason = 'stopped', 'stopped'
	elif kind == 'task_state_changed':
		status = xy.get('task_status')
		if status not in {'failed', 'stopped', 'cancelled'}:
			return False
		if turn.outcome != 'failed':
			turn.outcome = 'failed' if status == 'failed' else 'stopped'
			turn.outcome_reason = str(xy.get('error') or status)
	elif kind.startswith('permission_'):
		turn.waiting_permission = kind == 'permission_pending'
		if turn.status != 'stopping':
			turn.status = 'waiting_permission' if turn.waiting_permission else 'running'
	elif kind in {'tool_call', 'tool_result'}:
		tool_id = str(xy.get('tool_use_id') or '')
		if not tool_id:
			return False
		if kind == 'tool_call' and tool_id not in turn.incomplete_tools:
			turn.incomplete_tools.append(tool_id)
		elif kind == 'tool_result' and tool_id in turn.incomplete_tools:
			turn.incomplete_tools.remove(tool_id)
		else:
			return False
	else:
		agent_id = str(xy.get('agent_id') or '')
		if not agent_id or agent_id in turn.active_agents:
			return False
		turn.active_agents.append(agent_id)
	return True
