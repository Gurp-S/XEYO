"""Literal protected facts, with an origin entrance when excerpted."""
from synaptic.coldstore import node_group_handle
from synaptic.handles import renderer_or_default
from synaptic.types import Pin


def render_pin(pin: Pin, *, handles=None) -> str:
    text = pin.text
    if pin.key == "card_archive":
        from synaptic.card_surface import render
        return render(pin, renderer_or_default(handles))
    if pin.key == "task_checkpoint":
        import json
        from synaptic.task_handoff import render
        return render(json.loads(text), pin.nodes, renderer_or_default(handles))
    if pin.key in {"failure_archive", "constraint_candidates"}:
        origin = renderer_or_default(handles).expression(node_group_handle(pin.nodes))
        return f"{pin.label}: {text} {origin}"
    if pin.suppress_excerpt:
        text = f"失败回执（{len(pin.nodes)}个来源，诊断摘录未内联）"
    if pin.key.startswith(("unresolved:", "denial:")) and len(pin.nodes) > 1:
        renderer = renderer_or_default(handles)
        latest = pin.nodes[-1]
        current = renderer.expression(node_group_handle((latest,)))
        earlier = renderer.expression(node_group_handle(pin.nodes[:-1]))
        return f"{pin.label}: {text} source=#{latest} {current} earlier={earlier}"
    if pin.nodes and (pin.key.startswith(("unresolved:", "denial:")) or pin.key == "todo:0"):
        origin = renderer_or_default(handles).expression(node_group_handle(pin.nodes))
        return f"{pin.label}: {text} source=#{pin.nodes[0]} {origin}"
    if not pin.nodes or len(text) <= 400:
        return f"{pin.label}: {text}"
    origin = renderer_or_default(handles).expression(node_group_handle(pin.nodes))
    return f"{pin.label}: {text[:399]}… {origin}"
