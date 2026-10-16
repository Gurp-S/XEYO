"""Write-through updates touch only the published source file."""
import json
import os


def upsert_file(domain, path, table):
    from memory import memindex
    from memory.memdir import split_frontmatter
    from memory.governance import MemorySchemaError

    if table not in ("notes", "rollouts"):
        raise ValueError(table)
    try:
        with path.open("rb") as handle:
            raw = handle.read()
            stat = os.fstat(handle.fileno())
        decoded = raw.decode("utf-8")
        # Match Path.read_text's universal newline handling for cached payloads;
        # the promoted signature still hashes the original decoded file bytes.
        text = decoded.replace("\r\n", "\n").replace("\r", "\n")
        if table == "notes":
            fm, body = split_frontmatter(text)
            fm_json = json.dumps(fm, ensure_ascii=False, sort_keys=True)
            hashed = memindex._sync_table.__module__ == "memory.memindex_sig_shadow"
            sha = memindex._sha(decoded if hashed else fm_json + body)
            payload = (domain, path.name, stat.st_mtime, stat.st_size, sha, fm_json, body)
        else:
            payload = (domain, path.name, stat.st_mtime, stat.st_size, text)
    except (OSError, UnicodeError, MemorySchemaError):
        with memindex._connect(domain) as conn:
            conn.execute(f"DELETE FROM {table} WHERE domain=? AND path=?", (domain, path.name))
        return
    with memindex._connect(domain) as conn:
        if table == "notes":
            conn.execute("INSERT OR REPLACE INTO notes(domain,path,mtime,size,sha,fm_json,body) VALUES (?,?,?,?,?,?,?)", payload)
        else:
            conn.execute("INSERT OR REPLACE INTO rollouts(domain,path,mtime,size,raw) VALUES (?,?,?,?,?)", payload)
