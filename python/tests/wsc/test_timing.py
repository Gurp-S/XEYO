"""Stage timing is diagnostic only and must not affect WSC output."""

from __future__ import annotations

from synaptic.metrics import determinism_digest
from synaptic.project import project
from synaptic.types import WscParams
from wsc._fixtures import synth_session


def test_project_exposes_stage_timings_without_changing_digest():
	msgs = synth_session(turns=8, error_turn=3)
	a = project(msgs, region_end=len(msgs), params=WscParams())
	b = project(msgs, region_end=len(msgs), params=WscParams())
	assert determinism_digest(a.result) == determinism_digest(b.result)
	assert {
		"graph",
		"file_state",
		"seeds",
		"select",
		"select_plan",
		"select_cards",
		"coldstore",
		"assemble",
		"total",
	} <= set(
		a.result.stage_ms
	)
	assert all(value >= 0 for value in a.result.stage_ms.values())


def test_default_project_does_not_build_soft_dag():
	from synaptic.types import EDGE_ERR, EDGE_FILE, EDGE_SEQ, EDGE_USE

	proj = project(
		synth_session(turns=6, error_turn=3),
		region_end=10_000,
		params=WscParams(),
	)
	kinds = {edge.kind for edge in proj.graph.edges}
	assert EDGE_USE in kinds
	assert not ({EDGE_SEQ, EDGE_FILE, EDGE_ERR} & kinds)


def test_soft_dag_remains_explicit_offline_comparison():
	from synaptic.types import EDGE_ERR, EDGE_FILE, EDGE_SEQ, EDGE_USE

	proj = project(
		synth_session(turns=6, error_turn=3),
		region_end=10_000,
		params=WscParams(soft_dag=True),
	)
	kinds = {edge.kind for edge in proj.graph.edges}
	assert {EDGE_SEQ, EDGE_FILE, EDGE_ERR, EDGE_USE} <= kinds
