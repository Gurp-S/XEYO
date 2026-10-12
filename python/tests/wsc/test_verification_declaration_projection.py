"""Preserve explicit binding IDs separately from resolved execution facts."""
from copy import deepcopy
import json

import pytest

from synaptic.project import project
from tests.wsc._fixtures import msg_asst_use, msg_tool
from tests.wsc.test_task_continuity import receipt, task


@pytest.mark.parametrize('declared', [['verify'], ['verify', 'missing'], ['previous']])
def test_declared_ids_survive_projection_without_inferred_submission_ids(declared):
    rows = receipt('previous', [task()], {'objective': 'recorded task'})
    rows += [msg_asst_use('verify', 'Bash', {'command': 'verify'}),
             msg_tool('verify', 'Bash', 'verification failed', is_error=True)]
    rows += receipt('current', [task()], {'objective': 'recorded task', 'verification_call_ids': declared})
    original = deepcopy(rows)
    output = project(rows, region_end=len(rows))
    state = json.loads(next(pin.text for pin in output.result.hot.pins if pin.key == 'task_checkpoint'))
    assert state['verification_call_ids'] == declared
    assert [value['call_id'] for value in state['verification_receipts']] == [uid for uid in declared if uid != 'missing']
    assert 'current' not in state['verification_call_ids']
    assert '验收调用身份（声明）: ' + json.dumps(declared, ensure_ascii=False, separators=(',', ':')) in output.text
    if 'verify' in declared:
        assert state['verification_receipts'][0]['is_error'] is True
    if 'missing' in declared:
        assert any(value.get('call_id') == 'missing' for value in state['unknown_sources'])
    if declared == ['previous']:
        assert state['verification_receipts'][0]['tool'] == 'TodoWrite'
    assert rows == original
