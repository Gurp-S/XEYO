"""Quality: fidelity × visibility. I = I_M only. λ(x)=1+κ·4x(1-x) frozen."""

from __future__ import annotations

import os
from dataclasses import dataclass

from memory.simulator.params import Params, load_params
from memory.simulator.projection import Projected, project
from memory.simulator.state_model import ContextState


def lambda_z(z: float, kappa: float) -> float:
	x = min(1.0, max(0.0, z))
	return 1.0 + kappa * 4.0 * x * (1.0 - x)


def q_unit(r: float, z: float | None, kappa: float) -> float:
	if r <= 0:
		return 0.0
	if z is None:
		raise ValueError("z required when r>0")
	return r / lambda_z(z, kappa)


# --------------------------------------------------------------------------- #
# B2 证据门（优化2）：内容类型驻留分 s_i —— q_i = r_i·s_i/λ_eff(z_i)。
# 报错栈 s=1.2 且 λ 强制 1（无视位置死保）；kv/json/path 正常衰减 κ=0.3；
# tree/grep 大输出 s=0.6 强衰减 κ=1.2；line/chunk（bash 纯日志）s=0.3 极强衰减 κ=1.8。
# 仅 XEYO_V61_SI=1 且单元带 atom_kind 时生效；默认关闭=与冻结公式逐位一致。
# --------------------------------------------------------------------------- #

_SI_TABLE: dict[str, tuple[float, float | None]] = {
	"stack": (1.2, None),  # None → λ 强制 1（位置豁免）
	"kv": (1.0, 0.3),
	"json": (1.0, 0.3),
	"path": (1.0, 0.3),
	"table": (0.8, 0.8),
	"tree": (0.6, 1.2),
	"line": (0.3, 1.8),
	"chunk": (0.3, 1.8),
}


def si_enabled() -> bool:
	"""B2 证据门：走 memory_switches.get_value（settings.memory 唯一权威）。"""
	from memory.memory_switches import get_value

	return get_value("XEYO_V61_SI") == "1"


def si_for(atom_kind: str) -> tuple[float, float | None]:
	"""返回 (s_i, κ覆盖)。无标注 / 未收录类型 → (1.0, None)（冻结公式行为）。"""
	entry = _SI_TABLE.get((atom_kind or "").strip())
	if not entry:
		return 1.0, None
	return entry


def q_unit_si(
	r: float, z: float | None, kappa: float, atom_kind: str
) -> float:
	"""B2 版 q_unit：q = r·s_i/λ_eff(z)。stack 的 λ_eff 强制 1。"""
	if r <= 0:
		return 0.0
	if z is None:
		raise ValueError("z required when r>0")
	s_i, kappa_override = si_for(atom_kind)
	if kappa_override is None and s_i >= 1.2:
		# 报错栈：位置豁免（λ=1），只乘驻留分
		return r * s_i
	lam = lambda_z(z, kappa_override if kappa_override is not None else kappa)
	return r * s_i / lam


@dataclass(frozen=True)
class UnitEval:
	id: str
	v: int
	r: float
	z: float | None
	q: float
	raw_dq: float  # q(S0)-q(Sa) without relu
	position_improved: bool


@dataclass(frozen=True)
class QualityResult:
	Q: float
	D: float
	units: tuple[UnitEval, ...]
	alarms: tuple[str, ...]
	G_beta: int
	empty_m: bool


def _z_for_unit(
	s: ContextState, uid: str, proj: Projected
) -> tuple[float, float | None, str]:
	"""Return (r, z, atom_kind). z is None iff r==0."""
	L = max(proj.length, 1)
	if s.c2_active:
		r = s.c2_r
		if r <= 0:
			return 0.0, None, ""
		span = proj.spans.get(s.c2_summary_id or "")
		if span is None:
			z = 0.0
		else:
			z = span.mid / L
		return r, min(1.0, max(0.0, z)), ""
	seg = s.segment_by_id().get(uid)
	if seg is None:
		return 0.0, None, ""
	if seg.r <= 0:
		return 0.0, None, ""
	span = proj.spans.get(uid)
	if span is None:
		z = 0.0
	else:
		z = span.mid / L
	return seg.r, min(1.0, max(0.0, z)), getattr(seg, "atom_kind", "") or ""


def evaluate_quality(
	s_a: ContextState,
	s0: ContextState,
	params: Params | None = None,
) -> QualityResult:
	p = params or load_params()
	i_m = s0.frozen_i_m
	vmap = s0.frozen_v_map()
	t_tok = s0.t_tokens
	g_beta = 1 if s0.m_tokens > p.beta * max(t_tok, 0) and t_tok >= 0 else 0
	if t_tok == 0:
		g_beta = 1 if s0.m_tokens > 0 else 0

	if not i_m:
		return QualityResult(
			Q=1.0, D=0.0, units=(), alarms=(), G_beta=g_beta, empty_m=True
		)

	proj0 = project(s0)
	proja = project(s_a)
	units: list[UnitEval] = []
	alarms: list[str] = []
	num = 0.0
	den = 0.0
	d_sum = 0.0
	si_on = si_enabled()
	for uid in i_m:
		v = int(vmap.get(uid, 0))
		r0, z0, kind0 = _z_for_unit(s0, uid, proj0)
		ra, za, _kind_a = _z_for_unit(s_a, uid, proja)
		if si_on and kind0:
			q0 = q_unit_si(r0, z0, p.kappa, kind0) if r0 > 0 else 0.0
			qa = q_unit_si(ra, za, p.kappa, kind0) if ra > 0 else 0.0
		else:
			q0 = q_unit(r0, z0, p.kappa) if r0 > 0 else 0.0
			qa = q_unit(ra, za, p.kappa) if ra > 0 else 0.0
		lam0 = lambda_z(z0 if z0 is not None else 0.0, p.kappa)
		lama = lambda_z(za if za is not None else 0.0, p.kappa)
		pos_improved = ra > 0 and r0 > 0 and za is not None and z0 is not None and lama < lam0 - 1e-12
		raw = q0 - qa
		if raw < -1e-12 and not pos_improved:
			alarms.append(f"q_increased_without_position:{uid}:raw={raw:.6f}")
		d_sum += v * max(raw, 0.0)
		num += v * qa
		den += v
		units.append(
			UnitEval(
				id=uid, v=v, r=ra, z=za, q=qa, raw_dq=raw, position_improved=pos_improved
			)
		)
	Q = 1.0 if den <= 0 else num / den
	Q = min(1.0, max(0.0, Q))
	return QualityResult(
		Q=Q,
		D=max(0.0, d_sum),
		units=tuple(units),
		alarms=tuple(alarms),
		G_beta=g_beta,
		empty_m=False,
	)


def g_beta(s0: ContextState, params: Params | None = None) -> int:
	p = params or load_params()
	t_tok = s0.t_tokens
	if t_tok <= 0:
		return 1 if s0.m_tokens > 0 else 0
	return 1 if s0.m_tokens > p.beta * t_tok else 0
