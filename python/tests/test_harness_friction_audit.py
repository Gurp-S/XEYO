"""Regression evidence for isolated candidates; no production gate is enabled."""
import pytest

from evals.harness_friction_audit import run


@pytest.fixture(scope="module")
def audit():
    from engine.harness_policy import DEFAULTS
    from evals.harness_friction_audit import environment
    # This historical audit characterizes the pre-repair route explicitly.
    with environment({name: "0" for name in DEFAULTS}):
        return run()


@pytest.mark.parametrize("route", ["direct", "store"])
def test_deletion_becomes_visible_but_is_not_prevented(audit, route):
    a, b = (audit["cases"][f"legal_semantic_deletion/{route}"][x] for x in ("A", "B"))
    assert a["accepted"] and b["accepted"]
    assert not a["model_diff_visible"] and b["model_diff_visible"]
    assert '"ERROR: "' not in b["after"]
    assert a["after"] == b["after"]


@pytest.mark.parametrize("route", ["direct", "store"])
@pytest.mark.parametrize("case", ["syntax_error", "compile_only_error"])
def test_candidate_rejects_invalid_python_before_disk_mutation(audit, route, case):
    a, b = (audit["cases"][f"{case}/{route}"][x] for x in ("A", "B"))
    assert a["accepted"] and not a["syntax_valid_after"]
    assert not b["accepted"] and b["disk_unchanged"]
    assert b["syntax_valid_after"] and "SyntaxError" in b["error"]


def test_compile_is_not_a_semantic_or_concurrency_guarantee(audit):
    for route in ("direct", "store"):
        b = audit["cases"][f"undefined_name/{route}"]["B"]
        assert b["accepted"] and b["syntax_valid_after"]
    for variant in ("A", "B"):
        direct = audit["cases"]["external_write_after_validate/direct"][variant]
        store = audit["cases"]["external_write_after_validate/store"][variant]
        assert direct["accepted"] and not direct["disk_unchanged"]
        assert not store["accepted"] and store["disk_unchanged"]


def test_projection_does_not_mutate_transcript(audit):
    for pair in audit["cases"].values():
        for result in pair.values():
            assert result["projection_preserves_transcript"]
            assert result["projection_idempotent"]


def test_presentation_probe_keeps_verdict_and_artifacts(audit):
    result = audit["verdict"]
    assert result["A_verdict_line"] == 4 and result["B_verdict_line"] == 1
    assert result["same_lines"] and result["exit_code"] == 0
