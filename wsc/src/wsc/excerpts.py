"""Exact caller-selected observations, with optional version-bound reference relocation."""
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path

from .contracts import require
from . import evidence
from . import references


@dataclass(frozen=True)
class Excerpt:
    key: str
    source_id: str
    # A None step decodes a JSON string; other steps address a key or array index.
    path: tuple
    start: int
    end: int
    text_sha256: str
    historical_locator: str | None = None
    current_resource: str | None = None
    current_resource_sha256: str | None = None
    # Public text is an immutable producer-supplied event field, not a payload path.
    basis: str = "payload"


def text_at(payload, path):
    require(isinstance(path, (tuple, list)), "excerpt_path_invalid")
    value = payload
    for step in path:
        if step is None:
            require(isinstance(value, str), "excerpt_json_value_not_text")
            try:
                value = json.loads(value)
            except ValueError:
                require(False, "excerpt_json_unavailable")
        elif type(step) is int:
            require(isinstance(value, list) and 0 <= step < len(value), "excerpt_index_unavailable")
            value = value[step]
        else:
            require(isinstance(step, str) and isinstance(value, dict) and step in value,
                    "excerpt_key_unavailable")
            value = value[step]
    require(isinstance(value, str), "excerpt_value_not_text")
    return value


def resolve(selected, known, *, bind_live=True,resource_io=None):
    resolved, keys = [], set()
    for item in selected:
        require(isinstance(item, Excerpt), "excerpt_shape_invalid")
        require(isinstance(item.key, str) and item.key.strip() and item.key not in keys,
                "excerpt_key_invalid_or_duplicate")
        keys.add(item.key)
        require(item.source_id in known, "excerpt_source_missing")
        source = known[item.source_id]
        require(source["kind"] != "opaque", "opaque_excerpt_unavailable")
        require(isinstance(item.basis, str) and item.basis in {"payload", "public_text"},
                "excerpt_basis_invalid")
        if item.basis == "public_text":
            require(item.path in ((), []), "public_text_excerpt_path_invalid")
            text = text_at(source["text"], ())
        else:
            text = text_at(source["payload"], item.path)
        require(type(item.start) is int and type(item.end) is int and
                0 <= item.start < item.end <= len(text), "excerpt_range_invalid")
        selected_text = text[item.start:item.end]
        require(sha256(selected_text.encode("utf-8")).hexdigest() == item.text_sha256,
                "excerpt_content_mismatch")
        require(item.historical_locator is None or isinstance(item.historical_locator, str),
                "excerpt_locator_invalid")
        resolved.append({**asdict(item), "text": selected_text,
                         "observed_at": source["observed_at"], "source_kind": source["kind"],
                         "call_id": source["call_id"]})
        require((item.current_resource is None) == (item.current_resource_sha256 is None),
                "reference_binding_incomplete")
        if item.current_resource is not None and bind_live:
            resolved[-1]["current_reference"] = references.locate(selected_text, item.current_resource,
                expected_sha256=item.current_resource_sha256,resource_io=resource_io)
    return resolved


def export(store, access, selected, directory, *, write_object=None):
    directory = Path(directory).resolve()
    locators = {}
    for item in selected:
        evidence.authorize(store, access, item["source_id"], "export")
        raw = item["text"].encode("utf-8")
        require(sha256(raw).hexdigest() == item["text_sha256"], "excerpt_content_mismatch")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (item["text_sha256"] + ".txt")
        (write_object or evidence.write_once)(path, raw)
        locators[item["key"]] = {"source_id": item["source_id"], "file_path": str(path),
            "sha256": item["text_sha256"], "observed_at": item["observed_at"],
            "representation": "exact_selected_public_text", "path": item["path"],
            "basis": item.get("basis", "payload"),
            "start": item["start"], "end": item["end"]}
    return locators


def check(store, access, locators, *, resource_io=None):
    for locator in locators.values():
        evidence.authorize(store, access, locator["source_id"], "export")
        path = Path(locator["file_path"])
        actual = resource_io.digest(path) if resource_io is not None else (sha256(path.read_bytes()).hexdigest() if path.is_file() else None)
        require(actual == locator["sha256"],
                "exported_excerpt_changed_or_missing")
