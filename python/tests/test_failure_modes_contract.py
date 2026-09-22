from synaptic.failure_modes import Answer, QUESTION_BANK


def test_question_bank_has_unique_ids_and_explicit_kinds():
	ids = [q.id for q in QUESTION_BANK]
	assert len(ids) == len(set(ids))
	assert {q.kind for q in QUESTION_BANK} == {"mechanical", "sample"}


def test_zero_denominator_is_not_a_false_perfect_score():
	a = Answer("X", "demo", "q", "mechanical", 0, 0, "not_applicable")
	assert a.rate is None
	assert a.row()["status"] == "not_applicable"
	assert a.row()["rate"] is None
