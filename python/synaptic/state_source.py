"""Deterministic state-note emission exclusion for an append source.

This changes selection metadata only. Node indices/text remain intact for cold
recovery. Caller owns the source-layout contract and resets incompatible heads.
No mutable process/session state is held here.
"""
from dataclasses import replace

from synaptic.types import KIND_OTHER


def exclude_state_notes(graph, messages):
    notes = frozenset(i for i, row in enumerate(messages) if row.get("note_key"))
    if not notes:
        return graph, notes
    graph = replace(graph, file_index={path: tuple(i for i in indices if i not in notes)
                                      for path, indices in graph.file_index.items()
                                      if any(i not in notes for i in indices)}, nodes=tuple(
        replace(node, kind=KIND_OTHER, refs=(), symbols=()) if node.idx in notes else node
        for node in graph.nodes
    ))
    return graph, notes
