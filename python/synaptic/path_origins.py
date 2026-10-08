"""Declared command paths use the graph's own canonical representatives."""
from synaptic.textutil import command_paths, normalize_path, is_noise_path


def declared_paths(node, graph):
    result = set((*node.arg_paths, *node.scope_paths))
    # Result nodes already carry scope_paths. Unfinished uses still declare
    # their command targets; they cannot wait for a future result to be visible.
    named = command_paths({"command": node.command}) if node.command else ()
    for raw in named:
        path = normalize_path(raw)
        if is_noise_path(path):
            continue
        matches = [p for p in node.refs if p == path or path.endswith("/" + p) or p.endswith("/" + path)]
        if matches:
            result.update(matches)
        else:
            result.add(path)
    return tuple(sorted(result))


def origin(graph, path, region_end):
    """Index provenance is not filesystem existence or proof of an operation."""
    for node in graph.nodes[:region_end]:
        if path in node.arg_paths:
            return "tool_argument"
    return "command_mention"
