"""Opt-in at-rest references; original event payloads remain snapshot-bound."""
from copy import deepcopy
from .contracts import require

MODE='native_source_refs_v1'


def project(rows,mode):
    if mode=='context_source_refs_v1':
        from .context_projection import project as project_context
        return project_context(rows)
    require(mode==MODE,'view_source_projection_unsupported')
    result=[]
    for row in rows:
        value=deepcopy(row)
        if value['kind']!='message':
            value.pop('payload')
            value['payload_ref']=row['id']
        result.append(value)
    return result


def hydrate(body,source):
    mode=body.get('source_projection')
    if mode is None:
        return body
    if mode=='context_source_refs_v1':
        from .context_projection import hydrate as hydrate_context
        return hydrate_context(body,source)
    require(mode==MODE,'view_source_projection_unsupported')
    known={row['id']:row for row in source}
    result=deepcopy(body)
    for index,row in enumerate(result['sources']):
        if row.get('kind')=='message':
            require(row==known.get(row['id']),'projected_source_binding_changed')
            continue
        require(row.get('payload_ref')==row['id'] and row['id'] in known,'projected_source_missing')
        expected=deepcopy(known[row['id']])
        projected=deepcopy(expected)
        projected.pop('payload')
        projected['payload_ref']=row['id']
        require(row==projected,'projected_source_binding_changed')
        result['sources'][index]=expected
    return result
