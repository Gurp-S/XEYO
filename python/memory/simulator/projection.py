"""Action-dependent projection Π_a. X^a is the byte sequence sent to the model."""

from __future__ import annotations

from dataclasses import dataclass

from memory.simulator.state_model import ContextState, Segment, token_len


def emit_segment(seg: Segment) -> str:
	uid = seg.tool_use_id or ""
	return f"{seg.role}\n{seg.kind}\n{uid}\n{seg.text}\n"


@dataclass(frozen=True)
class Span:
	start: int
	end: int  # exclusive, token offsets into X

	@property
	def mid(self) -> float:
		if self.end <= self.start:
			return float(self.start)
		return (self.start + self.end) / 2.0


@dataclass(frozen=True)
class Projected:
	x: str
	length: int
	spans: dict[str, Span]
	p_end: int  # token offset where P ends (start of M)


def project(s: ContextState) -> Projected:
	parts: list[str] = []
	spans: dict[str, Span] = {}
	tok = 0
	p_end = 0

	def add_region(segs: tuple[Segment, ...], *, mark_p_end: bool = False) -> None:
		nonlocal tok, p_end
		for seg in segs:
			chunk = emit_segment(seg)
			n = token_len(chunk)
			spans[seg.id] = Span(tok, tok + n)
			parts.append(chunk)
			tok += n
		if mark_p_end:
			p_end = tok

	add_region(s.p_s)
	add_region(s.p_c, mark_p_end=True)
	add_region(s.m)
	add_region(s.t_k)
	add_region(s.t_now)
	add_region(s.delta)
	x = "".join(parts)
	return Projected(x=x, length=tok, spans=spans, p_end=p_end)


def common_prefix(a: str, b: str) -> str:
	n = min(len(a), len(b))
	i = 0
	while i < n and a[i] == b[i]:
		i += 1
	return a[:i]


def lcp_tokens(x_a: str, x_prev: str) -> int:
	if not x_a or not x_prev:
		return 0
	return token_len(common_prefix(x_a, x_prev))
