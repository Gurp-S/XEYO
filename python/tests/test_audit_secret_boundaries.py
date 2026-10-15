import json
import pytest
from audit.redact import redact_text, scrub_audit_fields


@pytest.mark.parametrize('key', ['password', 'Password', 'API_KEY', 'api-key', 'Authorization', 'access_token', 'refresh_token'])
def test_secret_field_masks_value_without_pattern(key):
    assert scrub_audit_fields({key: 'short'})[key] == '***'


def test_depth_limit_does_not_return_uninspected_secret_subtree():
    data = {'password': 'secret-at-depth'}
    for _ in range(20):
        data = {'wrap': data}
    assert 'secret-at-depth' not in json.dumps(scrub_audit_fields({'tool_input': data}))


def test_github_underscore_token_is_redacted():
    fake = 'ghp_' + 'abcXYZ0123' * 4
    assert fake not in redact_text('curl ' + fake)


def test_ordinary_metadata_keeps_structure():
    assert scrub_audit_fields({'label': 'ordinary', 'items': [1, 2]}) == {'label': 'ordinary', 'items': [1, 2]}
