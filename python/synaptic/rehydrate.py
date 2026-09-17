"""Deterministic working-set rehydration planning.

This is an opt-in algorithm-side planner.  It does not infer task meaning: a
node is eligible only when its explicit file reference intersects the current
working-set paths.  The caller decides whether and where to render the plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from synaptic.graph import Graph
from synaptic.types import FileState

Line = tuple[str, str]
LeaseBook = tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class RehydrationPlan:
	"""A bounded, deterministic set of cold nodes to make visible again."""

	paths: tuple[str, ...]
	nodes: tuple[int, ...]
	tokens: int
	budget_tokens: int
	reasons: dict[int, str] = field(default_factory=dict)
	selected_paths: tuple[str, ...] = ()

	@property
	def exhausted(self) -> bool:
		return self.tokens >= self.budget_tokens and self.budget_tokens > 0


def working_set_paths(states: tuple[FileState, ...] | list[FileState]) -> tuple[str, ...]:
	"""Return explicit working-set paths in stable first-seen order."""
	return tuple(dict.fromkeys(s.path for s in states if str(s.path).strip()))


def decay_leases(
	previous: LeaseBook,
	*,
	working_paths: tuple[str, ...] = (),
	min_working_set_lease: int = 3,
) -> LeaseBook:
	"""Advance leases one turn without creating new leases.

	A path that was explicitly rehydrated and remains in the working set keeps a
	short floor.  This prevents the expensive ``hot -> cold -> hot`` oscillation,
	while paths that leave the working set naturally expire.
	"""
	working = set(working_paths)
	minimum = max(0, int(min_working_set_lease))
	out: dict[str, int] = {}
	for path, remaining in previous:
		next_remaining = max(0, int(remaining) - 1)
		if path in working and int(remaining) > 0:
			next_remaining = max(next_remaining, minimum)
		if next_remaining > 0:
			out[str(path)] = next_remaining
	return tuple(sorted(out.items()))


def renew_leases(
	previous: LeaseBook,
	*,
	selected_paths: tuple[str, ...] = (),
	initial_lease: int = 3,
	refresh_lease: int = 5,
) -> LeaseBook:
	"""Create or refresh leases for paths that actually supplied a node."""
	out = {str(path): max(0, int(remaining)) for path, remaining in previous}
	initial = max(0, int(initial_lease))
	refresh = max(initial, int(refresh_lease))
	for path in dict.fromkeys(str(p) for p in selected_paths if str(p).strip()):
		out[path] = max(out.get(path, 0), refresh if path in out else initial)
	return tuple(sorted((path, remaining) for path, remaining in out.items() if remaining > 0))


def leased_paths(leases: LeaseBook) -> tuple[str, ...]:
	"""Return active lease paths in deterministic order."""
	return tuple(path for path, remaining in sorted(leases) if int(remaining) > 0)


def plan_working_set_rehydration(
	graph: Graph,
	states: tuple[FileState, ...] | list[FileState],
	*,
	region_end: int,
	budget_tokens: int,
	exclude: tuple[int, ...] | set[int] = (),
	extra_paths: tuple[str, ...] = (),
	eligible_paths: tuple[str, ...] | None = None,
) -> RehydrationPlan:
	"""Select prior nodes touching current working-set files.

	Selection is two-pass: first one newest/high-risk node per path, then the
	remaining candidates globally.  This prevents a single hot file from
	starving the other files in the working set.  ``node.tokens`` is the charge;
	no partial node is selected and no semantic classification is performed.
	"""
	base_paths = working_set_paths(states) if eligible_paths is None else tuple(str(p) for p in eligible_paths)
	paths = tuple(dict.fromkeys(path for path in (*base_paths, *(str(p) for p in extra_paths)) if path.strip()))
	limit = max(0, int(region_end))
	budget = max(0, int(budget_tokens))
	excluded = set(exclude)

	def priority(node) -> tuple[int, int]:
		# Explicit execution facts only: unresolved failures and writes first,
		# then newest evidence.  The final index tie-break is deterministic.
		risk = 0 if node.is_error else 1 if node.is_write else 2
		return risk, -node.idx

	by_path: dict[str, list[int]] = {path: [] for path in paths}
	for node in graph.nodes:
		if node.idx >= limit or node.idx in excluded or not node.text.strip():
			continue
		for path in paths:
			if path in node.refs:
				by_path[path].append(node.idx)
	for path in paths:
		by_path[path].sort(key=lambda idx: priority(graph.node(idx)))

	ordered: list[int] = []
	seen: set[int] = set()
	for path in paths:
		if by_path[path]:
			idx = by_path[path][0]
			if idx not in seen:
				ordered.append(idx)
				seen.add(idx)
	remaining = [idx for path in paths for idx in by_path[path] if idx not in seen]
	remaining.sort(key=lambda idx: priority(graph.node(idx)))
	ordered.extend(remaining)

	chosen: list[int] = []
	used = 0
	reasons: dict[int, str] = {}
	selected_paths: set[str] = set()
	for idx in ordered:
		node = graph.node(idx)
		if node is None:
			continue
		cost = max(1, int(node.tokens))
		if used + cost > budget:
			continue
		chosen.append(idx)
		seen_paths = tuple(path for path in paths if path in node.refs)
		reasons[idx] = "working_set:" + ",".join(seen_paths)
		selected_paths.update(seen_paths)
		used += cost
	return RehydrationPlan(
		paths=paths,
		nodes=tuple(sorted(chosen)),
		tokens=used,
		budget_tokens=budget,
		reasons=reasons,
		selected_paths=tuple(sorted(selected_paths)),
	)


def render_rehydrated_nodes(graph: Graph, plan: RehydrationPlan) -> list[Line]:
	"""Render selected nodes as visible facts, preserving their full text."""
	out: list[Line] = []
	for idx in plan.nodes:
		node = graph.node(idx)
		if node is not None and node.text.strip():
			out.append((f"rehydrate:{idx}", f"#{idx} {' '.join(node.text.split())}"))
	return out


__all__ = [
	"RehydrationPlan",
	"LeaseBook",
	"decay_leases",
	"leased_paths",
	"plan_working_set_rehydration",
	"render_rehydrated_nodes",
	"renew_leases",
	"working_set_paths",
]
