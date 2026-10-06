"""Evaluation-only append-only state source and note emission exclusion.

All note originals remain addressable in the graph/cold layer. Current state is
selected at emission by StateLifecycle, independently of compression indices.
This module is never imported by the production engine.
"""
from contextlib import ExitStack
from dataclasses import replace
import importlib
from unittest.mock import patch

from session.message_store import MessageStore
from synaptic.types import KIND_OTHER


class AppendStateStore(MessageStore):
    def as_api_messages(self):
        # Use production pairing cleanup, but not its latest-note source filter.
        super().as_api_messages()
        rows = []
        self._api_items = list(self.items)
        for item in self.items:
            row = {"role": item.role, "content": item.content}
            if item.role == "tool":
                if item.tool_call_id:
                    row["tool_call_id"] = item.tool_call_id
                if item.name:
                    row["name"] = item.name
            elif item.note_key:
                row.update(note_key=item.note_key, note_fp=item.note_fp)
            rows.append(row)
        return rows


def select_note_rows(rows, current):
    """Select complete current state after generation; retain every ordinary row."""
    last = {row["note_key"]: i for i, row in enumerate(rows) if row.get("note_key")}
    return [row for i, row in enumerate(rows) if not row.get("note_key") or
            (last[row["note_key"]] == i and row["note_key"] in current and
             row.get("role") == current[row["note_key"]]["role"] and
             row.get("content") == current[row["note_key"]]["content"] and
             ("note_fp" not in current[row["note_key"]] or
              row.get("note_fp", "") == current[row["note_key"]]["note_fp"]))]


def install_note_exclusion() -> ExitStack:
    """Patch one isolated evaluation process; caller closes returned stack."""
    module = importlib.import_module("synaptic.project")
    original_graph = module.build_graph
    original_freshness = module.analyze_freshness
    blocked = {}

    def build_graph(messages, **kwargs):
        graph = original_graph(messages, **kwargs)
        # Graph nodes are message-indexed. Keep source text and indices intact,
        # exclude note paths from file-state selection and notes from user seeds.
        notes = frozenset(i for i, row in enumerate(messages) if row.get("note_key"))
        graph = replace(graph, file_index={path: tuple(i for i in indices if i not in notes)
                                         for path, indices in graph.file_index.items()
                                         if any(i not in notes for i in indices)}, nodes=tuple(
            replace(node, kind=KIND_OTHER, refs=(), symbols=()) if node.idx in notes else node
            for node in graph.nodes
        ))
        blocked[id(graph)] = notes
        return graph

    def freshness(graph, **kwargs):
        result = original_freshness(graph, **kwargs)
        notes = blocked.pop(id(graph), frozenset())
        return replace(result, superseded=result.superseded | notes)

    stack = ExitStack()
    stack.enter_context(patch.object(module, "build_graph", build_graph))
    stack.enter_context(patch.object(module, "analyze_freshness", freshness))
    return stack
