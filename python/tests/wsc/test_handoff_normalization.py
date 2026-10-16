"""The native parser and every handoff guard consume the same value."""
from copy import deepcopy

import pytest

from memory.wsc_handoff_validation import validate
from tests.wsc.test_task_phase import declaration, sources
from tests.wsc.test_task_continuity import receipt


@pytest.mark.parametrize('field', ['decisions', 'constraints', 'verification_call_ids'])
def test_optional_empty_field_matches_explicit_value_after_prior_commit(field):
    explicit = declaration()
    explicit['checkpoint'][field] = []
    if field in ('decisions', 'constraints'):
        explicit['checkpoint']['phase_state']['fact_scopes'][field] = []
    rows = sources() + receipt('previous', explicit['todos'], explicit['checkpoint'])
    rows[-1]['id'] = 'checkpoint'
    omitted = deepcopy(explicit)
    del omitted['checkpoint'][field]
    before = deepcopy((rows, omitted))
    expected = validate(explicit, rows, require_phase=True)
    actual = validate(omitted, rows, require_phase=True)
    assert actual == expected
    assert (rows, omitted) == before


def test_normalization_does_not_accept_invalid_optional_value():
    raw = declaration()
    raw['checkpoint']['constraints'] = None
    with pytest.raises(ValueError, match='handoff_invalid_state'):
        validate(raw, sources(), require_phase=True)
