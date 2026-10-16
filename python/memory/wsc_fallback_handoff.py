"""Committed continuity and published sources for the legacy deterministic fold."""
def compose(messages, legacy, handoff):
    """One task-state representation per newly published fallback generation."""
    from synaptic.todo_snapshot import latest_todo_snapshot
    if handoff and latest_todo_snapshot(messages).observed:
        return handoff
    return legacy + ("\n\n" + handoff if handoff else "")


def render(messages, working, cursor, cwd):
    from synaptic.project import project
    from memory.wsc_projection import production_params, _view_path_for
    path = _view_path_for(str(cwd or ""), working.session_id).with_suffix(".handoff.txt")
    if path.exists():
        # A new explicit fold publishes a new immutable generation; never
        # overwrite the Read source that backs an earlier model response.
        path = path.with_name(f"{path.stem}.{int(cursor)}{path.suffix}")
    # The newly committed task receipt may be in the protected raw tail.
    # State authority follows the full observed transcript; cursor controls
    # which history is folded, not which declarations are visible.
    projection = project(messages, region_end=cursor,
                         params=production_params(), view_path=path,
                         session=working.session_id, media_cwd=cwd,
                         media_source_layout=getattr(working, 'compression_source_layout', 'latest-notes-v1'))
    from pathlib import Path
    count = len(Path(projection.view_path).read_text(encoding="utf-8").splitlines())
    working.c2_evidence_paths = projection.evidence_paths
    archive = f"历史存档: Read(file_path={Path(projection.view_path).resolve().as_posix()!r}, offset=1, limit={min(8, count)}) span=1-{count}"
    return projection.fallback_continuity_text + "\n" + archive
