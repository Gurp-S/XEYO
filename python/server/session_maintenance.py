"""Blocking maintenance batch, called from a worker thread."""
def collect_expired(sessions_root, journal_root, ttl):
    from engine.subagent_runner import gc_sidechains
    from memory import journal

    if sessions_root.is_dir():
        for directory in sessions_root.iterdir():
            if directory.is_dir():
                gc_sidechains(directory.name, ttl_seconds=ttl)
    if journal_root.is_dir():
        for wsid in journal.journal_workspace_ids(journal_root):
            journal.gc(wsid, ttl_seconds=ttl)
