"""Durable terminal receipts keyed by call id; start evidence is not completion."""
from __future__ import annotations
import hashlib
import json
import time
from engine.execution_facts import enabled
from session.call_trace import trace_path, _trim


def record(session, uid, tool, result=None):
    if not enabled() or not session or not uid:
        return
    path = trace_path(session)
    if path is None:
        return
    try:
        row = {"uid": uid, "name": tool, "phase": "unknown" if result is None else "returned", "ts": time.time()}
        if result is not None:
            text = str(result.content or "")
            row.update(is_error=bool(result.is_error), status=result.status,
                       execution=result.execution_metadata(),
                       content_sha256=hashlib.sha256(text.encode()).hexdigest(),
                       complete=len(text) <= 32000, content=text[:32000])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            import os
            os.fsync(out.fileno())
        _trim(path)
    except Exception:
        pass


def lookup(session, uid):
    if not enabled():
        return None
    path = trace_path(session)
    try:
        rows = path.read_text(encoding="utf-8").splitlines()
    except (OSError, AttributeError):
        return None
    for raw in reversed(rows):
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if row.get("uid") == uid and row.get("phase") in {"returned", "unknown"}:
            if row["phase"] == "returned" and row.get("complete"):
                if hashlib.sha256(row.get("content", "").encode()).hexdigest() != row.get("content_sha256"):
                    return None
            return row
    return None
