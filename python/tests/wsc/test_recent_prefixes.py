import pytest

from evals.wsc_recent_prefixes import RecentPrefixes


def test_recurring_old_prefix_and_bounded_eviction():
    run = RecentPrefixes(2)
    assert run.observe("A"*400)["recent_input_hit"] == 0
    assert run.observe("B"*400)["extra_hit"] == 0
    result = run.observe("A"*400)
    assert result["extra_hit"] == 100
    assert result["best_request_age"] == 2
    run.observe("C"*400)
    result = run.observe("B"*400)
    assert result["recent_input_hit"] == 0
    assert result["retained_inputs"] == 2


def test_append_sequence_gains_nothing_from_older_inputs():
    run = RecentPrefixes(4)
    for i in range(1,8):
        result = run.observe("A"*(400*i))
        assert result["extra_hit"] == 0
        assert result["recent_input_hit"] == 100*(i-1)
    assert len(run.history) == 4


@pytest.mark.parametrize("capacity", [0, 1.5, True])
def test_invalid_capacity(capacity):
    with pytest.raises(ValueError):
        RecentPrefixes(capacity)
