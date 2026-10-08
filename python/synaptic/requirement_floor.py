"""Retired experiment: all historical user bodies are not active task state."""


def enabled():
    return False


def render(graph, region_end, user_nodes, handles):
    from synaptic.coldstore import node_handle
    from synaptic.handles import renderer_or_default
    hr = renderer_or_default(handles)
    return [(f"req:{i}", f"#{i} 历史用户原话 {hr.expression(node_handle(i))}\n"
             + graph.node(i).text)
            for i in user_nodes if i < region_end and graph.node(i)]
