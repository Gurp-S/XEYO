"""Idempotent attempt accounting; missing receipts remain unknown."""
from dataclasses import asdict
import json

from .contracts import Usage, encode, identifier, require


def begin(db, attempt_id: str, phase: str) -> None:
    identifier(attempt_id)
    identifier(phase)
    require(not db.execute("SELECT 1 FROM usage WHERE id=?", (attempt_id,)).fetchone(),
            "usage_attempt_exists")
    db.execute("INSERT INTO usage VALUES (?,?,?,?)",
               (attempt_id, phase, "pending", encode(asdict(Usage()))))


def finish(db, attempt_id: str, usage: Usage, *, status: str = "completed") -> None:
    require(status in {"completed", "failed"}, "usage_status_invalid")
    data = asdict(usage)
    for key, value in data.items():
        require(value is None or (isinstance(value, (int, float)) and not isinstance(value, bool)
                                  and value >= 0), "usage_value_invalid")
        if key != "elapsed_ms":
            require(value is None or type(value) is int, "usage_token_count_invalid")
    encoded = encode(data)
    old = db.execute("SELECT status,data FROM usage WHERE id=?", (attempt_id,)).fetchone()
    require(old is not None, "usage_attempt_missing")
    if old[0] != "pending":
        require(old[0] == status and old[1] == encoded, "usage_receipt_conflict")
        return
    db.execute("UPDATE usage SET status=?,data=? WHERE id=?", (status, encoded, attempt_id))


def summary(db) -> dict:
    attempts = [dict(row) for row in db.execute("SELECT * FROM usage ORDER BY rowid")]
    for row in attempts:
        row["data"] = json.loads(row["data"])
    fields = asdict(Usage())
    return {"coverage": "recorded_attempts_only", "attempts": attempts, "totals": {
        key: {"known_sum": sum(r["data"][key] or 0 for r in attempts),
              "unknown_attempts": sum(r["data"][key] is None for r in attempts)} for key in fields},
        "monetary_cost": None}
