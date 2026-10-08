"""Lossless readable chunks for cold sources with oversized atomic lines."""
import hashlib
import json

from synaptic.coldstore import node_handle
from synaptic.read_budget import MAX_READ_CHARS
from synaptic.task_checkpoint import enabled

PREFIX = "head://source-chunks-"
CHUNK_CHARACTERS = 1024


def snapshot_handle(members, body):
    return PREFIX + hashlib.sha256(json.dumps([list(members), body], ensure_ascii=False).encode()).hexdigest()


def encoded_members(cold, members):
    records = []
    for index in members:
        original = cold.texts[index]
        checksum = hashlib.sha256(original.encode("utf-8")).hexdigest()
        header = {"format": "json_chunks", "source": index, "sha256": checksum,
                  "characters": len(original), "chunk_characters": CHUNK_CHARACTERS}
        records.append(json.dumps(header, ensure_ascii=False, separators=(",", ":")))
        for start in range(0, len(original), CHUNK_CHARACTERS):
            end = min(len(original), start + CHUNK_CHARACTERS)
            records.append(json.dumps({"start": start, "end": end, "text": original[start:end]},
                ensure_ascii=False, separators=(",", ":")))
    return "\n".join(records)


def prepare(cold):
    if not enabled():
        return {}
    oversized = {index for index, original in cold.texts.items()
        if any(len(line) + 8 > MAX_READ_CHARS for line in original.split("\n"))}
    requested = {node_handle(index): (index,) for index in oversized}
    aliases = {}
    for origin, members in requested.items():
        body = encoded_members(cold, members)
        handle = snapshot_handle(members, body)
        cold.put_snapshot(handle, body)
        cold.bind(handle, members)
        aliases[origin] = handle
    return aliases


def verified_copies(cold, ranges):
    copies = []
    for handle, body in cold.snapshots.items():
        if not handle.startswith(PREFIX):
            continue
        members = cold.handles.get(handle)
        if not members or any(index not in cold.texts for index in members):
            raise ValueError("chunk source unavailable")
        if body != encoded_members(cold, members) or handle != snapshot_handle(members, body):
            raise ValueError("chunk identity mismatch")
        first, last = ranges[handle]
        cursor = first
        for index in members:
            count = 1 + (len(cold.texts[index]) + CHUNK_CHARACTERS - 1) // CHUNK_CHARACTERS
            copies.append((index, cursor, cursor + count - 1))
            cursor += count
        if cursor != last + 1:
            raise ValueError("chunk extent mismatch")
    return tuple(copies)
