"""Horizon J: shared R=16 trajectory, slice 4/8. P1 re-runs π with P0 inner J."""

from __future__ import annotations

from dataclasses import dataclass

from memory.simulator.cache_model import CacheState, after_request
from memory.simulator.cost_model import shot_cost
from memory.simulator.params import Params
from memory.simulator.projection import project
from memory.simulator.state_model import ACTIONS, ContextState, freeze_s0, roll_turn


@dataclass(frozen=True)
class Trajectory:
	action0: str
	c_action: float
	biz: tuple[float, ...]  # per-shot C_biz, length R
	actions: tuple[str, ...]

	def J(self, R: int) -> float:
		r = min(R, len(self.biz))
		return self.c_action + sum(self.biz[:r])


def _delta_text(ctx_delta: str) -> str:
	return ctx_delta if ctx_delta else "follow-up\n"


def p0_trajectory(
	s0: ContextState,
	cache: CacheState,
	first_action: str,
	steps: int,
	params: Params,
	delta_text: str,
) -> Trajectory:
	"""After Apply(a), future shots keep unless HardTop. No nested vote."""
	from memory.simulator.decision import hardtop_pick

	s_a, shot0 = shot_cost(s0, first_action, cache, params, charge_action=True)
	biz = [shot0.c_biz]
	acts = [first_action]
	cache_h = after_request(cache, x_sent=shot0.x, action=first_action)
	s = freeze_s0(roll_turn(s_a, _delta_text(delta_text), params))
	for _h in range(1, steps):
		keep_l = project(s).length
		if keep_l > params.l_max:
			picked = hardtop_pick(s, cache_h, params)
			a = picked if picked in ACTIONS else "keep"
		else:
			a = "keep"
		s_a, shot = shot_cost(s, a, cache_h, params, charge_action=False)
		biz.append(shot.c_biz)
		acts.append(a)
		cache_h = after_request(cache_h, x_sent=shot.x, action=a)
		s = freeze_s0(roll_turn(s_a, _delta_text(delta_text), params))
	return Trajectory(
		action0=first_action,
		c_action=shot0.c_action,
		biz=tuple(biz),
		actions=tuple(acts),
	)


def p1_trajectory(
	s0: ContextState,
	cache: CacheState,
	first_action: str,
	steps: int,
	params: Params,
	delta_text: str,
	remaining_turns: int,
) -> Trajectory:
	"""h=0 uses first_action; h>=1 re-runs π with P0 J (no nested P1)."""
	from memory.simulator.decision import decide

	s_a, shot0 = shot_cost(s0, first_action, cache, params, charge_action=True)
	biz = [shot0.c_biz]
	acts = [first_action]
	cache_h = after_request(cache, x_sent=shot0.x, action=first_action)
	s = freeze_s0(roll_turn(s_a, _delta_text(delta_text), params))
	for h in range(1, steps):
		inner = decide(
			s,
			cache_h,
			remaining_turns=max(1, remaining_turns - h),
			params=params,
			delta_text=delta_text,
			forecast="p0",
		)
		a = inner.a_star if inner.a_star in ACTIONS else "keep"
		s_a, shot = shot_cost(s, a, cache_h, params, charge_action=False)
		biz.append(shot.c_biz)
		acts.append(a)
		cache_h = after_request(cache_h, x_sent=shot.x, action=a)
		s = freeze_s0(roll_turn(s_a, _delta_text(delta_text), params))
	return Trajectory(
		action0=first_action,
		c_action=shot0.c_action,
		biz=tuple(biz),
		actions=tuple(acts),
	)


def trajectory_for(
	s0: ContextState,
	cache: CacheState,
	first_action: str,
	params: Params,
	*,
	forecast: str,
	delta_text: str,
	remaining_turns: int,
	steps: int = 16,
) -> Trajectory:
	# 缺口③：J_a(R) 是「跑 R 轮的钱」（§4.7(6)），轨迹步数不得超出预计剩余轮数，
	# 否则 J(16) 会假设会话还有 16 轮未来，高估压缩过渡 miss 的摊薄（表现乐观）。
	steps = min(int(steps), max(1, int(remaining_turns)))
	if forecast == "p1":
		return p1_trajectory(
			s0, cache, first_action, steps, params, delta_text, remaining_turns
		)
	return p0_trajectory(s0, cache, first_action, steps, params, delta_text)
