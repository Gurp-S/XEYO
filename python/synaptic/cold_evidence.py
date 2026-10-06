"""Archive omitted originals independently of selection/card coverage."""
from synaptic.coldstore import node_handle


def complete_cold_evidence(cold, graph, kept, *, region_end):
    kept = set(kept)
    rows = []
    for node in graph.nodes:
        idx = node.idx
        if idx >= region_end or idx in kept or idx in cold.texts:
            continue
        cold.bind(node_handle(idx), (idx,))
        rows.append((idx, node.text, {"kind": node.kind, "tool": node.tool_name}))
    # Append after existing archive rows to preserve every published Read range.
    cold.put_nodes(rows)
