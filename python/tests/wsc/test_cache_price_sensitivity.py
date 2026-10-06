import pytest

from evals.wsc_cache_price_sensitivity import analyze, load_points


def row(case, hit, miss):
    return dict(case=case, shot=0, end=1, prompt=hit+miss, hit=hit, miss=miss)


def test_shorter_prompt_can_be_more_expensive_with_stronger_cache_discount():
    baseline, candidate = row("short", 100, 10), row("short", 80, 12)
    report = analyze([baseline], [candidate])
    assert report["aggregate_interval"] == [1, 10]
    for point in report["matrix"]:
        ratio, realized = point["miss_hit_price_ratio"], point["predicted_prefix_realization"]
        # Independent direct split: only realized hits get cached unit price.
        before = baseline["hit"]*realized + ratio*(baseline["miss"]+baseline["hit"]*(1-realized))
        after = candidate["hit"]*realized + ratio*(candidate["miss"]+candidate["hit"]*(1-realized))
        assert point["aggregate_saving_pct"] == pytest.approx(100*(1-after/before))
        if ratio > 10 and realized == 1:
            assert point["cases_cost_increased"] == ["short"]


def test_partial_cache_realization_reverses_a_high_ratio_gain():
    report = analyze([row("long", 100, 10)], [row("long", 120, 5)])
    assert report["aggregate_interval"] == [4, None]
    at_30 = {p["predicted_prefix_realization"]:p for p in report["matrix"] if p["miss_hit_price_ratio"] == 30}
    assert at_30[1]["aggregate_saving_pct"] > 0
    assert at_30[0]["aggregate_saving_pct"] < 0


def test_mispaired_requests_and_invalid_token_totals_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="pairing"):
        analyze([row("a", 1, 2)], [row("b", 1, 2)])
    path = tmp_path/"points.jsonl"
    path.write_text('{"prompt":9,"hit":1,"miss":2}', encoding="utf-8")
    with pytest.raises(ValueError, match="conserved"):
        load_points(path)
