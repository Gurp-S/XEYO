"""Durable, append-only goal observations attached to a frozen WSC generation."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from synaptic.textutil import tool_use_blocks, tool_result_blocks


class GoalEventLedgerError(ValueError):
    """A previously emitted generation cannot be reconstructed safely."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _seal(messages):
    return hashlib.sha256(_json(messages).encode("utf-8")).hexdigest()


def _fact(snapshot, *, baseline=False):
    snapshot = snapshot or {}
    return {"goal_id": snapshot.get("goal_id"), "revision": snapshot.get("revision"),
            "status": snapshot.get("status"),
            "text": "" if snapshot.get("status") in {"completed", "abandoned"}
            else str(snapshot.get("goal" if baseline else "text") or "")}


def _closed_pairs(messages):
    pending = set()
    for message in messages:
        for block in tool_use_blocks(message):
            uid = block.get("id")
            if not uid:
                return False
            pending.add(uid)
        for block in tool_result_blocks(message):
            pending.discard(block.get("tool_use_id"))
    return not pending


def path_for(session, cwd, head, base, source_layout):
    home = Path(os.environ.get("XEYO_HOME") or Path.home() / ".xeyo")
    identity = _seal([session, str(cwd), head, base, source_layout])
    return home / "wsc_goal_events" / (identity + ".json")


def _save(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(_json({"version": 1, "events": rows, "events_sha256": _seal(rows)}))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        marker = path.with_suffix(".required")
        try:
            with marker.open("x", encoding="utf-8") as stream:
                stream.write("goal_event_ledger_required\n")
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            pass
    finally:
        Path(temporary).unlink(missing_ok=True)


def augment(messages, base, frozen_attr, *, head, cwd, session, lifecycle, source_layout):
    """Weave persisted observations at their original source positions, before C0/C1.

    Writes complete before emission. No raw transcript or frozen-head byte changes.
    A state observed during an open tool pair waits for a closed pair boundary.
    """
    from synaptic.request_plane import enabled
    if not enabled() or not session:
        return messages, frozen_attr
    from memory.wsc_goal_source import snapshot
    path = path_for(session, cwd, head, base, source_layout)
    rows = []
    if path.with_suffix(".required").exists() and not path.exists():
        raise GoalEventLedgerError("goal_event_state_missing")
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GoalEventLedgerError("goal_event_state_unavailable") from exc
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("events"), list):
            raise GoalEventLedgerError("invalid_goal_event_ledger")
        rows = data["events"]
        if data.get("events_sha256") != _seal(rows):
            raise GoalEventLedgerError("goal_event_digest_mismatch")
        last_anchor = base
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("fact"), dict):
                raise GoalEventLedgerError("invalid_goal_event_row")
            anchor = row.get("anchor")
            if (not isinstance(anchor, int) or anchor < last_anchor or anchor > len(messages)
                    or row.get("source_seal") != _seal(messages[:anchor])):
                raise GoalEventLedgerError("goal_event_source_changed")
            last_anchor = anchor
    try:
        current = _fact(snapshot(str(cwd), session))
    except Exception as exc:
        from memory.wsc_diagnostics import record
        record("goal_event_snapshot", exc, session=session)
        current = rows[-1]["fact"] if rows else _fact(lifecycle, baseline=True)
    prior = rows[-1]["fact"] if rows else _fact(lifecycle, baseline=True)
    if current != prior and _closed_pairs(messages[base:]):
        candidate = [*rows, {"anchor": len(messages), "source_seal": _seal(messages), "fact": current}]
        try:
            _save(path, candidate)
        except Exception as exc:
            from memory.wsc_diagnostics import record
            record("goal_event_save", exc, session=session)
        else:
            rows = candidate
    if not rows:
        return messages, frozen_attr
    emitted = []
    cursor = 0
    for row in rows:
        anchor = row["anchor"]
        emitted.extend(messages[cursor:anchor])
        emitted.append({"role": "assistant", "name": "goal_state",
                        "content": "[BOUND_GOAL_STATE]\n" + _json({**row["fact"],
                            "observed_after_source_messages": anchor})})
        cursor = anchor
    emitted.extend(messages[cursor:])
    return emitted, frozen_attr + sum(row["anchor"] < frozen_attr for row in rows)
