"""Phase and file-version freezes for the WSC sidecar.

The freeze is deliberately opt-in. It reuses a completed main-chain decision
until a phase signal changes, while allowing new tail nodes to be represented
by the already existing REQUESTS/PATHS channels. Working-set entries are
reused only when their file-version facts are unchanged.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from synaptic.types import FileState


def phase_signature(graph: Any, seeds: Any, region_end: int) -> str:
	"""Stable phase key; writes/errors and seed facts define a new phase."""
	events = [
		(n.idx, n.kind, bool(n.is_error), bool(n.is_write), n.error_sig)
		for n in graph.nodes
		if n.idx < region_end and (n.is_error or n.is_write)
	]
	payload = {
		"goal": seeds.goal,
		"original_task": seeds.original_task,
		"constraints": list(seeds.constraints),
		"unresolved": list(seeds.unresolved_errors),
		"todos": list(seeds.todos),
		"pin_paths": list(seeds.pin_paths),
		"events": events,
	}
	return hashlib.sha1(
		json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
			"utf-8"
		)
	).hexdigest()[:20]


def file_version(state: FileState) -> tuple[Any, ...]:
	"""Facts that mean the file-state entry has materially changed."""
	return (
		state.observed_hash,
		state.stale,
		state.stale_at,
		state.diff_summary,
	)


def freeze_working_set(
	previous: tuple[FileState, ...],
	current: tuple[FileState, ...],
	*,
	limit: int = 12,
) -> tuple[FileState, ...]:
	"""Keep previous order and objects for unchanged file versions."""
	by_path = {state.path: state for state in current}
	out: list[FileState] = []
	seen: set[str] = set()
	for old in previous:
		now = by_path.get(old.path)
		if now is None:
			continue
		out.append(old if file_version(old) == file_version(now) else now)
		seen.add(old.path)
	for now in current:
		if now.path not in seen:
			out.append(now)
	return tuple(out[: max(0, int(limit))])


__all__ = ["file_version", "freeze_working_set", "phase_signature"]
