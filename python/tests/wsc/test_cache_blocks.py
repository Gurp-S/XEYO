import copy

import pytest

from evals.wsc_cache_blocks import rounded_points, run


def test_partial_blocks_and_minimum_prefix_become_uncached_without_mutation():
    rows = [dict(case="a", shot=0, end=1, prompt=1500, hit=1050, miss=450),
            dict(case="a", shot=1, end=2, prompt=900, hit=899, miss=1)]
    original = copy.deepcopy(rows)
    result = rounded_points(rows, block=128, minimum=1024)
    assert [(r["hit"], r["miss"]) for r in result] == [(1024, 476), (0, 900)]
    assert rows == original
    assert all(r["hit"] + r["miss"] == r["prompt"] for r in result)
    assert rounded_points(rows, block=1, minimum=0) == original


def test_rounding_can_reverse_an_apparent_prefix_gain():
    a = [dict(case="a", shot=0, end=1, prompt=1600, hit=1023, miss=577)]
    b = [dict(case="a", shot=0, end=1, prompt=1650, hit=1073, miss=577)]
    report = run(a, b)
    zero = next(s for s in report["scenarios"] if s["block_tokens"] == 1 and s["minimum_prefix_tokens"] == 0)
    threshold = next(s for s in report["scenarios"] if s["block_tokens"] == 128 and s["minimum_prefix_tokens"] == 1024)
    at30 = lambda s: next(r["aggregate_saving_pct"] for r in s["price_scenarios"] if r["miss_hit_price_ratio"] == 30)
    assert at30(zero) < 0
    assert at30(threshold) > 0


@pytest.mark.parametrize("block,minimum", [(0,0), (128,-1), (1.5,0)])
def test_invalid_scenario_is_rejected(block, minimum):
    with pytest.raises(ValueError):
        rounded_points([], block=block, minimum=minimum)
