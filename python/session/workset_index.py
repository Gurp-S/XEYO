"""Rebuildable session query over the original journal; filter before paging."""
from memory import journal
from engine.session_presence import session_tree_root


def query(workspace_id, session_id, *, limit=20, before_seq=None, path_prefix=None,
          since_ts=None, agent_id=None, workspace_root=None, operation_id=None):
    rows = journal._read_rows(journal._changes_path(workspace_id))
    root = session_tree_root(session_id)
    visible = []
    for row in rows:
        sid = str((row.get("metadata") or {}).get("session_id") or "")
        # Unknown legacy owners are not evidence of current-session edits.
        if root and session_tree_root(sid) != root:
            continue
        if before_seq is not None and row.get("seq", 0) >= before_seq:
            continue
        if since_ts is not None and row.get("ts", 0) < since_ts:
            continue
        if agent_id and row.get("agent_id") != agent_id:
            continue
        if operation_id and (row.get("metadata") or {}).get("operation_id") != operation_id:
            continue
        if path_prefix and not journal._path_matches_prefix(row.get("path", ""), path_prefix, workspace_root=workspace_root):
            continue
        visible.append(row)
    visible.sort(key=lambda row: row.get("seq", 0))
    page = visible[-limit:]
    return {"records": page, "returned": len(page), "total_matching_before_cursor": len(visible),
            "next_before_seq": page[0]["seq"] if len(visible) > len(page) else None,
            "source": "retained_workspace_journal", "history_complete": False,
            "session_scope": "session_tree" if root else "workspace_unbound",
            "unknown_owner_records": sum(not (row.get("metadata") or {}).get("session_id") for row in rows)}
