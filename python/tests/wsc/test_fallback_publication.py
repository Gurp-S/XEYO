"""Fallback and ordinary WSC heads share publication, recovery and identity."""
from copy import deepcopy
from contextlib import contextmanager
import importlib
import json
import os
from pathlib import Path

import pytest

from evals.wsc_unfolded_source_ab import environment as isolated_environment
from memory import wsc_projection, wsc_head_store
from memory.runtime import force_compact, project_for_model
from memory.working import WorkingSnapshot, flush, hydrate
from tests.wsc.test_handoff_validation import recovered_fixture


@contextmanager
def environment(root):
    with isolated_environment(root):
        os.environ['XEYO_WSC'] = '1'
        yield


def prepare(tmp_path):
    rows, _ = recovered_fixture()
    rows += [{'id': f'small-{i}', 'role': 'assistant', 'content': 'receipt observed'} for i in range(20)]
    state = WorkingSnapshot(session_id='fallback-publication')
    wsc_projection._STATE.clear()
    first = force_compact(rows, state, cwd=tmp_path)
    rec = json.loads(wsc_head_store.path_for(state.session_id).read_text(encoding='utf-8'))
    # Actual small-region gain refusal selects legacy fallback, without a
    # mocked projector or manufactured compressed result.
    assert rec['view_path'] == '' and rec['text'] == state.c2_summary_text == first[0]['content']
    assert rec['publication']['objects']
    return rows, state, first, rec


def keep(rows, state, root):
    return project_for_model(rows, state, cwd=root, capacity_managed=True,
                             context_limit=1048576, include_memory_index=False)


def test_real_gain_refusal_remains_one_published_generation_across_restart(tmp_path):
    with environment(tmp_path):
        rows, state, first, rec = prepare(tmp_path)
        original = {Path(name): Path(name).read_bytes() for name in rec['publication']['objects']}
        head_bytes = wsc_head_store.path_for(state.session_id).read_bytes()
        grown = rows + [{'id': 'new-work', 'role': 'assistant', 'content': 'fresh observation'}]
        before = deepcopy(grown)
        assert keep(grown, state, tmp_path)[0] == first[0]
        flush(state.session_id, state)
        wsc_projection._STATE.clear()
        restored = hydrate(state.session_id, source_layout=state.compression_source_layout)
        assert keep(grown, restored, tmp_path)[0] == first[0]
        assert grown == before
        assert wsc_head_store.path_for(state.session_id).read_bytes() == head_bytes
        assert all(p.read_bytes() == body for p, body in original.items())


def test_second_explicit_no_gain_fold_binds_authorized_cursor_and_survives_restart(tmp_path):
    with environment(tmp_path):
        rows, state, first, rec = prepare(tmp_path)
        original = {Path(name): Path(name).read_bytes() for name in rec['publication']['objects']}
        old_cursor = state.compact_cursor
        grown = rows + [{'id': f'extra-{i}', 'role': 'assistant', 'content': 'observation'} for i in range(2)]
        second = force_compact(grown, state, cwd=tmp_path)
        assert state.compact_cursor > old_cursor
        new_rec = json.loads(wsc_head_store.path_for(state.session_id).read_text(encoding='utf-8'))
        assert new_rec['cursor'] == state.compact_cursor
        assert new_rec['region_end'] == rec['region_end']  # No invented absorption.
        assert second[0] == first[0] and new_rec['text'] == rec['text']
        flush(state.session_id, state)
        wsc_projection._STATE.clear()
        restored = hydrate(state.session_id, source_layout=state.compression_source_layout)
        assert keep(grown, restored, tmp_path) == second
        assert all(p.read_bytes() == body for p, body in original.items())


@pytest.mark.parametrize('damage', ['source', 'head', 'cold_missing', 'cold_corrupt', 'layout', 'cwd', 'cursor'])
def test_invalid_fallback_replays_source_without_republication(tmp_path, monkeypatch, damage):
    with environment(tmp_path):
        rows, state, first, rec = prepare(tmp_path)
        if damage == 'source': rows[0]['content'] = 'new specification'
        if damage == 'head': wsc_head_store.path_for(state.session_id).unlink()
        path = Path(next(iter(rec['publication']['objects'])))
        if damage == 'cold_missing': path.unlink()
        if damage == 'cold_corrupt': path.write_bytes(b'corrupted cold evidence')
        if damage == 'layout': state.compression_source_layout = 'append-notes-v1'
        if damage == 'cursor': state.compact_cursor += 1
        cwd = tmp_path / 'different-root' if damage == 'cwd' else tmp_path
        wsc_projection._STATE.clear()
        attempts = []
        def forbidden(*args, **kwargs):
            attempts.append(True)
            raise AssertionError('Ordinary request attempted publication')
        monkeypatch.setattr(wsc_head_store, 'save', forbidden)
        monkeypatch.setattr(importlib.import_module('synaptic.project'), 'project', forbidden)
        assert keep(rows, state, cwd) == rows and not attempts


def test_failed_first_publication_never_installs_unrecoverable_head(tmp_path, monkeypatch):
    with environment(tmp_path):
        rows, _ = recovered_fixture()
        rows += [{'id': f'small-{i}', 'role': 'assistant', 'content': 'receipt observed'} for i in range(20)]
        state = WorkingSnapshot(session_id='failed-fallback')
        wsc_projection._STATE.clear()
        monkeypatch.setattr(wsc_head_store, 'save', lambda *a, **kw: False)
        assert force_compact(rows, state, cwd=tmp_path) == rows
        assert state.c2_summary_text  # Its existence is insufficient authority.
        assert not wsc_head_store.path_for(state.session_id).exists()
        assert keep(rows, state, tmp_path) == rows


def test_disabled_wsc_keeps_legacy_projection_without_wsc_head(tmp_path, monkeypatch):
    with environment(tmp_path):
        monkeypatch.setenv('XEYO_WSC', '0')
        rows, _ = recovered_fixture()
        rows += [{'id': f'small-{i}', 'role': 'assistant', 'content': 'receipt observed'} for i in range(20)]
        state = WorkingSnapshot(session_id='non-wsc-fallback')
        first = force_compact(rows, state, cwd=tmp_path)
        assert first[0]['name'] == 'session_summary'
        assert not wsc_head_store.path_for(state.session_id).exists()


def test_new_archive_literal_keeps_quotes_and_cold_object_discoverable(tmp_path):
    root = tmp_path / "a'quoted-root"
    root.mkdir()
    with environment(root):
        rows, state, first, rec = prepare(root)
        from memory.wsc_publication import validate
        from evals.stale_goal_ab import tool_read
        assert validate(rec)
        for name in rec['publication']['objects']:
            result = tool_read({'file_path': name, 'offset': 1, 'limit': 1000}, root)
            assert not result['is_error'] and 'failed' in result['content']
        assert keep(rows, state, root)[0] == first[0]


@pytest.mark.parametrize('status', ['active', 'paused', 'blocked', 'completed', 'abandoned'])
def test_runtime_goal_facts_use_existing_baseline_shape_without_duplicate_event(tmp_path, monkeypatch, status):
    with environment(tmp_path):
        observed = {'goal_id': 'g1', 'revision': 3, 'status': status, 'text': 'current runtime goal'}
        monkeypatch.setattr('memory.wsc_goal_source.snapshot', lambda *a: observed)
        rows, state, first, rec = prepare(tmp_path)
        assert rec['lifecycle']['goal'] == (observed['text'] if status in {'active', 'paused', 'blocked'} else '')
        assert rec['lifecycle']['goal_id'] == 'g1' and rec['lifecycle']['revision'] == 3
        assert not list((tmp_path / 'home' / 'wsc_goal_events').glob('*.required'))
        assert keep(rows, state, tmp_path)[0] == first[0]
