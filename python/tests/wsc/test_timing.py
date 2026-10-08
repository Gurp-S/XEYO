"""Capacity policy must supersede ordinary economics and old absolute gates."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from memory import runtime
from memory.working import WorkingSnapshot
from memory.wsc_timing import decide, measure


@pytest.mark.parametrize("tokens,action,notice", [
    (20_000, "keep", False), (799_999, "keep", False),
    (800_000, "keep", True), (849_999, "keep", True),
    (850_000, "capacity", True), (1_100_000, "capacity", True)])
def test_million_window_boundaries(tokens, action, notice):
    result = decide(tokens, 1_000_000)
    assert (result.action, result.notify) == (action, notice)


def test_explicit_request_unknown_capacity_and_exact_ratio():
    assert decide(20_000, 1_000_000, model_requested=True).action == "model"
    assert decide(999_999, None).action == "keep"
    assert not decide(999_999, None).notify
    assert decide(85, 101).action == "keep"
    assert decide(86, 101).action == "capacity"
    assert not decide(800_000, 1_000_000, notified=True).notify


def test_measure_rejects_unbound_old_receipt_and_does_not_count_reserve():
    working = SimpleNamespace(compact_cursor=10, last_prompt_tokens=999_999,
        last_projection_manifest={"compact_cursor": 9, "context_receipt_cursor": 9,
                                  "context_receipt_basis": "provider_current_request", "estimated_tokens": 1})
    assert measure([], working, context_limit=1_000_000).action == "keep"
    working.last_projection_manifest.update(compact_cursor=10, context_receipt_cursor=10)
    assert measure([], working, context_limit=1_000_000).action == "capacity"
    working.last_projection_manifest["context_receipt_basis"] = "projected_estimate"
    assert measure([], working, context_limit=1_000_000).action == "keep"


@pytest.mark.parametrize("entry", ["projection", "pressure"])
def test_runtime_20k_does_not_admit_old_absolute_or_economic_gates(monkeypatch, entry):
    monkeypatch.setenv("XEYO_WSC_MODEL_TIMING", "1")
    monkeypatch.setenv("XEYO_C2_PRESSURE_TOKENS", "100")
    monkeypatch.setenv("XEYO_WSC_SOFT_WATERMARK", "100")
    messages = [{"role": "user", "content": "a" * 80_000}]
    original = deepcopy(messages)
    working = WorkingSnapshot()
    working.last_prompt_tokens = 999_999  # Unbound old receipt is not occupancy.
    def forbidden(*args, **kwargs):
        pytest.fail("ordinary fold admitted below 85%")
    monkeypatch.setattr(runtime, "force_compact", forbidden)
    if entry == "projection":
        assert runtime.project_for_model(messages, working, context_limit=1_000_000,
                                         include_memory_index=False) == messages
    else:
        assert not runtime.maybe_force_compact_on_pressure(messages, working, context_limit=1_000_000)
    assert messages == original
    assert working.compact_cursor == working.c1_frozen_until == 0


@pytest.mark.parametrize("entry", ["projection", "pressure"])
def test_runtime_85_percent_uses_force_path(monkeypatch, entry):
    monkeypatch.setenv("XEYO_WSC_MODEL_TIMING", "1")
    messages = [{"role": "user", "content": "a" * 100}]
    working = WorkingSnapshot()
    # Actual current-request overhead is explicitly bound to this generation.
    working.last_prompt_tokens = 850_000
    working.last_projection_manifest = {"compact_cursor": 0, "context_receipt_cursor": 0,
        "context_receipt_basis": "provider_current_request", "estimated_tokens": 1}
    calls = []
    def forced(rows, snapshot, **kwargs):
        calls.append(rows)
        snapshot.compact_cursor = 1
        return [{"role": "user", "content": "new projection"}]
    monkeypatch.setattr(runtime, "force_compact", forced)
    if entry == "projection":
        out = runtime.project_for_model(messages, working, context_limit=1_000_000, include_memory_index=False)
        assert out[0]["content"] == "new projection"
    else:
        assert runtime.maybe_force_compact_on_pressure(messages, working, context_limit=1_000_000)
    assert len(calls) == 1
