from synaptic.eval_stats import paired_delta, wilson_interval


def test_wilson_known_positive_and_empty_control():
	row = wilson_interval(10, 10)
	assert row["rate"] == 1.0
	assert 0.7 < row["low"] < 1.0
	assert row["high"] == 1.0
	assert wilson_interval(0, 0)["rate"] is None
	assert wilson_interval(0, 0)["low"] is None


def test_paired_delta_known_positive_and_negative():
	row = paired_delta([False, True, False, True], [True, True, False, False])
	assert row["n"] == 4
	assert row["delta"] == 0.0
	assert row["candidate_wins"] == 1
	assert row["baseline_wins"] == 1
