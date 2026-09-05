"""v6.1 decision chain: HardTop → per-horizon argmin J → majority vote → safety gate."""

from __future__ import annotations

import os
from dataclasses import dataclass

from memory.simulator.cache_model import CacheState
from memory.simulator.cost_model import shot_cost
from memory.simulator.horizon import Trajectory, trajectory_for
from memory.simulator.params import Params, load_params
from memory.simulator.projection import project
from memory.simulator.quality_model import g_beta
from memory.simulator.r_estimator import RGate
from memory.simulator.state_model import (
	ACTIONS,
	TIE_RANK,
	ContextState,
	apply,
	fingerprint,
	freeze_s0,
	legal,
)

L4 = "L4"


def _pareto_enabled() -> bool:
	"""B1 证据门（优化1）：Pareto 可行集替代加权 J。默认关=与冻结版逐位一致。

	走 memory_switches.get_value（settings.memory 唯一权威，env 不参与）。
	"""
	from memory.memory_switches import get_value

	return get_value("XEYO_V61_PARETO") == "1"


def _pareto_env_float(name: str, default: float) -> float:
	raw = os.environ.get(name, "").strip()
	if raw:
		try:
			return float(raw)
		except ValueError:
			pass
	return default


def _pareto_pick(
	cand: dict[str, float],
	branches: dict[str, "Branch"],
	m_tok: int,
	params: Params,
) -> str:
	"""B1：硬约束 + 非支配排序替代 argmin J。

	可行集 F = {a | C_biz(a) ≤ C_MAX×C_biz(keep), D_a/|M| ≤ D_MAX}；
	F 内取 (C_biz, D) 非支配集，再按 J（平局 TIE_RANK）决胜——J 保留为
	可行集内部的排序器，但「省小钱丢大脸」的组合被硬约束直接排除。
	"""
	c_max = _pareto_env_float("XEYO_V61_PARETO_CMAX", 1.15)
	d_max = _pareto_env_float("XEYO_V61_PARETO_DMAX", 0.05)
	c_keep = max(branches["keep"].c_biz, 1e-12)
	den = max(int(m_tok), 1)
	feas: list[tuple[str, float, float, float]] = []
	for a, j in cand.items():
		br = branches.get(a)
		if br is None:
			continue
		d_norm = float(br.D) / den
		if br.c_biz <= c_max * c_keep and d_norm <= d_max:
			feas.append((a, br.c_biz, d_norm, j))
	if not feas:
		return _argmin_j(cand, params)

	def _dominated(x: tuple[str, float, float, float]) -> bool:
		return any(
			y[1] <= x[1] + 1e-15
			and y[2] <= x[2] + 1e-15
			and (y[1] < x[1] - 1e-15 or y[2] < x[2] - 1e-15)
			for y in feas
			if y[0] != x[0]
		)

	non_dominated = [x for x in feas if not _dominated(x)]
	non_dominated.sort(key=lambda x: (round(x[3], params.j_round_ndigits), TIE_RANK.get(x[0], 9)))
	return non_dominated[0][0]


def _round_j(j: float, params: Params) -> float:
	return round(float(j), params.j_round_ndigits)


def _argmin_j(candidates: dict[str, float], params: Params) -> str:
	best_a = "keep"
	best_j = None
	best_rank = 99
	for a in ACTIONS:
		if a not in candidates:
			continue
		j = _round_j(candidates[a], params)
		rank = TIE_RANK[a]
		if best_j is None or j < best_j or (j == best_j and rank < best_rank):
			best_j = j
			best_a = a
			best_rank = rank
	return best_a


def _argmin_d(ds: dict[str, float], params: Params) -> str:
	"""HardTop: argmin D; |D1-D2|<=eps_D → C1."""
	if "C1" in ds and "C2" in ds and abs(ds["C1"] - ds["C2"]) <= params.eps_d:
		return "C1"
	best_a = None
	best_d = None
	for a in ("C1", "C2"):
		if a not in ds:
			continue
		d = ds[a]
		if best_d is None or d < best_d - params.eps_d:
			best_d = d
			best_a = a
		elif best_a is not None and abs(d - best_d) <= params.eps_d:
			# 平手 → C1
			best_a = "C1" if "C1" in ds else a
	return best_a or L4


@dataclass(frozen=True)
class Branch:
	action: str
	L: int
	Q: float
	D: float
	H: float
	lcp: int
	legal: bool
	c_biz: float
	c_action: float
	alarms: tuple[str, ...]
	x: str


@dataclass(frozen=True)
class Decision:
	a_star: str
	a4: str
	a8: str
	a16: str
	a_vote: str
	a_hard: str | None
	hardtop: bool
	G_beta: int
	J: dict[str, dict[int, float]]
	margin_j: dict[int, float]
	feasible: dict[int, tuple[str, ...]]
	branches: dict[str, Branch]
	s0_fp: str
	remaining_turns: int
	notes: tuple[str, ...] = ()


def _branch(s0: ContextState, cache: CacheState, action: str, params: Params) -> Branch:
	_s_a, shot = shot_cost(s0, action, cache, params, charge_action=True)
	return Branch(
		action=action,
		L=shot.L,
		Q=shot.Q,
		D=shot.D,
		H=shot.H,
		lcp=shot.lcp,
		legal=legal(action, s0, params),
		c_biz=shot.c_biz,
		c_action=shot.c_action,
		alarms=shot.alarms,
		x=shot.x,
	)


def _ok_quality_length(br: Branch, params: Params) -> bool:
	return br.Q >= params.theta and br.L <= params.l_max and br.legal


def hardtop_pick(s0: ContextState, cache: CacheState, params: Params) -> str | None:
	if not s0.frozen_i_m:
		return None
	ds: dict[str, float] = {}
	for a in ("C1", "C2"):
		if not legal(a, s0, params):
			continue
		s_a, shot = shot_cost(s0, a, cache, params, charge_action=True)
		if shot.Q >= params.theta and shot.L <= params.l_max:
			ds[a] = shot.D
	if not ds:
		return None
	picked = _argmin_d(ds, params)
	return picked if picked in ("C1", "C2") else None


def _safety(a_vote: str, branches: dict[str, Branch], params: Params, *, hardtop: bool) -> str:
	order = ("C1", "C2") if hardtop else ("keep", "C1", "C2")
	if a_vote in branches and _ok_quality_length(branches[a_vote], params):
		if not hardtop or a_vote != "keep":
			return a_vote
	for a in order:
		if a in branches and _ok_quality_length(branches[a], params):
			return a
	return L4


def decide(
	s: ContextState,
	cache: CacheState,
	*,
	remaining_turns: int = 8,
	params: Params | None = None,
	delta_text: str = "follow-up\n",
	forecast: str = "p1",
	r_gate: RGate | None = None,
) -> Decision:
	p = params or load_params()
	s0 = freeze_s0(s)
	fp0 = fingerprint(s0)
	notes: list[str] = []
	gb = g_beta(s0, p)
	# P1 缺失3：R 从「预测值」降级为「约束条件」。r_gate（None=全部档可行）只约束
	# 哪些 horizon 参与 per-R 决策与投票；Q/J/vote 公式一律不动。不得把 R 当唯一选择器。
	horizons: tuple[int, ...] = p.horizons if r_gate is None else r_gate.allowed_horizons
	if r_gate is not None and r_gate.force_hardtop:
		notes.append("R_gate_force_hardtop")
	branches = {a: _branch(s0, cache, a, p) for a in ACTIONS}
	# Apply 不得改动 S0
	for a in ACTIONS:
		apply(a, s0, p)
	if fingerprint(s0) != fp0:
		raise RuntimeError("Apply mutated S0")

	keep_l = branches["keep"].L
	keep_sendable = keep_l <= p.l_hard_send
	need_hard = (keep_l > p.l_max) or (not keep_sendable)
	a_hard: str | None = None

	empty_m = not s0.frozen_i_m
	if empty_m:
		notes.append("empty_M")

	if need_hard:
		a_hard = hardtop_pick(s0, cache, p)
		a_star = a_hard or L4
		notes.append("hardtop")
		return Decision(
			a_star=a_star,
			a4=a_star,
			a8=a_star,
			a16=a_star,
			a_vote=a_star,
			a_hard=a_hard,
			hardtop=True,
			G_beta=gb,
			J={a: {} for a in ACTIONS},
			margin_j={},
			feasible={},
			branches=branches,
			s0_fp=fp0,
			remaining_turns=remaining_turns,
			notes=tuple(notes),
		)

	# R=1 收尾：keep，不覆盖 HardTop（已另行处理）
	if remaining_turns <= 1:
		notes.append("R=1_keep")
		return Decision(
			a_star="keep",
			a4="keep",
			a8="keep",
			a16="keep",
			a_vote="keep",
			a_hard=None,
			hardtop=False,
			G_beta=gb,
			J={a: {} for a in ACTIONS},
			margin_j={},
			feasible={1: ("keep",)},
			branches=branches,
			s0_fp=fp0,
			remaining_turns=remaining_turns,
			notes=tuple(notes),
		)

	steps = max(horizons)
	traj: dict[str, Trajectory] = {}
	jtab: dict[str, dict[int, float]] = {a: {} for a in ACTIONS}
	for a in ACTIONS:
		if a != "keep" and empty_m:
			continue
		if a != "keep" and not branches[a].legal:
			continue
		traj[a] = trajectory_for(
			s0,
			cache,
			a,
			p,
			forecast=forecast,
			delta_text=delta_text,
			remaining_turns=remaining_turns,
			steps=steps,
		)
		for R in horizons:
			jtab[a][R] = traj[a].J(R)

	per_r: dict[int, str] = {}
	feasible: dict[int, tuple[str, ...]] = {}
	margin: dict[int, float] = {}
	for R in horizons:
		j_keep = jtab.get("keep", {}).get(R)
		if j_keep is None:
			j_keep = 0.0
		j_keep_den = j_keep if j_keep > 0 else 1e-15
		fset = ["keep"]
		for a in ("C1", "C2"):
			if empty_m or a not in jtab or R not in jtab[a]:
				continue
			br = branches[a]
			if not _ok_quality_length(br, p):
				continue
			if jtab[a][R] <= p.tau_switch * j_keep_den:
				fset.append(a)
		feasible[R] = tuple(fset)
		cand = {a: jtab[a][R] for a in fset if a in jtab and R in jtab[a]}
		if "keep" not in cand:
			cand["keep"] = j_keep
		if _pareto_enabled():
			# B1 证据门：Pareto 可行集（C_biz ≤ 1.15×keep，D/|M| ≤ θ_D）内非支配，
			# J 只作可行集内部决胜。「省小钱丢大脸」的组合被硬约束排除。
			m_tok = sum(v for _i, v in s0.frozen_v)
			per_r[R] = _pareto_pick(cand, branches, m_tok, p)
		else:
			per_r[R] = _argmin_j(cand, p)
		js = [jtab[a][R] for a in fset if a in jtab and R in jtab[a]]
		js_sorted = sorted(js)
		if len(js_sorted) >= 2:
			margin[R] = js_sorted[1] - js_sorted[0]
		elif js_sorted:
			margin[R] = 0.0

	a4, a8, a16 = per_r.get(4, "keep"), per_r.get(8, "keep"), per_r.get(16, "keep")
	counts: dict[str, int] = {}
	for a in (a4, a8, a16):
		counts[a] = counts.get(a, 0) + 1
	# 稳定顺序：先遍历 ACTIONS 再遍历其余
	best_n = 0
	a_vote = "keep"
	for a in list(ACTIONS) + [x for x in counts if x not in ACTIONS]:
		n = counts.get(a, 0)
		if n > best_n:
			best_n = n
			a_vote = a
	if best_n < 2:
		a_vote = "keep"

	a_star = _safety(a_vote, branches, p, hardtop=False)
	if fingerprint(s0) != fp0:
		raise RuntimeError("decision mutated S0")
	return Decision(
		a_star=a_star,
		a4=a4,
		a8=a8,
		a16=a16,
		a_vote=a_vote,
		a_hard=None,
		hardtop=False,
		G_beta=gb,
		J=jtab,
		margin_j=margin,
		feasible=feasible,
		branches=branches,
		s0_fp=fp0,
		remaining_turns=remaining_turns,
		notes=tuple(notes),
	)


def decision_key(d: Decision) -> tuple:
	return (d.a4, d.a8, d.a16, d.a_vote, d.a_hard, d.a_star, d.hardtop)
