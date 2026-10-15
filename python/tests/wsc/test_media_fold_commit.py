"""The preflight succeeding does not certify later generation publication."""
from copy import deepcopy
import os
import pytest
from evals.wsc_recovered_result_behavior import fixture, actual
from evals.wsc_unfolded_source_ab import environment
from memory.runtime import force_compact
from memory.working import WorkingSnapshot


@pytest.mark.parametrize('native', [False, True])
def test_later_media_publication_failure_preserves_working(tmp_path, monkeypatch, native):
    with environment(tmp_path):
        os.environ.update(XEYO_WSC=str(int(native)), XEYO_WSC_MEDIA_ARCHIVE='1',
                          XEYO_MEDIA_DIR=str(tmp_path / 'media'))
        rows = fixture(media=True)
        working = WorkingSnapshot(session_id='later-media-failure')
        first = force_compact(rows, working, cwd=tmp_path)
        before = deepcopy(working)
        from memory.wsc_head_store import path_for
        head_path = path_for(working.session_id)
        head_bytes = head_path.read_bytes() if head_path.exists() else None
        rows += [actual(media=True)] + [
            {'id': f'after-{i}', 'role': 'assistant', 'content': f'Observed later work {i}. ' * 100}
            for i in range(30)]
        from memory import wsc_media_archive
        original = wsc_media_archive.create
        calls = []
        def fail_after_preflight(*args, **kwargs):
            calls.append(1)
            if len(calls) > 1:
                raise OSError('later media publication failed')
            return original(*args, **kwargs)
        monkeypatch.setattr(wsc_media_archive, 'create', fail_after_preflight)
        try:
            result = force_compact(rows, working, cwd=tmp_path)
        except (OSError, ValueError):
            result = None
        assert len(calls) >= 2
        assert working == before
        if head_bytes is not None:
            assert head_path.read_bytes() == head_bytes
        if result is not None:
            assert result[0] == first[0]
