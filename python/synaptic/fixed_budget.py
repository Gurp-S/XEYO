"""Fixed-segment allocation helpers.

REQUESTS is the only channel in the fixed segment that carries the original
user wording.  When the fixed budget is tight, lower-priority fixed facts must
give up space before REQUESTS is degraded.  This module owns that allocation
policy so the renderer and the project assembler do not each invent a rule.
"""

from __future__ import annotations

from typing import Any

from synaptic.textutil import node_token_len

Line = tuple[str, str]

_DEGRADE_ORDER = (
	"[PATHS]",
	"[WORKING SET]",
	"[NEXT]",
	"[TODO]",
	"[UNRESOLVED]",
	"[CONSTRAINTS]",
)


def segment_tokens(items: list[Line] | tuple[Line, ...]) -> int:
	return sum(node_token_len(line) + 1 for _key, line in items)


def request_floor_tokens(
	fixed_budget_tokens: int, configured_floor_tokens: int, *, has_requests: bool
) -> int:
	"""Return the reserved REQUESTS budget for this fixed segment."""
	if not has_requests:
		return 0
	return min(
		max(0, int(fixed_budget_tokens)),
		max(0, int(configured_floor_tokens)),
	)


def _prefix_within_budget(items: list[Line], budget_tokens: int) -> list[Line]:
	out: list[Line] = []
	used = 0
	for header, line in items:
		cost = node_token_len(line) + 1
		if used + cost > budget_tokens:
			break
		out.append((header, line))
		used += cost
	return out


def trim_fixed_for_request_floor(
	groups: dict[str, list[Line]],
	*,
	fixed_headers: tuple[str, ...],
	request_header: str,
	fixed_budget_tokens: int,
	request_floor_tokens_: int,
) -> tuple[dict[str, list[Line]], int]:
	"""Trim lower-priority fixed facts until REQUESTS has its reserved space.

	The returned groups never spend the reserved floor on non-REQUESTS lines.
	Lines are kept in their existing order and only whole lines are removed;
	the function never edits a fact into a partial sentence.  ``[REQUESTS]`` is
	never trimmed here; its own downgrade ladder runs afterwards.
	"""
	out = {header: list(items) for header, items in groups.items()}
	reserve = request_floor_tokens(
		fixed_budget_tokens,
		request_floor_tokens_,
		has_requests=bool(out.get(request_header)),
	)
	allow_non_request = max(0, int(fixed_budget_tokens) - reserve)

	def non_request_total() -> int:
		return sum(
			segment_tokens(out.get(header, ()))
			for header in fixed_headers
			if header != request_header
		)

	current = non_request_total()
	if current <= allow_non_request:
		return out, reserve

	# The order is explicit: paths and working state yield first; the protected
	# fact sections are touched only if lower-priority sections cannot make room.
	for header in _DEGRADE_ORDER:
		if header == request_header or header not in fixed_headers:
			continue
		current = non_request_total()
		if current <= allow_non_request:
			break
		items = out.get(header, [])
		if not items:
			continue
		other = current - segment_tokens(items)
		keep_budget = max(0, allow_non_request - other)
		kept = _prefix_within_budget(items, keep_budget)
		if kept:
			out[header] = kept
		else:
			out.pop(header, None)

	return out, reserve


__all__ = [
	"request_floor_tokens",
	"segment_tokens",
	"trim_fixed_for_request_floor",
]
