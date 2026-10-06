"""Inline claims must preserve task-significant whitespace, not just words."""
import ast

from synaptic.assemble import render_main
from synaptic.graph import build_graph
from synaptic.types import WscParams


def test_inline_python_fragment_can_still_be_parsed_for_continuation():
    source = "if ready:\n    action()\nelse:\n    fallback()"
    graph = build_graph([{"role": "assistant", "content": source}])
    assert graph.node(0).tokens <= 48
    text = render_main(graph, (0,), WscParams(), pin_nodes=frozenset())[0][1]
    retained = text.split(" ", 1)[1]
    ast.parse(retained)
    assert retained == source


def test_inline_blank_lines_and_indentation_are_not_silently_lost():
    source = "def answer():\n\n    return 42\n"
    graph = build_graph([{"role": "assistant", "content": source}])
    text = render_main(graph, (0,), WscParams(), pin_nodes=frozenset())[0][1]
    assert graph.node(0).text in text
    assert "\n\n    return" in text
