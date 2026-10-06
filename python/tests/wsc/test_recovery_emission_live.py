"""Live and restarted WSC retain only the explicitly pinned recovery source."""
import asyncio
import copy
import importlib

from tests.wsc.test_head_store import store
from tests.wsc.test_live_contracts import _W
from tests.wsc._fixtures import synth_session
from engine.compact import keep_tail_cut
from engine.abort import AbortController
from tools.file_read_tool.file_read_tool import FileReadTool
from memory.wsc_projection import _emit


def receipt(path, content, uid='read', error=False, tool='Read'):
    return [{'role':'assistant','content':[{'type':'tool_use','id':uid,'name':tool,'input':{'file_path':str(path)}}]},
            {'role':'user','content':[{'type':'tool_result','tool_use_id':uid,'content':content,'is_error':error}]}]


def test_live_recovery_is_identical_after_restart_and_root_change(store, tmp_path, monkeypatch):
    _, wp = store
    monkeypatch.setenv('XEYO_TOOL_OFFLOAD','0')
    messages=synth_session(turns=22,error_turn=4)
    cut=keep_tail_cut(messages)
    working=_W(cut,sid='recovery-live')
    initial=wp.project_c2_messages(messages,working,cwd=str(tmp_path))
    assert initial is not None
    cached=next(iter(wp._STATE.values()))
    path=cached.view_path
    assert path
    result=asyncio.run(FileReadTool(cwd=str(tmp_path)).execute({'file_path':path,'offset':1,'limit':300},AbortController()))
    assert not result.is_error and 8192<len(result.content)<=100003
    grown=messages+receipt(path,result.content)
    raw=copy.deepcopy(grown)
    emitted=wp.project_c2_messages(grown,working,cwd=str(tmp_path))
    assert emitted[-1]['content'][0]['content']==result.content
    assert emitted[0]==initial[0] and grown==raw
    wp._STATE.clear()
    monkeypatch.setenv('XEYO_OFFLOAD_DIR',str(tmp_path/'changed-root'))
    restarted=wp.project_c2_messages(grown,working,cwd=str(tmp_path))
    assert restarted==emitted
    assert wp._restore_frozen('recovery-live',cut,grown,str(tmp_path)).view_path==path


def test_recovery_identity_and_frozen_boundary_are_conservative(tmp_path, monkeypatch):
    monkeypatch.setenv('XEYO_TOOL_OFFLOAD','0')
    path=tmp_path/'cold.txt'
    content='diagnostic\n'*2000
    for rows,view,frozen in ((receipt(path,content),path,2),
                              (receipt(path,content,error=True),path,0),
                              (receipt(tmp_path/'other.txt',content),path,0),
                              (receipt(path,content,tool='Bash'),path,0),
                              (receipt(path,content),None,0),
                              (receipt(tmp_path,content),'',0)):
        assert _emit('fixed',rows,0,frozen,cwd=str(tmp_path),view_path=view)==_emit('fixed',rows,0,frozen,cwd=str(tmp_path))
    rows=receipt(path,content)
    before=copy.deepcopy(rows)
    assert _emit('fixed',rows,0,0,cwd=str(tmp_path),view_path=path)[-1]['content'][0]['content']==content
    assert rows==before


def test_old_store_without_source_identity_restores_head_conservatively(store, tmp_path):
    hs,wp=store
    messages=[{'role':'user','content':'old request'}, {'role':'assistant','content':'old response'}]
    hs.save('legacy',text='old head',cwd=str(tmp_path),cursor=2,region_end=2,messages=messages)
    restored=wp._restore_frozen('legacy',2,messages,str(tmp_path))
    assert restored and restored.head=='old head' and not restored.view_path
