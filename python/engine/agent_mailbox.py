"""Durable, attributed messages delivered at model request boundaries."""
from __future__ import annotations

import asyncio
import hashlib
import json

from engine.agent_identity import current_agent
from engine.agent_run_store import AgentRunStore


def _message(row):
    from msgtypes.message import user_message
    packet = {k: row[k] for k in ("sender", "recipient", "message_id", "kind", "text")}
    mid = "agent-mail-" + hashlib.sha256(
        (row["session"] + "\0" + row["sender"] + "\0" + row["message_id"]).encode()).hexdigest()
    return user_message("[Agent message]\n" + json.dumps(packet, ensure_ascii=False), message_id=mid)


def deliver_sync(messages, session, recipient, attempt=""):
    from engine.agent_delivery_guard import delivery_lease
    mailbox = AgentRunStore()
    lease = delivery_lease(mailbox, session, recipient).acquire()
    try:
        return _deliver_owned(mailbox, messages, session, recipient, attempt)
    finally:
        lease.release()


def _deliver_owned(mailbox, messages, session, recipient, attempt):
    from session.persistence import transcript_path
    from session.record_transcript import record_transcript_sync, flush_transcript
    from engine.subagent_runner import _sidechain_path
    rows = mailbox.claim_messages(session, recipient, attempt=attempt)
    if not rows:
        return 0
    packets = [_message(row) for row in rows]
    present = {m.id for m in messages.items}
    for packet in packets:
        if packet.id not in present:
            messages.append(packet)
            present.add(packet.id)
    path = transcript_path(session) if recipient == "parent" else _sidechain_path(session, recipient)
    # Flush preceding tool messages as well: a mailbox event must not overtake
    # the receiving conversation's in-memory tool_call/tool_result pairs.
    record_transcript_sync(messages.items, session_id=session, path=path,
                           session_persistence_disabled=False)
    flush_transcript(path)
    mailbox.acknowledge(session, recipient, [r["seq"] for r in rows], attempt=attempt)
    return len(rows)


async def deliver(messages):
    from engine.agent_runtime import actor, enabled
    if not enabled():
        return 0
    sid, recipient = actor()
    if not sid:
        return 0
    identity = current_agent.get()
    # Legacy workers outside the managed runtime do not consume the parent's inbox.
    from permissions.policy import in_subagent
    if in_subagent() and identity is None:
        return 0
    from engine.agent_io import owned_io
    return await owned_io(deliver_sync, messages, sid, recipient,
                                    identity.attempt_id if identity else "")
