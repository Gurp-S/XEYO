"""Context state S, C0-δ freeze, independent Apply(a, S0)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

from engine.compact import MAX_TOOL_RESULT_CHARS, TRUNCATE_SUFFIX
from memory.simulator.params import Params, load_params
# P0 估参在生产热路径（memory.runtime）与离线 simulator 之间共享，单点定义见 memory.token。
from memory.token import n_lines, token_len

Action = Literal["keep", "C1", "C2", "L4"]
ACTIONS: tuple[str, ...] = ("keep", "C1", "C2")
TIE_RANK = {"keep": 0, "C1": 1, "C2": 2}


@dataclass(frozen=True)
class Segment:
	id: str
	text: str
	role: str = "user"
	kind: str = "text"  # text | tool_use | tool_result | summary
	tool_use_id: str | None = None
	tool_name: str | None = None
	r: float = 1.0
	high_value: bool = False
	# B2 证据门（优化2）：原子类型（fidelity_segmenter 的 stack/kv/path/…）。
	# 原片段为 ""；不进 fingerprint——同文本不同类型标注不改变决策缓存语义。
	atom_kind: str = ""

	@property
	def tokens(self) -> int:
		return token_len(self.text)

	@property
	def line_count(self) -> int:
		return n_lines(self.text)


def _copy_seg(seg: Segment, **kwargs: Any) -> Segment:
	return replace(seg, **kwargs)


@dataclass(frozen=True)
class ContextState:
	p_s: tuple[Segment, ...] = ()
	p_c: tuple[Segment, ...] = ()
	m: tuple[Segment, ...] = ()
	t_k: tuple[Segment, ...] = ()
	t_now: tuple[Segment, ...] = ()
	delta: tuple[Segment, ...] = ()
	turns_since_middle_edit: int = 10_000
	turn: int = 0
	frozen_i_m: tuple[str, ...] = ()
	frozen_v: tuple[tuple[str, int], ...] = ()
	# C2 之后 I_M 单元不在 m 中；quality 用此 r 和摘要跨度。
	c2_active: bool = False
	c2_summary_id: str | None = None
	c2_r: float = 0.6

	def region_tokens(self, segs: tuple[Segment, ...]) -> int:
		return sum(s.tokens for s in segs)

	@property
	def m_tokens(self) -> int:
		return self.region_tokens(self.m)

	@property
	def t_tokens(self) -> int:
		return self.region_tokens(self.t_k) + self.region_tokens(self.t_now)

	@property
	def p_tokens(self) -> int:
		return self.region_tokens(self.p_s) + self.region_tokens(self.p_c)

	def frozen_v_map(self) -> dict[str, int]:
		return dict(self.frozen_v)

	def all_segments(self) -> tuple[Segment, ...]:
		return self.p_s + self.p_c + self.m + self.t_k + self.t_now + self.delta

	def segment_by_id(self) -> dict[str, Segment]:
		return {s.id: s for s in self.all_segments()}


def _c0_truncate_seg(seg: Segment) -> Segment:
	"""§4.2 C0: cap a single tool_result. Prefix layout unchanged."""
	if seg.kind != "tool_result":
		return seg
	raw = seg.text or ""
	if len(raw) <= MAX_TOOL_RESULT_CHARS:
		return seg
	return replace(seg, text=raw[:MAX_TOOL_RESULT_CHARS] + TRUNCATE_SUFFIX)


def _c0_truncate_region(segs: tuple[Segment, ...]) -> tuple[Segment, ...]:
	return tuple(_c0_truncate_seg(seg) for seg in segs)


def freeze_s0(s: ContextState) -> ContextState:
	"""S0 = C0 size-cap then C0_δ: truncate tool_results, drop δ, freeze I_M."""
	capped = replace(
		s,
		p_s=_c0_truncate_region(s.p_s),
		p_c=_c0_truncate_region(s.p_c),
		m=_c0_truncate_region(s.m),
		t_k=_c0_truncate_region(s.t_k),
		t_now=_c0_truncate_region(s.t_now),
		delta=(),
	)
	ids = tuple(seg.id for seg in capped.m)
	vs = tuple((seg.id, seg.tokens) for seg in capped.m)
	return replace(capped, frozen_i_m=ids, frozen_v=vs)


def atomize_m_segments(
	segs: tuple[Segment, ...], *, needles: tuple[str, ...] = ()
) -> tuple[Segment, ...]:
	"""把 M 段按信息原子切分（P1 缺失1）。

	Q 的单元粒度由此从「消息条数」细化为「原子数」：一条含报错栈 + 取值行的
	tool_result 会被切成多个原子，折叠报错栈不再连带把取值行一起减信。每个原子
	继承原 Segment 的 role/kind/tool 信息，只替换 id/text 并重算 high_value。
	不改 Q/J/投票公式，只改表示粒度。
	"""
	from memory.fidelity_segmenter import split_into_atoms

	if not segs:
		return segs
	out: list[Segment] = []
	for seg in segs:
		atoms = split_into_atoms(seg.text)
		if len(atoms) <= 1:
			out.append(seg)
			continue
		for j, atom in enumerate(atoms):
			hv = bool(needles) and any(n in atom.text for n in needles)
			out.append(
				replace(
					seg,
					id=f"{seg.id}:atom{j}",
					text=atom.text,
					high_value=hv,
					atom_kind=atom.kind,
				)
			)
	return tuple(out)


def apply(action: str, s0: ContextState, params: Params | None = None) -> ContextState:
	"""Independent branch. Must not mutate s0."""
	p = params or load_params()
	if action == "keep":
		return replace(s0)
	if action == "C1":
		return _apply_c1(s0, p)
	if action == "C2":
		return _apply_c2(s0, p)
	raise ValueError(f"unknown action: {action}")


def _apply_c1(s0: ContextState, params: Params) -> ContextState:
	new_m: list[Segment] = []
	for seg in s0.m:
		if seg.kind == "tool_result" and seg.r >= params.r_orig - 1e-12:
			stub = f"[compacted] {seg.tool_name or 'tool'}: {seg.line_count} matches"
			new_m.append(_copy_seg(seg, text=stub, r=params.r_stub))
		else:
			new_m.append(seg)
	return replace(
		s0,
		m=tuple(new_m),
		turns_since_middle_edit=0,
		c2_active=False,
		c2_summary_id=None,
	)


def _apply_c2(s0: ContextState, params: Params) -> ContextState:
	hv = [seg.text[:80] for seg in s0.m if seg.high_value]
	meta = ";".join(
		f"{seg.id}:{seg.tool_name or seg.kind}:{seg.tokens}" for seg in s0.m
	)
	summary_text = "[C2] " + meta
	if hv:
		summary_text += "\n" + "\n".join(hv)
	sid = "c2_summary"
	summary = Segment(
		id=sid,
		text=summary_text,
		role="system",
		kind="summary",
		r=params.r_summary,
	)
	return replace(
		s0,
		p_c=s0.p_c + (summary,),
		m=(),
		turns_since_middle_edit=0,
		c2_active=True,
		c2_summary_id=sid,
		c2_r=params.r_summary,
	)


def has_unstubbed_tool(s: ContextState, params: Params) -> bool:
	return any(
		seg.kind == "tool_result" and seg.r >= params.r_orig - 1e-12 for seg in s.m
	)


def legal(action: str, s0: ContextState, params: Params) -> bool:
	if action == "keep":
		return True
	if not s0.frozen_i_m:
		return False
	if s0.turns_since_middle_edit < params.min_middle_edit_gap:
		return False
	if action == "C1":
		return has_unstubbed_tool(s0, params)
	if action == "C2":
		return True
	return False


def roll_turn(s: ContextState, delta_text: str, params: Params) -> ContextState:
	"""After a sent request: t_now → T_k, overflow → M, new t_now = Δ."""
	combined = s.t_k + s.t_now
	k = params.t_k_count
	if len(combined) > k:
		overflow, t_k = combined[:-k], combined[-k:]
		m = s.m + overflow
	else:
		overflow, t_k, m = (), combined, s.m
	new_id = f"delta:{s.turn + 1}"
	t_now = (
		Segment(id=new_id, text=delta_text, role="user", kind="text"),
	) if delta_text else ()
	return replace(
		s,
		m=m,
		t_k=t_k,
		t_now=t_now,
		turn=s.turn + 1,
		turns_since_middle_edit=s.turns_since_middle_edit + 1,
		# I_M 保持 *决策* S0 的冻结值；真实 turn 之后再重新冻结。
		frozen_i_m=tuple(seg.id for seg in m),
		frozen_v=tuple((seg.id, seg.tokens) for seg in m),
		c2_active=False if overflow else s.c2_active,
	)


def fingerprint(s: ContextState) -> str:
	parts = [
		s.turns_since_middle_edit,
		s.turn,
		int(s.c2_active),
		s.c2_summary_id or "",
		str(s.c2_r),
		"|".join(s.frozen_i_m),
	]
	for seg in s.all_segments():
		parts.append(f"{seg.id}:{seg.r}:{seg.text}")
	return "\n".join(str(x) for x in parts)
