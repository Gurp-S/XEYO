"""Read transport must reject changed owned bytes before image conversion."""
import io
from pathlib import Path

from PIL import Image
import hashlib
import pytest
from evals.wsc_recovered_result_behavior import actual
from memory.wsc_media_archive import ENV, create
from tools.file_read_tool.file_read_tool import FileReadTool, ReadInput


def test_read_ab_rejects_valid_but_replaced_image(monkeypatch, tmp_path):
    monkeypatch.setenv('XEYO_MEDIA_DIR', str(tmp_path / 'media'))
    monkeypatch.setenv(ENV, '1')
    catalog = create([actual(media=True)], 1, cwd=tmp_path, session='read')
    path = Path(catalog['records'][0]['image_path'])
    tool = FileReadTool(cwd=str(tmp_path))
    inp = ReadInput(file_path=str(path))
    good = tool._execute_image(str(path), inp)
    assert not good.is_error and len(good.images) == 1
    replacement = io.BytesIO()
    Image.new('RGB', (200, 200), 'red').save(replacement, format='PNG')
    path.write_bytes(replacement.getvalue())
    monkeypatch.setenv(ENV, '0')
    old = tool._execute_image(str(path), inp)
    assert not old.is_error and len(old.images) == 1
    monkeypatch.setenv(ENV, '1')
    rejected = tool._execute_image(str(path), inp)
    assert rejected.is_error and not rejected.images
    assert rejected.content == 'stale_media_archive: content digest mismatch'
    assert path.read_bytes() == replacement.getvalue()


def test_unowned_digest_named_image_keeps_normal_read(monkeypatch, tmp_path):
    monkeypatch.setenv('XEYO_MEDIA_DIR', str(tmp_path / 'owned'))
    monkeypatch.setenv(ENV, '1')
    path = tmp_path / ('0' * 64 + '.png')
    Image.new('RGB', (20, 20), 'blue').save(path)
    result = FileReadTool(cwd=str(tmp_path))._execute_image(str(path), ReadInput(file_path=str(path)))
    assert not result.is_error and result.images


def test_requested_identity_survives_relative_path_and_redirect(monkeypatch, tmp_path):
    from media_store import MediaError
    from memory.wsc_media_integrity import verify_read
    monkeypatch.setenv('XEYO_MEDIA_DIR', str(tmp_path / 'media'))
    monkeypatch.setenv(ENV, '1')
    raw = b'original'
    requested = Path('media') / (hashlib.sha256(raw).hexdigest() + '.png')
    verify_read(raw, str(requested), cwd=tmp_path)
    # Even if path expansion/redirect returned another valid asset's bytes,
    # admission is against the requested digest, not the resolved filename.
    with pytest.raises(MediaError, match='content digest mismatch'):
        verify_read(b'other asset', str(requested), cwd=tmp_path)
