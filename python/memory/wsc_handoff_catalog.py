"""Bounded identity pages over an immutable handoff transcript."""
from collections import Counter
import json

from synaptic.task_fact_sources import source_text
from synaptic.textutil import tool_use_blocks, tool_result_blocks

NAME = "HandoffCatalog"
INITIAL_RECORDS = 32
INITIAL_BYTES = 16_000
PAGE_BYTES = 24_000


def schema():
    return {"name": NAME, "description": "Returns source identities, roles, character counts and invocation identities from this handoff transcript. Optional literal text query and role filter. No task actions.",
        "input_schema": {"type": "object", "properties": {
            "start": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 16},
            "role": {"type": "string", "enum": ["user", "human", "assistant", "tool", "system"]},
            "query": {"type": "string", "minLength": 1, "maxLength": 256}},
            "required": ["start", "limit"], "additionalProperties": False}}


class Catalog:
    def __init__(self, sources):
        self.sources = sources
        identities = [str(row.get("message_id") or row.get("id")) for row in sources
                      if row.get("message_id") or row.get("id")]
        counts = Counter(identities)
        self.unique_ids = [uid for uid in dict.fromkeys(identities) if counts[uid] == 1]
        calls, results = {}, {}
        self.records = []
        for index, row in enumerate(sources):
            identity = row.get("message_id") or row.get("id")
            record = {"source": index, "message_id": identity, "role": row.get("role")}
            if identity: record["identity_unique"] = counts[str(identity)] == 1
            text = source_text(row)
            if text is not None: record["text_characters"] = len(text)
            use_ids, result_ids = [], []
            for use in tool_use_blocks(row):
                uid = use.get("id")
                if isinstance(uid, str) and uid:
                    calls.setdefault(uid, []).append(index)
                    use_ids.append(uid)
            for result in tool_result_blocks(row):
                uid = result.get("tool_use_id")
                if isinstance(uid, str) and uid:
                    results.setdefault(uid, []).append((index, result))
                    result_ids.append(uid)
            if use_ids: record["tool_call_ids"] = use_ids
            if result_ids: record["tool_result_call_ids"] = result_ids
            self.records.append(record)
        self.verification_ids = []
        for uid, origins in calls.items():
            receipts = results.get(uid, [])
            if len(origins) != 1 or len(receipts) != 1 or origins[0] >= receipts[0][0]: continue
            execution = receipts[0][1].get("execution") or {}
            if not isinstance(execution, dict) or execution.get("complete") is False or execution.get("status") == "cancelled": continue
            self.verification_ids.append(uid)
        eligible = set(self.verification_ids)
        from memory.wsc_handoff_facts import committed_facts
        declarations = committed_facts(sources)
        for record in self.records:
            if str(record["message_id"]) in declarations:
                record["committed_task_fields"] = declarations[str(record["message_id"])]
            observed = [uid for uid in record.get("tool_result_call_ids", []) if uid in eligible]
            if observed: record["verification_call_ids"] = observed

    def initial(self):
        if len(self.records) <= INITIAL_RECORDS:
            order = list(range(len(self.records)))
        else:
            from synaptic.todo_snapshot import latest_todo_snapshot
            snapshot = latest_todo_snapshot(self.sources)
            order = []
            if snapshot.observed and snapshot.checkpoint is not None and snapshot.active_count:
                order.append(snapshot.checkpoint_source)
                bound = set(snapshot.checkpoint["context_message_ids"])
                order.extend(i for i, record in enumerate(self.records) if str(record["message_id"]) in bound)
            order.extend(range(max(0, len(self.records) - INITIAL_RECORDS), len(self.records)))
        selected, size = [], 0
        for index in dict.fromkeys(order):
            record = self.records[index]
            if not record["message_id"]: continue
            encoded = len(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            if size + encoded > INITIAL_BYTES or len(selected) == INITIAL_RECORDS: continue
            selected.append(record)
            size += encoded
        return selected

    def read(self, arguments):
        if not isinstance(arguments, dict) or not {"start", "limit"} <= set(arguments) or set(arguments) - {"start", "limit", "role", "query"}:
            raise ValueError("handoff_catalog_invalid_arguments")
        start, limit = arguments["start"], arguments["limit"]
        role, query = arguments.get("role"), arguments.get("query")
        if (type(start) is not int or start < 0 or type(limit) is not int or not 1 <= limit <= 16
                or ("role" in arguments and role not in {"user", "human", "assistant", "tool", "system"})
                or ("query" in arguments and (not isinstance(query, str) or not 1 <= len(query) <= 256))):
            raise ValueError("handoff_catalog_invalid_arguments")
        selected, size, cursor = [], 0, min(start, len(self.records))
        while cursor < len(self.records) and len(selected) < limit:
            record, row = self.records[cursor], self.sources[cursor]
            if role is not None and row.get("role") != role:
                cursor += 1
                continue
            if query is not None:
                text = source_text(row)
                if text is None: text = json.dumps(row.get("content"), ensure_ascii=False)
                if query not in text:
                    cursor += 1
                    continue
            encoded = len(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            if size + encoded > PAGE_BYTES:
                if not selected: raise ValueError("handoff_catalog_record_too_large")
                break
            selected.append(record)
            size += encoded
            cursor += 1
        return {"total_sources": len(self.records), "records": selected,
                "next_source": cursor if cursor < len(self.records) else None}
