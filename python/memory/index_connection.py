"""Short-lived SQLite connections with explicit ownership and versioned setup."""
import sqlite3


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *exc):
        try:
            return super().__exit__(*exc)
        finally:
            self.close()


def connect(path, schema: str, version: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=2.0, factory=ClosingConnection)
    try:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current < version:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(schema)
            conn.execute("INSERT OR REPLACE INTO meta(k,v) VALUES ('schema_version',?)", (str(version),))
            conn.execute(f"PRAGMA user_version={int(version)}")
            conn.commit()
        return conn
    except BaseException:
        conn.close()
        raise
