"""Public origins for omitted PIN evidence, independent of body size."""
from dataclasses import replace
from synaptic.coldstore import node_group_handle


def bind_short_pin_sources(pins, seeds, graph, *, region_end, inline_max_tokens):
    groups = {}
    for idx in seeds.pin_nodes:
        node = graph.node(idx)
        if node and node.is_error and node.error_sig:
            groups.setdefault(node.error_sig, []).append(idx)
    errors = list(groups.items())
    result = []
    for pin in pins:
        sources = ()
        if pin.key.startswith('unresolved:'):
            ordinal = int(pin.key.partition(':')[2])
            if ordinal < len(errors):
                signature, members = errors[ordinal]
                label = signature if len(members) == 1 else f'{signature}（×{len(members)}）'
                if pin.text == label:
                    sources = tuple(idx for idx in members if idx < region_end and graph.node(idx).text not in pin.text)
        elif pin.key == 'todo:0' and 0 <= seeds.todo_source < region_end:
            source = graph.node(seeds.todo_source)
            if source and source.text not in pin.text:
                sources = (source.idx,)
        result.append(replace(pin, nodes=sources) if sources else pin)
    return tuple(result)



def complete_pin_sources(pins, previous, handles, cold):
    """Publish earlier missing members while preserving the latest entrance."""
    if previous and previous.full_text:
        covered = handles.recoverable_nodes(previous.full_text)
        pins = tuple(replace(pin, nodes=tuple(idx for idx in pin.nodes[:-1] if idx not in covered) + pin.nodes[-1:])
            if pin.key.startswith('unresolved:') and len(pin.nodes) > 1 else pin for pin in pins)
    for pin in pins:
        if pin.key.startswith('unresolved:') and len(pin.nodes) > 2:
            earlier = pin.nodes[:-1]
            handle = node_group_handle(earlier)
            cold.bind(handle, earlier)
            handles.handle_nodes[handle] = earlier
    return pins
