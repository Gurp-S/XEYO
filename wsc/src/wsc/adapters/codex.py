"""Explicit native checkpoint conversion, not an in-process Codex compaction hook."""
from copy import deepcopy

from ..contracts import Event, digest, encode, identifier, require


def public_text(item: dict) -> str | None:
    kind = item.get("type")
    if kind == "message":
        content = item.get("content")
        require(isinstance(content, list), "native_message_content_invalid")
        parts = [part["text"] for part in content if isinstance(part, dict)
                 and part.get("type") in {"input_text", "output_text"} and isinstance(part.get("text"), str)]
        return "\n".join(parts) if parts else None
    if kind in {"function_call", "custom_tool_call"}:
        return encode({k: item[k] for k in ("name", "arguments", "input") if k in item})
    if kind in {"function_call_output", "custom_tool_call_output"}:
        output = item.get("output")
        return output if isinstance(output, str) else encode(output)
    return None


class CodexCheckpointAdapter:
    @staticmethod
    def capabilities() -> dict:
        return {"adapter": "codex_checkpoint_v1", "boundary": "explicit_checkpoint_recovery",
                "transparent_native_compaction": False, "opaque_prefix": "archive_only",
                "installation": "host_callback_required", "token_capacity": "host_checked"}

    def import_items(self, items: list[dict], *, thread_id: str, start_ordinal=0,
                     observed_at=None) -> list[Event]:
        identifier(thread_id)
        require(type(start_ordinal) is int and start_ordinal >= 0, "native_ordinal_invalid")
        require(isinstance(items, list), "native_items_invalid")
        require(observed_at is None or (isinstance(observed_at, (list, tuple)) and
                len(observed_at) == len(items) and all(t is None or isinstance(t, str) for t in observed_at)),
                "native_observation_times_invalid")
        result = []
        for ordinal, item in enumerate(items, start_ordinal):
            require(isinstance(item, dict), "native_item_invalid")
            native_type = item.get("type")
            role, call_id = None, None
            if native_type == "message":
                role = item.get("role")
                require(role in {"system", "developer", "user", "assistant"}, "native_role_unsupported")
                kind = "message"
            elif native_type in {"function_call", "custom_tool_call"}:
                kind, call_id = "call", identifier(item.get("call_id"))
            elif native_type in {"function_call_output", "custom_tool_call_output"}:
                kind, call_id = "result", identifier(item.get("call_id"))
            elif native_type in {"reasoning", "compaction"}:
                kind = "opaque"
            else:
                require(False, "native_item_type_unsupported")
            result.append(Event(id=f"native:{thread_id}:{ordinal}:{digest(item)}", kind=kind,
                                payload=deepcopy(item), role=role, call_id=call_id,
                                text=public_text(item),
                                observed_at=observed_at[ordinal-start_ordinal] if observed_at is not None else None,
                                control=role in {"user", "system", "developer"}))
        return result

    def render(self, body, sources, cut, locators, *, source_index, understanding_index):
        # The tail remains byte-value equivalent. In-flight calls stay in the host;
        # this checkpoint adapter deliberately refuses to interrupt their protocol.
        pending = set()
        for row in sources:
            if row["kind"] == "call":
                pending.add(row["call_id"])
            elif row["kind"] == "result":
                pending.discard(row["call_id"])
        require(not pending, "checkpoint_requires_idle_tools")
        items, excerpts = [], []
        body = body or {"sources": [], "understandings": [], "clues": []}
        for row in body["sources"]:
            if row["kind"] == "message":
                items.append(deepcopy(row["payload"]))
            else:
                # Historical calls are facts, never newly issued native tool calls.
                excerpts.append({"source_id": row["id"], "kind": row["kind"],
                                 "text": row["text"], "observed_at": row["observed_at"],
                                 "source": locators[row["id"]]})
        def locations(keys):
            return [{"source_id": key, "path": locators[key].get("readable_path", locators[key]["file_path"]),
                     "sha256": locators[key].get("readable_sha256", locators[key]["sha256"]),
                     "observed_at": locators[key]["observed_at"]}
                    for key in keys]
        facts = {"kind": "working_state", "understandings": [
            {"ref": r["ref"], "kind": r["kind"], "text": r["text"], "scope": r["scope"],
             "sources": locations(r["sources"])} for r in body["understandings"]],
            "clues": [{"text": c["text"], "sources": locations(c["sources"])} for c in body["clues"]],
            "historical_excerpts": excerpts,
            "archive": {"sources": source_index, "understandings": understanding_index}}
        if body.get("excerpts"):
            facts["observations"] = [{"key": e["key"], "text": e["text"],
                "historical_locator": e["historical_locator"],
                "source": body["excerpt_locators"][e["key"]],
                **({"current_reference": e["current_reference"]} if "current_reference" in e else {})}
                for e in body["excerpts"]]
        items.append({"type": "message", "role": "assistant", "phase": "commentary",
                      "content": [{"type": "output_text", "text": encode(facts)}]})
        items.extend(deepcopy(row["payload"]) for row in sources if row["seq"] > cut)
        return items
