"""Protect current path facts and archive a head only at an actual rebase."""
from synaptic.visible_paths import missing_paths
from synaptic.read_plan import prepare_view
from synaptic.group_recovery import recovery_renderer

def protect_paths(fresh,paths):
    visible='\n'.join(f'{header} {line}' for header,line in fresh)
    absent=missing_paths(tuple(dict.fromkeys(paths)),visible)
    return tuple(fresh)+tuple(('[PATHS]',path) for path in absent if path)

def finish_rebase(first,*,cold,pending,view_path,view_ref,persist,aliases,assembler,args,kwargs):
    if not first[1] or pending is None:
        return first
    handle,text=pending
    cold.put_snapshot(handle,text)
    ranges,lengths=prepare_view(cold,view_path,persist)
    renderer=recovery_renderer(cold,view_ref,ranges,lengths,aliases)
    second=assembler(*args,**dict(kwargs,handles=renderer))
    assert second[1]==first[1], 'archive changed the rebase decision'
    return second
