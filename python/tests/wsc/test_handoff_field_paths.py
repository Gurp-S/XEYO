from copy import deepcopy

import pytest

from memory.wsc_handoff_validation import validate, StateError
from tests.wsc.test_handoff_fact_disposition import prepared


@pytest.mark.parametrize('field', ['context_disposition', 'fact_disposition'])
def test_misplaced_transaction_field_reports_actual_root_path_without_repair(field):
    rows, raw = prepared()
    raw['checkpoint'][field] = {}
    before = deepcopy(raw)
    with pytest.raises(StateError) as caught:
        validate(raw, rows)
    assert caught.value.detail['field'] == 'checkpoint'
    assert caught.value.detail['defined_field_paths'] == [f'$.{field}']
    assert raw == before


def test_unknown_checkpoint_field_has_no_invented_schema_location():
    rows, raw = prepared()
    raw['checkpoint']['invented_slot'] = {}
    with pytest.raises(StateError) as caught:
        validate(raw, rows)
    assert 'defined_field_paths' not in caught.value.detail
