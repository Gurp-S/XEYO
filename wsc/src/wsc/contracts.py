"""Host-neutral contracts. Semantic choices belong to the caller's model."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Any, Callable, Protocol


class WSCError(ValueError):
    """A neutral, machine-readable execution result."""


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return sha256(encode(value).encode("utf-8")).hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise WSCError(reason)


def identifier(value: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), "invalid_identity")
    return value


@dataclass(frozen=True)
class Event:
    id: str
    kind: str
    payload: dict
    role: str | None = None
    call_id: str | None = None
    text: str | None = None
    observed_at: str | None = None
    control: bool = False


@dataclass(frozen=True)
class Understanding:
    text: str
    kind: str
    sources: tuple[str, ...] = ()
    scope: dict | None = None
    # Identity is optional on first write; revisions require an expected revision.
    id: str | None = None
    expected_revision: int | None = None


@dataclass(frozen=True)
class Selection:
    source_ids: tuple[str, ...] = ()
    understanding_refs: tuple[str, ...] = ()
    new_understandings: tuple[Understanding, ...] = ()
    # Each clue is model-selected text with exact source IDs, not a runtime plan.
    clues: tuple[dict, ...] = ()
    # Excerpt instances are exact observation slices, separate from model conclusions.
    excerpts: tuple = ()


@dataclass(frozen=True)
class Snapshot:
    session_id: str
    workspace: str
    generation: int
    control_epoch: int
    understanding_epoch: int
    cut: int
    source_digest: str
    events: tuple[dict, ...]
    understandings: tuple[dict, ...]


@dataclass(frozen=True)
class Limits:
    # Bytes are explicitly bytes; token accounting is supplied by the host.
    max_view_bytes: int = 32768
    max_generation_calls: int = 1
    max_material_bytes: int = 262144


@dataclass(frozen=True)
class Usage:
    input_uncached: int | None = None
    input_cached: int | None = None
    output: int | None = None
    elapsed_ms: float | None = None


@dataclass(frozen=True)
class Generated:
    selection: Selection
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class HostReceipt:
    operation_id: str
    package_digest: str
    session_id: str
    workspace: str
    generation: int
    control_epoch: int
    installed_through: int
    receiver: str
    evidence_accessible: bool


@dataclass(frozen=True)
class HostRejection:
    """Durable terminal result: this operation was not and will not be installed."""
    operation_id: str
    package_digest: str
    session_id: str
    workspace: str
    reason: str
    receiver: str


class HostPort(Protocol):
    """install is idempotent and guards binding at installation time.

    None from lookup means outcome unknown, not proof of non-execution.
    Installation must preserve host events newer than package.through.
    """
    def install(self, package: dict) -> HostReceipt | HostRejection: ...
    def lookup(self, operation_id: str) -> HostReceipt | HostRejection | None: ...


class GeneratorPort(Protocol):
    def __call__(self, material: dict) -> Generated: ...


AccessCheck = Callable[[str, str, str], bool]
