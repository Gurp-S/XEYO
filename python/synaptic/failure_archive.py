"""A recoverable index of compressed failures, distinct from task obligations."""
from synaptic.types import Pin


def compact(pins, checkpoint, graph):
    from synaptic.task_checkpoint import enabled
    if not enabled():
        return pins
    import json
    current = set()
    if checkpoint is not None:
        state = json.loads(checkpoint.text)
        current = {item["source"] for item in state["verification_receipts"]}
    archived, kept = [], []
    count = 0
    for pin in pins:
        if not pin.key.startswith("unresolved:") or current.intersection(pin.nodes):
            kept.append(pin)
            continue
        archived.extend(pin.nodes)
        count += 1
    if not archived:
        return tuple(kept)
    ids = {graph.node(i).tool_use_id for i in archived}
    calls = [node.idx for node in graph.nodes if node.kind == "tool_use" and node.tool_use_id in ids]
    sources = tuple(sorted(set(archived + calls)))
    kept.append(Pin("failure_archive", "折叠区失败回执索引",
        f"executions={len(set(archived))} identities={count} coverage=unknown", nodes=sources))
    return tuple(kept)
