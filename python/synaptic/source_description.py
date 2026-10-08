"""Bounded literal source descriptions, without semantic task inference."""


def describe(node):
    first = node.text.split("\n", 1)[0]
    return {"source_kind": node.kind, "first_line": first[:160],
            "first_line_complete": len(first) <= 160}
