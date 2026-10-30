"""Persistent query ledger: cumulative query budgets must survive a restart.

`SourceAccess` keeps its counters in memory and zeroes them in `reset()`, so a
new process starts from zero and the "cumulative" ceiling is only per-process.
The ledger records spend against a stable key (session + boundary) so the
ceiling holds across restarts.
"""
from .contracts import require

TABLE = """CREATE TABLE IF NOT EXISTS wsc_query_ledger_v1(
key TEXT PRIMARY KEY,calls INTEGER NOT NULL,rows INTEGER NOT NULL,text_bytes INTEGER NOT NULL)"""


def spend(db, key, *, calls=0, rows=0, text_bytes=0):
    db.execute(TABLE)
    db.execute(
        "INSERT INTO wsc_query_ledger_v1(key,calls,rows,text_bytes) VALUES(?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET calls=calls+excluded.calls,rows=rows+excluded.rows,"
        "text_bytes=text_bytes+excluded.text_bytes", (key, calls, rows, text_bytes))
    return totals(db, key)


def totals(db, key):
    db.execute(TABLE)
    row = db.execute("SELECT calls,rows,text_bytes FROM wsc_query_ledger_v1 WHERE key=?",
                     (key,)).fetchone()
    return dict(calls=0, rows=0, text_bytes=0) if row is None else dict(
        calls=row[0], rows=row[1], text_bytes=row[2])


def enforce(db, key, limits):
    seen = totals(db, key)
    require(seen['calls'] <= limits.max_calls, 'source_access_call_budget_exhausted')
    require(seen['rows'] <= limits.max_rows_total, 'source_access_row_budget_exhausted')
    require(seen['text_bytes'] <= limits.max_text_bytes_total, 'source_access_text_budget_exhausted')
    return seen
