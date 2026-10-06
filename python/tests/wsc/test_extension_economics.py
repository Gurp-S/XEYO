"""回归：WSC 候选代价、活冷层隔离、实际发射一致性与执行层拒绝。"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from memory import wsc_extension_economics as econ
from memory import wsc_projection as wp
from memory.runtime import try_extend_c2
from memory.simulator.params import Params
from memory.working import WorkingSnapshot
from synaptic.coldstore import ColdStore


@pytest.fixture(autouse=True)
def _state(monkeypatch):
	wp._STATE.clear()
	monkeypatch.setenv("XEYO_WSC", "1")
	monkeypatch.setenv("XEYO_WSC_EXTENSION_ECONOMICS", "0")
	monkeypatch.setenv("XEYO_WSC_HEAD_STORE", "0")
	monkeypatch.setenv("XEYO_WSC_FROZEN_HEAD", "1")
	monkeypatch.setenv("XEYO_WSC_CADENCE_ABSORB", "0")
	monkeypatch.setenv("XEYO_WSC_OFFLINE", "1")
	yield
	wp._STATE.clear()


def _messages(n=40):
	return [{"role": "user", "content": f"Request {i}: " + "x" * 6000} for i in range(n)]


def test_compare_counts_tool_arguments_and_preserves_negative_gain():
	short = [{"role": "assistant", "content": [{
		"type": "tool_use", "id": "c", "name": "Bash", "input": {"command": "ls"},
	}]}]
	long = copy.deepcopy(short)
	long[0]["content"][0]["input"]["command"] = "长参数" * 100
	pair = econ.compare(short, long)
	assert pair.saved_tokens < 0
	assert pair.transition_tokens > 0
	assert econ.compare(long, long).transition_tokens == 0


def test_preview_layout_equals_written_view_without_writing(tmp_path):
	cs = ColdStore(session="s")
	cs.put_nodes([(3, "first\r\nlast\n", {}), (1, "earlier index", {})])
	text, ranges = cs.render_text_view()
	path = tmp_path / "view.txt"
	assert not path.exists()
	assert cs.write_text_view(path) == ranges
	assert path.read_text(encoding="utf-8") == text


@pytest.mark.parametrize("layout", ["latest-notes-v1", "append-notes-v1"])
def test_measure_is_the_actual_fold_without_changing_live_cold_view(tmp_path, layout):
	messages = _messages()
	messages.insert(1, {"role": "user", "content": "obsolete machine state src/old.py", "note_key": "world_state", "note_fp": "old"})
	w = WorkingSnapshot(session_id="s_economics", compact_cursor=8, c1_frozen_until=8)
	w.compression_source_layout = layout
	assert wp.project_c2_messages(messages[:12], w, cwd=str(tmp_path))
	cached = wp._STATE[wp._state_key(w.session_id, str(tmp_path))]
	view = wp._view_path_for(str(tmp_path), w.session_id)
	view_before = view.read_bytes()
	cold_before = cached.cold.to_json()
	head_before = cached.head
	working_before = copy.deepcopy(w)
	keep = wp._emit(cached.head, messages, cached.region_end, 8, cwd=str(tmp_path))
	pair = econ.measure(messages, w, 36, cwd=str(tmp_path))
	assert pair is not None
	assert view.read_bytes() == view_before
	assert cached.cold.to_json() == cold_before
	assert cached.head == head_before
	assert w == working_before
	w.compact_cursor = w.c1_frozen_until = 36
	fold = wp.project_c2_messages(messages, w, cwd=str(tmp_path))
	assert pair == econ.compare(keep, fold)


@pytest.mark.parametrize("pair,approved", [
	(econ.ExtensionEconomics(2000, 1900, 100), False),
	(econ.ExtensionEconomics(2000, 2500, 100), False),
	(econ.ExtensionEconomics(2000, 1000, 900), True),
])
def test_extension_uses_measured_cost_even_when_c2_proxy_approves(monkeypatch, pair, approved):
	monkeypatch.setenv("XEYO_WSC_EXTENSION_ECONOMICS", "1")
	monkeypatch.setattr(econ, "measure", lambda *a, **k: pair)
	w = WorkingSnapshot(session_id="s_gate", compact_cursor=8, c1_frozen_until=8)
	w.turns_since_c2 = 999
	account = {}
	assert try_extend_c2(w, _messages(), 36, Params(), account=account) is approved
	assert account["economics_basis"] == econ.BASIS
	assert account["projection_saved_tokens"] == pair.saved_tokens
	assert w.compact_cursor == (36 if approved else 8)


def test_disabled_and_force_paths_never_measure(monkeypatch):
	def fail(*a, **k):
		raise AssertionError("unexpected candidate measurement")
	monkeypatch.setattr(econ, "measure", fail)
	for enabled, forced in (("0", False), ("1", True)):
		monkeypatch.setenv("XEYO_WSC_EXTENSION_ECONOMICS", enabled)
		w = WorkingSnapshot(compact_cursor=8, c1_frozen_until=8)
		w.turns_since_c2 = 999
		assert try_extend_c2(w, _messages(), 36, Params(), force=forced)


def test_measure_declines_stale_head_after_history_rollback(tmp_path):
	messages = _messages()
	w = WorkingSnapshot(session_id="s_rollback", compact_cursor=8, c1_frozen_until=8)
	assert wp.project_c2_messages(messages, w, cwd=str(tmp_path))
	assert econ.measure(messages[:36], w, 32, cwd=str(tmp_path)) is None


def test_measure_declines_same_length_frozen_source_revision(tmp_path):
	messages = _messages()
	w = WorkingSnapshot(session_id="s_revision", compact_cursor=8, c1_frozen_until=8)
	assert wp.project_c2_messages(messages[:12], w, cwd=str(tmp_path))
	changed = copy.deepcopy(messages)
	changed[0]["content"] = "replacement request"
	assert econ.measure(changed, w, 36, cwd=str(tmp_path)) is None


@pytest.mark.parametrize("restored", [False, True])
def test_measure_preserves_recovery_receipt_and_restored_generation(tmp_path, monkeypatch, restored):
	from tests.wsc.test_recovery_emission_live import receipt
	monkeypatch.setenv("XEYO_TOOL_OFFLOAD", "0")
	messages = _messages(22)
	w = WorkingSnapshot(session_id="s_receipt", compact_cursor=8, c1_frozen_until=8)
	assert wp.project_c2_messages(messages[:12], w, cwd=str(tmp_path))
	cached = wp._STATE[wp._state_key(w.session_id, str(tmp_path))]
	path = cached.view_path
	view_before = Path(path).read_bytes()
	if restored:
		# A disk-restored head has no in-memory cold layout or AssemblyState.
		cached.prev = cached.cold = None
	content = "complete recovery evidence\n" * 1000
	grown = messages + receipt(path, content)
	keep = wp._emit(cached.head, grown, cached.region_end, 8, cwd=str(tmp_path), view_path=path)
	assert keep[-1]["content"][0]["content"] == content
	pair = econ.measure(grown, w, 18, cwd=str(tmp_path))
	assert Path(path).read_bytes() == view_before
	w.compact_cursor = w.c1_frozen_until = 18
	fold = wp.project_c2_messages(grown, w, cwd=str(tmp_path))
	assert pair == econ.compare(keep, fold)
	if restored:
		assert wp._STATE[wp._state_key(w.session_id, str(tmp_path))].view_path != path
		assert Path(path).read_bytes() == view_before
