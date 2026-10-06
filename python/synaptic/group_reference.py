"""Stable ordered membership references using the existing cold handle map."""
import hashlib

from synaptic.coldstore import node_group_handle


def group_reference(nodes: tuple[int, ...]) -> str:
    direct = node_group_handle(nodes)
    fingerprint = "branch://set-" + hashlib.sha256(
        ",".join(str(idx) for idx in nodes).encode("ascii")
    ).hexdigest()
    return min((direct, fingerprint), key=len)
