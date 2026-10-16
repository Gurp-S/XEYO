"""Deletion and transcript delivery share the same per-recipient OS lock domain."""
from contextlib import contextmanager

from engine.agent_identity import AgentBusy, AgentLease


def delivery_lease(store, session, recipient):
    return AgentLease(store.directory / "delivery-leases", session, recipient)


@contextmanager
def deletion_guard(store, session, recipients):
    leases = []
    try:
        for recipient in sorted(set(recipients) | {"parent"}):
            try:
                leases.append(delivery_lease(store, session, recipient).acquire())
            except AgentBusy as exc:
                raise AgentBusy("delivery_busy") from exc
        yield
    finally:
        for lease in reversed(leases):
            lease.release()
