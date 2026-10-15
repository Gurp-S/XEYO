"""Recovery failure cannot authorize a new emission generation."""
from copy import deepcopy
import json

import pytest

from memory.runtime import force_compact, project_for_model
from memory.working import WorkingSnapshot
from memory import wsc_projection, wsc_head_store


def prepared(monkeypatch, tmp_path):
    monkeypatch.setenv('XEYO_HOME', str(tmp_path/'home'))
    monkeypatch.setenv('XEYO_WSC', '1')
    wsc_projection._STATE.clear()
    rows=[{'id':'spec','role':'user','content':'Current task: verify the receipt.'}]
    rows += [{'id':f'work-{i}','role':'assistant','content':'Observation '+ 'data '*400} for i in range(35)]
    working=WorkingSnapshot(session_id='generation-admission')
    first=force_compact(rows,working,cwd=tmp_path)
    assert working.compact_cursor > 0
    return rows,working,first


@pytest.mark.parametrize('failure',['seal','missing_head','missing_view','layout'])
def test_failed_restore_replays_source_without_publication(monkeypatch,tmp_path,failure):
    rows,working,_first=prepared(monkeypatch,tmp_path)
    head_path=wsc_head_store.path_for(working.session_id)
    old_head=head_path.read_bytes()
    if failure=='seal':rows[0]=dict(rows[0],content='Current task changed.')
    if failure=='missing_head':head_path.unlink()
    if failure=='missing_view':
        from pathlib import Path
        Path(json.loads(old_head)['view_path']).unlink()
    if failure=='layout':
        from memory.wsc_source_layout import APPEND
        working.compression_source_layout=APPEND
    wsc_projection._STATE.clear()
    original=deepcopy(rows)
    cursor=working.compact_cursor
    attempts=[]
    def forbidden(*args,**kwargs):
        attempts.append(True)
        raise RuntimeError('Publication intercepted')
    import importlib
    monkeypatch.setattr(importlib.import_module('synaptic.project'),'project',forbidden)
    emitted=project_for_model(rows,working,cwd=tmp_path,capacity_managed=True,
                              context_limit=1048576,include_memory_index=False)
    assert emitted==rows and rows==original
    assert not attempts
    assert working.compact_cursor==cursor
    assert head_path.read_bytes()==old_head if failure!='missing_head' else not head_path.exists()


def test_verified_restart_reuses_head_but_only_explicit_fold_publishes(monkeypatch,tmp_path):
    rows,working,first=prepared(monkeypatch,tmp_path)
    old_head=wsc_head_store.path_for(working.session_id).read_bytes()
    old_objects={p:p.read_bytes() for p in (tmp_path/'.xeyo_offload').rglob('*') if p.is_file()}
    wsc_projection._STATE.clear()
    grown=rows+[{'id':f'next-{i}','role':'assistant','content':'More observed '+ 'data '*400} for i in range(12)]
    same=project_for_model(grown,working,cwd=tmp_path,capacity_managed=True,context_limit=1048576,include_memory_index=False)
    assert same[0]==first[0]
    assert wsc_head_store.path_for(working.session_id).read_bytes()==old_head
    cursor=working.compact_cursor
    second=force_compact(grown,working,cwd=tmp_path)
    assert working.compact_cursor>cursor
    assert second[0]!=first[0]
    assert all(p.read_bytes()==content for p,content in old_objects.items())


@pytest.mark.parametrize('stage', ['seal', 'junction', 'missing_seal'])
def test_validation_exception_never_emits_unverified_cached_head(monkeypatch, tmp_path, stage):
    rows, working, _first = prepared(monkeypatch, tmp_path)
    head_path = wsc_head_store.path_for(working.session_id)
    old_head = head_path.read_bytes()
    cursor = working.compact_cursor
    calls = []
    original_emit = wsc_projection._emit
    def observed_emit(*args, **kwargs):
        calls.append(True)
        return original_emit(*args, **kwargs)
    def failed(*args, **kwargs):
        raise RuntimeError('Source validation unavailable')
    if stage == 'seal':
        rows[0] = dict(rows[0], content='Current task changed while cache is retained.')
        monkeypatch.setattr(wsc_head_store, 'region_seal', failed)
    elif stage == 'junction':
        monkeypatch.setattr(wsc_projection, '_junction_intact', failed)
    else:
        rows[0] = dict(rows[0], content='Current task changed while cache seal is absent.')
        wsc_projection._STATE[wsc_projection._state_key(working.session_id, tmp_path)].source_seal = ''
    monkeypatch.setattr(wsc_projection, '_emit', observed_emit)
    emitted = wsc_projection.project_c2_messages(rows, working, cwd=tmp_path)
    assert emitted == rows
    assert calls == []
    assert working.compact_cursor == cursor and head_path.read_bytes() == old_head
