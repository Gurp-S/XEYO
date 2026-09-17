"""Minimal stage timing helpers for WSC diagnostics.

Timing is observability only: it never participates in selection, rendering,
or determinism digests.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Iterator


@dataclass
class StageTimer:
	"""Measure sequential stage durations without changing WSC output."""

	_started: float = field(default_factory=perf_counter)
	_last: float = field(init=False)
	_values: dict[str, float] = field(default_factory=dict)

	def __post_init__(self) -> None:
		self._last = self._started

	def mark(self, name: str) -> None:
		now = perf_counter()
		self._values[str(name)] = max(0.0, (now - self._last) * 1000.0)
		self._last = now

	@contextmanager
	def measure(self, name: str) -> Iterator[None]:
		"""Accumulate a nested/repeated sub-stage without changing checkpoints."""
		started = perf_counter()
		try:
			yield
		finally:
			elapsed = max(0.0, (perf_counter() - started) * 1000.0)
			key = str(name)
			self._values[key] = self._values.get(key, 0.0) + elapsed

	def finish(self) -> dict[str, float]:
		now = perf_counter()
		self._values["total"] = max(0.0, (now - self._started) * 1000.0)
		return {name: round(value, 3) for name, value in self._values.items()}


__all__ = ["StageTimer"]
