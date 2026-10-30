"""Explicit reference projection. Controls and original source rows stay intact."""
from copy import deepcopy
from .contracts import digest,require
from .control_sources import is_control_source

MODE='context_source_refs_v1'


def project(rows):
    result=[]
    for row in rows:
        if row['kind']=='message' or is_control_source(row):result.append(deepcopy(row));continue
        result.append(dict(id=row['id'],seq=row['seq'],kind=row['kind'],role=row['role'],
             call_id=row['call_id'],observed_at=row['observed_at'],control=row['control'],
             source_ref=row['id'],source_seal=digest(row),representation='historical_source_reference'))
    return result


def hydrate(body,source):
    known={row['id']:row for row in source};result=deepcopy(body)
    for i,row in enumerate(body['sources']):
        original=known.get(row['id']);require(original is not None,'projected_source_missing')
        require(project([original])[0]==row,'projected_source_binding_changed')
        result['sources'][i]=deepcopy(original)
    return result
