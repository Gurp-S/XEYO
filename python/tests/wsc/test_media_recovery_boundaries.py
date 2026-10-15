"""Fresh-process mismatched generation recovery and cold object refusal."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from engine.abort import AbortController
from evals.wsc_recovered_result_behavior import fixture, actual
from evals.wsc_unfolded_source_ab import environment
from memory.runtime import force_compact
from memory.working import WorkingSnapshot, _to_dict
from memory.wsc_media_archive import create
from tools.file_read_tool.file_read_tool import FileReadTool


@pytest.mark.parametrize('native', [False, True])
def test_fresh_process_new_head_old_working_keeps_media_source(tmp_path, native):
    with environment(tmp_path):
        os.environ.update(XEYO_WSC=str(int(native)), XEYO_WSC_MEDIA_ARCHIVE='1',
                          XEYO_MEDIA_DIR=str(tmp_path / 'media'))
        rows = fixture(media=True)
        working = WorkingSnapshot(session_id='media-crash-gap')
        force_compact(rows, working, cwd=tmp_path)
        durable_old = _to_dict(working)
        old_cursor = working.compact_cursor
        rows += [actual(media=True)] + [
            {'id': f'after-{i}', 'role': 'assistant', 'content': f'Observed later work {i}. ' * 100}
            for i in range(30)]
        force_compact(rows, deepcopy(working), cwd=tmp_path)
        data = tmp_path / 'restart-input.json'
        data.write_text(json.dumps({'rows': rows, 'working': durable_old}), encoding='utf-8')
        original_files = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
        program = '''
import json, sys
from pathlib import Path
from memory.working import _from_dict
from memory.runtime import apply_c2_messages
p = Path(sys.argv[1])
d = json.loads(p.read_text(encoding='utf-8'))
w = _from_dict(d['working'], 'media-crash-gap')
before = w.compact_cursor
out = apply_c2_messages(d['rows'], w, cwd=p.parent)
image = d['rows'][27]['content'][0]['content'][1]['image_url']['url']
assert image in json.dumps(out)
assert w.compact_cursor == before
if sys.argv[2] == 'native':
    assert out == d['rows']
print(json.dumps({'cursor': before, 'media_source_retained': True, 'rebuilt': False}))
'''
        result = subprocess.run([sys.executable, '-B', '-c', program, str(data),
                                 'native' if native else 'fallback'],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)['cursor'] == old_cursor
        assert all(path.read_bytes() == content for path, content in original_files.items())


@pytest.mark.parametrize('damage', ['catalog', 'asset', 'missing_asset'])
def test_read_rejects_damaged_cold_media_without_repair(tmp_path, damage):
    with environment(tmp_path):
        os.environ.update(XEYO_WSC_MEDIA_ARCHIVE='1', XEYO_MEDIA_DIR=str(tmp_path / 'media'))
        catalog = create([actual(media=True)], 1, cwd=tmp_path, session='damage')
        path = Path(catalog['path'] if damage == 'catalog' else catalog['records'][0]['image_path'])
        if damage == 'missing_asset':
            path.unlink()
        else:
            path.write_bytes(b'damaged test object')
        tool = FileReadTool(cwd=str(tmp_path))
        tool.set_vision_enabled(True)
        result = asyncio.run(tool.execute({'file_path': str(path)}, AbortController()))
        assert result.is_error and not result.images
        if damage == 'missing_asset':
            assert not path.exists()
        else:
            assert path.read_bytes() == b'damaged test object'
