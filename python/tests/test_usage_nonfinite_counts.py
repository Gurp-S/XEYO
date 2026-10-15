import pytest
from usage import combine, ledger, pricing


@pytest.mark.parametrize('value', [float('inf'), float('-inf'), float('nan')])
@pytest.mark.parametrize('module', [combine, ledger, pricing])
def test_nonfinite_usage_cannot_crash_normalization(module, value):
    assert module._as_int(value) == 0


def test_split_usage_keeps_valid_dimensions_when_one_is_invalid():
    assert pricing.split_usage({'prompt_tokens': float('inf'), 'completion_tokens': 7}) == (0, 0, 7)


@pytest.mark.parametrize('value,expected', [('42', 42), (12, 12), (None, 0), ('bad', 0)])
def test_existing_count_semantics(value, expected):
    assert pricing._as_int(value) == expected
