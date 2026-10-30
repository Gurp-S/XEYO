"""Exact identity and revision types at the shared understanding write boundary."""
from uuid import uuid4

from .contracts import identifier, require


def write_identity(value):
    if value.id is not None:
        identifier(value.id)
    require(value.expected_revision is None or
            (type(value.expected_revision) is int and value.expected_revision > 0),
            "understanding_revision_invalid")
    return uuid4().hex if value.id is None else value.id
