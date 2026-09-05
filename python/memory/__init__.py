"""记忆平面（MemoryPlane）门面。主循环只依赖这里。"""

from __future__ import annotations

from memory.governance import MemoryNote
from memory.search import search as search_notes


def search(query: str, *, scope: str, top_k: int = 5) -> list[MemoryNote]:
    """门面：转交 memory.search.search，主循环不直接依赖 search.py"""
    return search_notes(query, scope=scope, top_k=top_k)
