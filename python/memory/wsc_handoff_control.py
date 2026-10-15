"""Invocation metadata is separate from the task represented by sources.

The factory owns only the isolated call's control carrier. Source provenance,
task meaning, lifecycle, validation and publication have their existing owners.
"""
import json


def legacy_message(identities, source_count):
    # Retained for the exact historical protocol and controlled ablations.
    from memory.wsc_handoff_generation import REQUEST
    return {"role": "user", "content": REQUEST + "\n来源身份=" + json.dumps(identities, ensure_ascii=False)
            + "\n来源总数=" + str(source_count)}


def factual_message(identities, source_count):
    return {"role": "user", "content": "request_kind=task_state_declaration"
            + "\n来源身份=" + json.dumps(identities, ensure_ascii=False)
            + "\n来源总数=" + str(source_count)}


# The candidate's default is unchanged until its controlled quality admission.
message = legacy_message


def legacy_messages(identities, source_count):
    """Keep the historical single-carrier seam for exact controlled ablation."""
    return [message(identities, source_count)]


def split_messages(identities, source_count):
    return [{"role": "system", "content": "request_kind=task_state_declaration"},
            {"role": "user", "content": "来源身份=" + json.dumps(identities, ensure_ascii=False)
             + "\n来源总数=" + str(source_count)}]


messages = legacy_messages
