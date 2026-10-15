"""Actual explicit fold entrances, frozen reuse, and prepublication refusal."""
from copy import deepcopy
from pathlib import Path
import pytest

from evals.wsc_recovered_result_behavior import fixture, actual
from evals.wsc_unfolded_source_ab import environment
from memory.runtime import force_compact, apply_c2_messages
from memory.working import WorkingSnapshot
from memory.wsc_projection import _STATE
from tests.wsc._recovery_contract import parse_read_refs


@pytest.mark.parametrize('native', [False, True])
@pytest.mark.parametrize('enabled', [False, True])
def test_explicit_fold_media_entrance_and_frozen_reuse(tmp_path, native, enabled):
    import os
    with environment(tmp_path):
        os.environ.update(XEYO_WSC=str(int(native)), XEYO_WSC_MEDIA_ARCHIVE=str(int(enabled)),
                          XEYO_MEDIA_DIR=str(tmp_path / 'media'))
        rows = fixture(media=True)
        working = WorkingSnapshot(session_id='directory-ab')
        force_compact(rows, working, cwd=tmp_path)
        rows += [actual(media=True)] + [
            {'id': f'after-{i}', 'role': 'assistant', 'content': f'Observed later work {i}. ' * 100}
            for i in range(30)]
        original = deepcopy(rows)
        emitted = force_compact(rows, working, cwd=tmp_path)
        assert working.compact_cursor > 27 and rows == original
        head = emitted[0]['content']
        catalogs = [ref for ref in parse_read_refs(head) if 'media-index' in str(ref)]
        assert bool(catalogs) == enabled
        if enabled:
            import asyncio
            import json
            import base64
            from engine.abort import AbortController
            from tools.file_read_tool.file_read_tool import FileReadTool
            tool = FileReadTool(cwd=str(tmp_path))
            tool.set_vision_enabled(True)
            entry = catalogs[0]
            directory = asyncio.run(tool.execute({'file_path': entry.path,
                'offset': entry.offset, 'limit': entry.limit}, AbortController()))
            assert not directory.is_error
            # Read the immutable advertised object, not a creator-side return.
            records = [json.loads(line) for line in Path(entry.path).read_text(encoding='utf-8').splitlines()]
            record = next(item for item in records if item['source_index'] == 27)
            image = asyncio.run(tool.execute({'file_path': record['image_path']}, AbortController()))
            assert not image.is_error and len(image.images) == 1
            original_url = rows[27]['content'][0]['content'][1]['image_url']['url']
            assert Path(record['image_path']).read_bytes() == base64.b64decode(original_url.split(';base64,')[1])
        snapshot = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
        reused = apply_c2_messages(rows, working, cwd=tmp_path)
        assert reused[0] == emitted[0]
        _STATE.pop(working.session_id, None)
        restored = apply_c2_messages(rows, working, cwd=tmp_path)
        assert restored[0] == emitted[0]
        assert all(path.read_bytes() == data for path, data in snapshot.items())


def test_media_prepublication_failure_does_not_retire_source(tmp_path, monkeypatch):
    import os
    with environment(tmp_path):
        os.environ.update(XEYO_WSC='1', XEYO_WSC_MEDIA_ARCHIVE='1')
        working = WorkingSnapshot(session_id='media-publication-failure')
        before = deepcopy(working)
        def fail(*args, **kwargs):
            raise OSError('media archive publication failed')
        monkeypatch.setattr('memory.wsc_media_archive.create', fail)
        with pytest.raises(OSError, match='publication failed'):
            force_compact(fixture(media=True), working, cwd=tmp_path)
        assert working == before
