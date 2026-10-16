"""Scoped extension configuration documents; validation never starts extensions."""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import threading
from functools import wraps
from pathlib import Path
from typing import Any

CONFIG_WRITE_LOCK = threading.RLock()
SETTINGS_KEYS = frozenset({"enabled_extensions", "plugins", "skills", "mcp_servers"})


def serialized_config_write(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with CONFIG_WRITE_LOCK:
            return fn(*args, **kwargs)
    return wrapped


def read_document(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes() if path.exists() else b""
    data = json.loads(raw) if raw else {}
    if not isinstance(data, dict):
        raise ValueError("configuration must be a JSON object")
    return data, hashlib.sha256(raw).hexdigest()


def atomic_document_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _object(value: Any, field: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _ident(value: str) -> None:
    if not value.strip() or value != value.strip() or any(ord(c) < 32 or 127 <= ord(c) <= 159 or c == "`" for c in value):
        raise ValueError("invalid entry name")


def validate_document(kind: str, data: dict[str, Any]) -> None:
    _object(data, "configuration")
    if kind == "settings":
        if set(data) - SETTINGS_KEYS:
            raise ValueError("only extension settings can be edited here")
        for name, value in data.items():
            if name == "enabled_extensions":
                if type(value) is not bool:
                    raise ValueError("enabled_extensions must be boolean")
                continue
            for key, entry in _object(value, name).items():
                _ident(key)
                entry = _object(entry, key)
                allowed = {"enabled", "auto_start"} if name == "mcp_servers" else {"enabled"}
                if set(entry) - allowed or any(type(v) is not bool for v in entry.values()):
                    raise ValueError(f"{name}.{key}: expected boolean enabled/auto_start fields")
        return
    from extension.mcp_scopes import _MCP_SERVER_FIELDS, MCP_POLICIES, ENV_MODES
    if set(data) != {"servers"}:
        raise ValueError('MCP configuration requires a "servers" object; only stdio transport is supported')
    for sid, spec in _object(data["servers"], "servers").items():
        _ident(sid)
        spec = _object(spec, sid)
        extra = set(spec) - _MCP_SERVER_FIELDS
        if extra:
            raise ValueError(f"{sid}: unsupported fields: {', '.join(sorted(extra))}")
        if not isinstance(spec.get("command"), str) or not spec["command"].strip() or "\0" in spec["command"]:
            raise ValueError(f"{sid}: command is required")
        for key in ("args", "env_vars", "read_only_tools", "enabled_tools"):
            if key in spec and (not isinstance(spec[key], list) or any(not isinstance(v, str) or "\0" in v for v in spec[key])):
                raise ValueError(f"{sid}.{key} must be a string array")
        for key in ("auto_start", "required", "elicit", "trust_annotations"):
            if key in spec and type(spec[key]) is not bool:
                raise ValueError(f"{sid}.{key} must be boolean")
        for key in ("startup_timeout_s", "tool_timeout_s"):
            if key in spec and (type(spec[key]) not in (int, float) or not math.isfinite(spec[key]) or spec[key] <= 0):
                raise ValueError(f"{sid}.{key} must be a positive finite number")
        if "env_mode" in spec and spec["env_mode"] not in ENV_MODES:
            raise ValueError(f"{sid}: invalid env_mode")
        if "tools_policy" in spec and spec["tools_policy"] not in MCP_POLICIES:
            raise ValueError(f"{sid}: invalid tools_policy")
        if "bearer_token_env_var" in spec and not isinstance(spec["bearer_token_env_var"], str):
            raise ValueError(f"{sid}: bearer_token_env_var must be a string")
        for key in ("env", "tool_policies", "output_token_limits"):
            for name, value in _object(spec.get(key, {}), key).items():
                if key == "output_token_limits":
                    valid = type(value) is int and value > 0
                else:
                    valid = isinstance(value, str) and "\0" not in name and "\0" not in value
                    if key == "tool_policies":
                        valid = valid and value in MCP_POLICIES
                if not valid:
                    raise ValueError(f"{sid}.{key}.{name}: invalid value")


class ConfigConflict(ValueError):
    pass


def save_document(path: Path, kind: str, data: dict[str, Any], revision: str) -> str:
    validate_document(kind, data)
    with CONFIG_WRITE_LOCK:
        current, actual = read_document(path)
        if revision != actual:
            raise ConfigConflict("configuration changed; reload before saving")
        # Preserve non-extension settings and unrelated top-level metadata.
        base = {k: v for k, v in current.items() if k not in SETTINGS_KEYS} if kind == "settings" else current
        merged = {**base, **data}
        atomic_document_write(path, merged)
        return read_document(path)[1]
