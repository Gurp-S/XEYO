"""Opt-in card source index; task facts remain in their existing channels."""
import hashlib
import json
import os

from synaptic.coldstore import node_handle
from synaptic.chunked_recovery import PREFIX as CHUNK_PREFIX
from synaptic.task_checkpoint import enabled as continuity_enabled
from synaptic.types import Pin

ENV = "XEYO_WSC_CARD_INDEX_ONLY"
PREFIX = "head://card-source-index-"


def eligible(pins):
    if not continuity_enabled() or os.environ.get(ENV, "").strip().lower() not in {"1", "true", "yes", "on"}:
        return False
    for pin in pins:
        if pin.key == "task_checkpoint":
            state = json.loads(pin.text)
            return bool(state.get("context_observed") or state.get("terminal_task"))
    return False


def prepare(cold, cards, pins, aliases):
    if not cards or not eligible(pins):
        return None
    _, ranges = cold.render_text_view()
    records = [{"format": "card_source_index", "cards": len(cards),
                "sources": len({index for card in cards for index in card.nodes})}]
    for card in cards:
        records.append({"card_id": card.card_id, "source_count": len(card.nodes)})
        records.extend({"card_id": card.card_id, "source": index} for index in card.nodes)
    for index in sorted({index for card in cards for index in card.nodes}):
        origin = aliases.get(node_handle(index), node_handle(index))
        if origin not in ranges or index not in cold.texts:
            return None  # Keep existing cards if a complete source is unavailable.
        records.append({"source": index, "view_lines": list(ranges[origin]),
            "encoding": "json_chunks" if origin.startswith(CHUNK_PREFIX) else "original_lf",
            "source_sha256": hashlib.sha256(cold.texts[index].encode("utf-8")).hexdigest()})
    body = "\n".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) for record in records)
    handle = PREFIX + hashlib.sha256(body.encode("utf-8")).hexdigest()
    cold.put_snapshot(handle, body)
    # Reading this index returns identities and locations, not original bodies.
    return Pin("card_archive", "历史折叠来源索引", json.dumps({"handle": handle,
        "cards": len(cards), "sources": records[0]["sources"]}, separators=(",", ":")))


def render(pin, handles):
    record = json.loads(pin.text)
    return f"历史折叠来源索引: cards={record['cards']} sources={record['sources']} " + handles.expression(record["handle"])
