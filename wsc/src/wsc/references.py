"""Opt-in, exact content relocation for a caller-named local resource."""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from .contracts import require


def normalize_lines(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def locate(text, resource, *, expected_sha256, max_bytes=1048576,resource_io=None):
    require(isinstance(resource, str) and resource and isinstance(expected_sha256, str),
            "reference_binding_invalid")
    require(type(max_bytes) is int and max_bytes > 0, "reference_byte_budget_invalid")
    path = Path(resource)
    require(path.is_absolute(), "reference_resource_not_absolute")
    result = {"resource": str(path), "checked_at": datetime.now(timezone.utc).isoformat(),
        "expected_resource_sha256": expected_sha256,
        "matching": "exact_text_after_line_ending_normalization",
        "historical_observation_retimed": False}
    try:
        if resource_io is not None:raw=resource_io.read_bounded(path,max_bytes+1)
        else:
            with path.open("rb") as stream:raw = stream.read(max_bytes + 1)
    except OSError:
        return {**result, "status": "resource_unavailable", "bytes_read": 0}
    result["bytes_read"] = len(raw)
    if len(raw) > max_bytes:
        return {**result, "status": "resource_byte_budget_exhausted"}
    result["resource_sha256"] = sha256(raw).hexdigest()
    if result["resource_sha256"] != expected_sha256:
        return {**result, "status": "resource_version_changed"}
    try:
        content = normalize_lines(raw.decode("utf-8-sig"))
    except UnicodeDecodeError:
        return {**result, "status": "resource_encoding_unavailable"}
    needle = normalize_lines(text)
    require(bool(needle), "reference_text_empty")
    offset = content.find(needle)
    if offset < 0:
        return {**result, "status": "content_missing"}
    if content.find(needle, offset + 1) >= 0:
        return {**result, "status": "content_ambiguous"}
    return {**result, "status": "unique_content_match", "start_line": content[:offset].count("\n") + 1,
        "end_line": content[:offset + len(needle.rstrip('\n'))].count("\n") + 1,
        "matched_normalized_text_sha256": sha256(needle.encode("utf-8")).hexdigest()}


def check(bindings, *, resource_io=None):
    for binding in bindings:
        if binding.get("status") == "unique_content_match":
            path = Path(binding["resource"])
            if resource_io is not None:
                try:actual=resource_io.digest(path,max_bytes=binding['bytes_read'])
                except OSError:require(False,'reference_resource_changed')
                require(actual==binding['resource_sha256'],'reference_resource_changed')
                continue
            require(path.is_file(), "reference_resource_changed")
            with path.open("rb") as stream:
                raw = stream.read(binding["bytes_read"] + 1)
            require(sha256(raw).hexdigest() == binding["resource_sha256"], "reference_resource_changed")
