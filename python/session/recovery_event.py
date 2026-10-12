"""Derived recovery receipts have an identity, but no durability until saved."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from msgtypes.message import Message, tool_result_message


def receipt(origin: Message, session_id: str, uid: str, name: str,
            content: str, *, is_error: bool,
            execution: dict[str, Any] | None = None, outcome_unknown: bool = False) -> Message:
    from session.transcript_blobs import message_fields

    if outcome_unknown:
        from session.recovery_result_chain import observation
        bound = observation(origin, uid)
        if bound is not None:
            execution = {**(execution or {}), "complete": False, "recovery_observation": bound}
    message = tool_result_message(uid, name, content, is_error=is_error,
                                  execution=execution)
    fields = message_fields(message)
    fields.pop("id")
    identity = json.dumps([session_id, origin.id, fields], ensure_ascii=False,
                          sort_keys=True, separators=(",", ":"))
    message.id = "recovered-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
    # In-memory provenance only; serializers and model messages omit it.
    setattr(message, "_transcript_pending", True)
    return message


def registration(messages: Sequence[Message]) -> tuple[set[str], int]:
    known: set[str] = set()
    cursor = len(messages)
    for index, message in enumerate(messages):
        if getattr(message, "_transcript_pending", False):
            cursor = min(cursor, index)
        elif message.id:
            known.add(message.id)
    return known, cursor
