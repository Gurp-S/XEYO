"""Committed continuity and published sources for the legacy deterministic fold."""
def render(messages, working, cursor, cwd):
    from synaptic.project import project
    from memory.wsc_projection import production_params, _view_path_for
    path = _view_path_for(str(cwd or ""), working.session_id).with_suffix(".handoff.txt")
    # The newly committed task receipt may be in the protected raw tail.
    # State authority follows the full observed transcript; cursor controls
    # which history is folded, not which declarations are visible.
    projection = project(messages, region_end=cursor,
                         params=production_params(), view_path=path,
                         session=working.session_id)
    from pathlib import Path
    count = len(Path(projection.view_path).read_text(encoding="utf-8").splitlines())
    archive = f"历史存档: Read(file_path='{projection.view_path}', offset=1, limit={min(8, count)}) span=1-{count}"
    return projection.task_handoff_text + "\n" + archive
