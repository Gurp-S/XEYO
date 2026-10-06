"""Contract checks for the bounded complete-member snapshot candidate."""
import asyncio
import importlib
import runpy
from dataclasses import replace
from pathlib import Path
import pytest

from engine.abort import AbortController
from synaptic.assemble import AssemblyState
from synaptic.coldstore import ColdStore,head_handle
from synaptic.handles import HandleRenderer,_READ_RE
from synaptic.read_plan import line_prefix
from synaptic.types import WscParams
from tools.file_read_tool.file_read_tool import FileReadTool

from synaptic import group_recovery as recovery
from synaptic.project import project
packet={name:getattr(recovery,name) for name in ('verified_layout','put_packet')}
ns={'aliases':{'required_origins':recovery.required_origins,'complete_members':recovery.complete_members},'make_project':lambda: project}

def renderer(cold, aliases):
    raw,ranges=cold.render_text_view()
    return recovery.recovery_renderer(cold,'cold.txt',ranges,line_prefix(raw),aliases)

def example():
    cold=ColdStore()
    cold.put_nodes([(1,'one',{}),(2,'noise'*8000,{}),(3,'three',{}),(4,'four',{})])
    cold.bind('branch://a',(1,4))
    cold.bind('branch://b',(1,3,4))
    return cold

def test_shared_expression_uses_complete_member_union_and_retains_old_coverage():
    cold=example()
    raw,ranges=cold.render_text_view()
    old=HandleRenderer(style='read',path='cold.txt',node_ranges=ranges,handle_nodes=dict(cold.handles),line_lengths=line_prefix(raw))
    old_ref=old.expression('branch://a')
    assert old_ref==old.expression('branch://b')
    required=ns['aliases']['required_origins'](old)
    members=ns['aliases']['complete_members']((1,4),old_ref,required)
    assert set(members)=={1,3,4}
    key=packet['put_packet'](cold,members)
    new=renderer(cold,{'branch://a':key,'branch://b':key})
    ref=new.expression('branch://a')
    assert ref==new.expression('branch://b')
    assert new.extract_nodes(ref)==new.recoverable_nodes(ref)=={1,3,4}
    assert new.extract_nodes(old_ref)=={1,2,3,4}
    assert cold.expand('branch://a')==('one','four')

def test_copy_boundaries_are_verified_even_when_body_contains_node_labels():
    cold=example()
    cold.texts[1]='one\n#node 4\nnot a partition'
    key=packet['put_packet'](cold,(1,4))
    new=renderer(cold,{'branch://a':key})
    restored=ColdStore.from_json(cold.to_json())
    assert packet['verified_layout'](restored)==packet['verified_layout'](cold)
    assert new.extract_nodes(new.expression('branch://a'))=={1,4}

def test_partial_read_is_not_whole_packet_coverage():
    cold=example()
    key=packet['put_packet'](cold,(1,4))
    new=renderer(cold,{'branch://a':key})
    first,last=new.span(key)
    partial=f"Read(file_path='cold.txt', offset={first}, limit=2)"
    assert new.extract_nodes(partial) <= {1}
    assert 4 not in new.extract_nodes(partial)
    assert new.extract_nodes(new.expression(key))=={1,4}

@pytest.mark.parametrize('damage',['body','binding'])
def test_corrupt_packet_is_not_accepted_as_complete(damage):
    cold=example()
    key=packet['put_packet'](cold,(1,4))
    if damage=='body':
        cold.snapshots[key]+='corrupt'
    else:
        cold.handles[key]=(1,3,4)
    with pytest.raises(ValueError):
        packet['verified_layout'](cold)

def test_packet_bound_falls_back_without_deleting_raw_or_old_ranges():
    cold=example()
    before=cold.render_text_view()
    assert packet['put_packet'](cold,(1,4),max_bytes=1) is None
    cold.texts[1]='x'*100004
    assert packet['put_packet'](cold,(1,4)) is None
    assert not cold.snapshots
    assert cold.texts[2]=='noise'*8000

def prior():
    old='[WORKING SET] old-state'
    return old,AssemblyState(level='Medium+',mode='closure',full_text=old,journal=(('[WORKING SET]','old-state'),))

def test_archive_only_at_real_rebase_and_old_ranges_stay_fixed(tmp_path):
    old,state=prior()
    function=ns['make_project']()
    cold=example()
    before=cold.render_text_view()[1]
    view=tmp_path/'cold.txt'
    kwargs=dict(region_end=1,prev=state,cold=cold,view_path=view,view_ref=str(view))
    history=[dict(role='user',content='Keep src/api.py API.')]
    first=function(history,params=replace(WscParams(journal_rebase=True,handle_style='read'),journal_growth_tokens=100000),**kwargs)
    assert first.text.startswith(old) and head_handle(old) not in cold.snapshots
    second=function(history,params=replace(WscParams(journal_rebase=True,handle_style='read'),journal_growth_tokens=1),**kwargs)
    assert second.result.rebuilt and cold.snapshots[head_handle(old)]==old
    after=cold.render_text_view()[1]
    assert all(after[h]==span for h,span in before.items())
    raw,ranges=cold.render_text_view()
    ref=recovery.recovery_renderer(cold,str(view),ranges,line_prefix(raw)).expression(head_handle(old))
    assert ref in second.text
    match=_READ_RE.search(ref)
    result=asyncio.run(FileReadTool(cwd=str(tmp_path)).execute(dict(file_path=str(view),offset=int(match.group('offset')),limit=int(match.group('limit'))),AbortController()))
    assert not result.is_error and 'old-state' in result.content
