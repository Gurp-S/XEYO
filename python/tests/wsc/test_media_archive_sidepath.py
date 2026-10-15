"""Exact assets, source positions, immutable publication and corrupt rejection."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import pytest
from evals.wsc_recovered_result_behavior import actual
from memory.wsc_media_archive import ENV, create


def setup(monkeypatch, tmp_path):
    monkeypatch.setenv('XEYO_MEDIA_DIR', str(tmp_path / 'owned-media'))
    monkeypatch.setenv(ENV, '1')
    return [actual(media=True)]


def test_default_off_has_no_publication(monkeypatch, tmp_path):
    monkeypatch.delenv(ENV, raising=False)
    assert create([actual(media=True)], 1, cwd=tmp_path, session='archive') is None
    assert not (tmp_path / '.xeyo_offload').exists()


def test_owned_asset_exact_and_catalog_idempotent(monkeypatch, tmp_path):
    rows = setup(monkeypatch, tmp_path)
    before = deepcopy(rows)
    output = create(rows, 1, cwd=tmp_path, session='archive')
    record = output['records'][0]
    url = rows[0]['content'][0]['content'][1]['image_url']['url']
    expected = base64.b64decode(url.split(';base64,')[1])
    assert Path(record['image_path']).read_bytes() == expected
    assert record['source_message_id'] == 'actual-pending' and record['declared_call_id'] == 'pending'
    assert record['content_path'] == '$.content[0].content[1]'
    saved = Path(output['path']).read_bytes()
    again = create(rows, 1, cwd=tmp_path, session='archive')
    assert again['path'] == output['path'] and Path(output['path']).read_bytes() == saved
    assert json.loads(saved)['sha256'] == record['sha256'] and rows == before
    from memory.wsc_head_store import region_seal
    assert json.loads(saved)['source_seal'] == region_seal(rows, 1)


def test_corrupt_existing_asset_is_not_replaced(monkeypatch, tmp_path):
    rows = setup(monkeypatch, tmp_path)
    output = create(rows, 1, cwd=tmp_path, session='archive')
    path = Path(output['records'][0]['image_path'])
    path.write_bytes(b'test-owned corruption')
    with pytest.raises(ValueError, match='stale_media_archive'):
        create(rows, 1, cwd=tmp_path, session='archive')
    assert path.read_bytes() == b'test-owned corruption'


def test_remote_reference_is_not_downloaded_and_tool_input_is_not_observed(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    image = {'type': 'image_url', 'image_url': {'url': 'https://invalid.example/source.png'}}
    rows = [{'id': 'remote', 'role': 'user', 'content': [image]},
            {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 'proposed', 'input': image}]}]
    output = create(rows, 2, cwd=tmp_path, session='archive')
    assert output['count'] == 1 and output['records'][0]['availability'] == 'reference_only'


@pytest.mark.parametrize('boundary', [-1, True, 2])
def test_invalid_source_boundary_publishes_nothing(monkeypatch, tmp_path, boundary):
    rows = setup(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match='invalid_media_archive_boundary'):
        create(rows, boundary, cwd=tmp_path, session='archive')
    assert not (tmp_path / '.xeyo_offload').exists()
