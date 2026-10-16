"""MCP discovery is atomic; schema budgets control exposure, never validation."""
from copy import deepcopy
from collections.abc import Mapping
import json


def complete_schema(schema: object) -> object:
    # Manager admission hides oversized tools; gateway describe retains their
    # full contract, including annotations, enum data, refs and property names.
    return deepcopy(schema)


def describe_payload(payload: dict) -> str:
    # Explicit deferred discovery must return valid complete JSON. Truncating it
    # recreates the same lost-constraint bug as degrading the static schema.
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def list_all_tools(request, *, timeout: float, max_pages: int = 128) -> list[dict]:
    params: dict = {}
    cursors: set[str] = set()
    tools: list[dict] = []
    for _ in range(max_pages):
        page = request("tools/list", params, timeout=timeout)
        if not isinstance(page, Mapping) or not isinstance(page.get("tools"), list):
            raise ValueError("invalid tools/list page")
        batch = page["tools"]
        if any(not isinstance(t, dict) or not isinstance(t.get("name"), str)
               or not t["name"].strip() for t in batch):
            raise ValueError("invalid tools/list tool")
        tools.extend(batch)
        cursor = page.get("nextCursor")
        if cursor is None or cursor == "":
            return tools
        if not isinstance(cursor, str) or cursor in cursors:
            raise ValueError("invalid or repeated tools/list cursor")
        cursors.add(cursor)
        params = {"cursor": cursor}
    raise ValueError("tools/list page limit exceeded")
