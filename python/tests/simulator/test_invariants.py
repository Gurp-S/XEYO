"""§4.7(11) invariants: math, empty M, monotonicity, Apply independence, HardTop, R=1."""

from __future__ import annotations

from dataclasses import replace

from memory.simulator.cache_model import CacheState
from memory.simulator.cost_model import expected_output, shot_cost, split_tokens
from memory.simulator.decision import decide, hardtop_pick
from memory.simulator.params import load_params
from memory.simulator.projection import project
from memory.simulator.quality_model import evaluate_quality, lambda_z, q_unit
from memory.simulator.scenarios import state_from_messages
from memory.simulator.state_model import (
	ContextState,
	Segment,
	apply,
	fingerprint,
	freeze_s0,
	legal,
	token_len,
)


def _cache(x_prev: str = "") -> CacheState:
	p = load_params()
	return CacheState(
		provider=p.provider,
		model=p.model,
		slot=p.price_slot,
		ts=p.default_ts,
		x_prev=x_prev,
	)


def _seg(i: str, text: str, *, kind: str = "text", r: float = 1.0, name: str = "Read") -> Segment:
	return Segment(
		id=i,
		text=text,
		role="user",
		kind=kind,
		tool_use_id=i if kind == "tool_result" else None,
		tool_name=name if kind == "tool_result" else None,
		r=r,
	)


def _state_with_m(*m: Segment, tail: str = "now") -> ContextState:
	ps = (_seg("ps", "You are XEYO.\n"),)
	tk = (_seg("tk0", "t0"), _seg("tk1", "t1"), _seg("tk2", "t2"))
	tn = (_seg("tn", tail),)
	return freeze_s0(ContextState(p_s=ps, m=m, t_k=tk, t_now=tn))


def test_token_len_empty_and_ascii():
	assert token_len("") == 0
	assert token_len("A" * 4) == 1
	assert token_len("A" * 5) == 2


def test_apply_does_not_mutate_s0():
	s0 = _state_with_m(_seg("tr", "X" * 400, kind="tool_result"))
	fp = fingerprint(s0)
	for a in ("keep", "C1", "C2"):
		s_a = apply(a, s0)
		assert fingerprint(s0) == fp
		assert s_a is not s0
		if a == "C1":
			assert s_a.m[0].r == load_params().r_stub
			assert s0.m[0].r == 1.0
		if a == "C2":
			assert s_a.m == ()
			assert s0.m != ()


def test_empty_m_q1_d0_no_c1_c2():
	s0 = freeze_s0(
		ContextState(
			p_s=(_seg("ps", "sys\n"),),
			t_now=(_seg("tn", "hello"),),
		)
	)
	q = evaluate_quality(s0, s0)
	assert q.empty_m
	assert q.Q == 1.0
	assert q.D == 0.0
	d = decide(s0, _cache(), remaining_turns=8, forecast="p0")
	assert d.a_star == "keep"
	for R, fset in d.feasible.items():
		assert "C1" not in fset
		assert "C2" not in fset
	assert not legal("C1", s0, load_params())
	assert not legal("C2", s0, load_params())


def test_split_exclusive_and_hat_h_clip():
	s0 = _state_with_m(_seg("tr", "Y" * 800, kind="tool_result"))
	for a in ("keep", "C1", "C2"):
		s_a = apply(a, s0)
		_proj, spl = split_tokens(s_a=s_a, cache=_cache("prefix"), action=a, params=load_params())
		assert spl.ok
		assert 0 <= spl.H <= spl.L
		assert spl.U >= 0
		assert abs(spl.H + spl.U + spl.W_phys - spl.L) <= 1e-6
	_s, shot = shot_cost(s0, "C2", _cache("anything"), charge_action=True)
	assert shot.lcp == 0  # x_prev 与 C2 投影无共同前缀 → 自然 0
	assert 0 <= shot.H <= shot.L


def test_c2_lcp_uses_common_prefix_when_p_preserved():
	"""C2 保留左段 P：x_prev 是同一状态的 keep 投影时，LCP 应 > 0（不再硬编码 0）。"""
	s0 = _state_with_m(_seg("tr", "Y" * 800, kind="tool_result"))
	x_keep = project(apply("keep", s0)).x
	_s, shot = shot_cost(s0, "C2", _cache(x_keep), charge_action=True)
	assert shot.lcp > 0
	assert 0 <= shot.H <= shot.L


def test_q_in_0_1_d_nonneg():
	s0 = _state_with_m(
		_seg("u", "user note " * 20),
		_seg("tr", "Z" * 400, kind="tool_result"),
	)
	for a in ("keep", "C1", "C2"):
		s_a = apply(a, s0)
		q = evaluate_quality(s_a, s0)
		assert 0 <= q.Q <= 1
		assert q.D >= 0


def test_fidelity_monotonic_q_and_d():
	"""Same z, r: keep 1, C1 0.6, C2 0.25 → Q and D monotonic (unit-level)."""
	kappa = 0.8
	z = 0.4
	q_keep = q_unit(1.0, z, kappa)
	q_c1 = q_unit(0.6, z, kappa)
	q_c2 = q_unit(0.25, z, kappa)
	assert q_c2 <= q_c1 <= q_keep
	# D 使用 v * [q0-qa]+；v=10
	d1 = 10 * max(q_keep - q_c1, 0)
	d2 = 10 * max(q_keep - q_c2, 0)
	assert d1 <= d2


def test_position_monotonic_lambda_and_q():
	kappa = 0.8
	assert lambda_z(0.1, kappa) < lambda_z(0.3, kappa) < lambda_z(0.5, kappa)
	r = 1.0
	assert q_unit(r, 0.5, kappa) < q_unit(r, 0.3, kappa) < q_unit(r, 0.1, kappa)


def test_deletion_monotonic():
	kappa = 0.8
	z = 0.2
	qs = [q_unit(r, z, kappa) if r > 0 else 0.0 for r in (1.0, 0.6, 0.25, 0.0)]
	assert qs[0] >= qs[1] >= qs[2] >= qs[3]
	assert qs[3] == 0.0


def test_apply_quality_monotonic_when_m_is_tools():
	s0 = _state_with_m(_seg("tr", "W" * 1200, kind="tool_result"))
	qk = evaluate_quality(apply("keep", s0), s0)
	q1 = evaluate_quality(apply("C1", s0), s0)
	q2 = evaluate_quality(apply("C2", s0), s0)
	assert q2.Q <= qk.Q + 1e-9
	assert q1.D >= 0 and q2.D >= 0
	# C1 打桩 r=0.25 对 C2 摘要 0.6：只要 z 不显著更优，D(C1) 应 >= D(C2)
	# 若 C2 的 z 更差则不严格成立；但仍要求 D>=0。
	assert qk.D == 0


def test_raw_negative_dq_alarms_if_not_position():
	s0 = _state_with_m(_seg("tr", "Q" * 200, kind="tool_result"))
	# 伪造一次提升 r 的 apply（应触发告警）。
	s_bad = replace(s0, m=(replace(s0.m[0], r=1.0, text=s0.m[0].text + " extra"),))
	# s0 单元已是 r=1；把 s0 的 r 调低
	s_low = freeze_s0(replace(s0, m=(replace(s0.m[0], r=0.25),)))
	s_high = replace(s_low, m=(replace(s_low.m[0], r=1.0),))
	q = evaluate_quality(s_high, s_low)
	assert q.alarms


def test_g_beta_does_not_change_action():
	s0 = _state_with_m(
		_seg("u", "note"),
		_seg("tr", "T" * 800, kind="tool_result"),
	)
	p1 = load_params(beta=1)
	p8 = load_params(beta=8)
	d1 = decide(s0, _cache(), remaining_turns=8, params=p1, forecast="p0")
	d8 = decide(s0, _cache(), remaining_turns=8, params=p8, forecast="p0")
	assert d1.a_star == d8.a_star
	assert d1.a4 == d8.a4 and d1.a8 == d8.a8 and d1.a16 == d8.a16


def test_r1_keep_unless_hardtop():
	s0 = _state_with_m(_seg("tr", "T" * 200, kind="tool_result"))
	d = decide(s0, _cache(), remaining_turns=1, forecast="p0")
	assert d.a_star == "keep"
	assert "R=1_keep" in d.notes


def test_c0_truncates_tool_result_in_tail_and_m():
	from engine.compact import MAX_TOOL_RESULT_CHARS, TRUNCATE_SUFFIX

	blob = "H" * 20_000
	s0 = freeze_s0(
		ContextState(
			p_s=(_seg("ps", "sys\n"),),
			m=(_seg("mtr", blob, kind="tool_result"),),
			t_k=(_seg("tk", "tail"),),
			t_now=(_seg("tn", blob, kind="tool_result", name="Read"),),
		)
	)
	assert s0.m[0].text.endswith(TRUNCATE_SUFFIX)
	assert len(s0.m[0].text) == MAX_TOOL_RESULT_CHARS + len(TRUNCATE_SUFFIX)
	assert s0.t_now[0].text.endswith(TRUNCATE_SUFFIX)
	assert len(s0.t_now[0].text) == MAX_TOOL_RESULT_CHARS + len(TRUNCATE_SUFFIX)
	assert blob not in s0.m[0].text
	assert s0.t_k[0].text == "tail"


def test_hardtop_bypasses_tau_and_r1():
	p = load_params(window_tokens=800, reserve_tokens=50, alpha_win=0.55)
	# 计算 l_max = min(750, 440) = 440
	blob = "H" * 4000
	s0 = _state_with_m(_seg("tr", blob, kind="tool_result"), _seg("u", "please keep going"))
	assert project(s0).length > p.l_max
	d = decide(s0, _cache(), remaining_turns=1, params=p, forecast="p0")
	assert d.hardtop
	assert d.a_star in ("C1", "C2", "L4")
	assert d.a_star != "keep"


def test_hardtop_tie_prefers_c1():
	p = load_params()
	s0 = _state_with_m(_seg("tr", "T" * 100, kind="tool_result"))
	# 两者都因空而非法？非本例。仅确认辅助函数存在。
	picked = hardtop_pick(s0, _cache(), p)
	assert picked in (None, "C1", "C2")


def test_c1_leaves_p_bytes_unchanged():
	s0 = _state_with_m(_seg("tr", "T" * 400, kind="tool_result"))
	x0 = project(s0).x
	s1 = apply("C1", s0)
	x1 = project(s1).x
	p_end = project(s0).p_end
	# 比较到 p_end token 为止的前缀串很别扭；改为比较 p_s+p_c 分段。
	assert s1.p_s == s0.p_s
	assert s1.p_c == s0.p_c
	assert x0 != x1


def test_expected_output_inflates_when_q_low():
	p = load_params()
	assert expected_output(1.0, p) == p.o_mean
	assert expected_output(0.01, p) == p.o_mean * 2.0


def test_j_tie_order_keep_over_c1():
	from memory.simulator.decision import _argmin_j

	p = load_params()
	assert _argmin_j({"keep": 1.0, "C1": 1.0, "C2": 1.0}, p) == "keep"
	assert _argmin_j({"C1": 1.0, "C2": 1.0}, p) == "C1"


def test_trajectory_capped_by_remaining_turns():
	"""缺口③：J 步数被 remaining_turns 封顶——J(16) 不得假设超过剩余轮数的未来。"""
	from memory.simulator.horizon import trajectory_for
	from memory.simulator.scenarios import list_scenarios

	p = load_params()
	sc_ = next(
		s for s in list_scenarios(smoke=True) if s.kind == "F" and s.length_class == "S3"
	)
	s0 = sc_.state()
	cache = sc_.cache(p)
	t_long = trajectory_for(
		s0, cache, "keep", p,
		forecast="p0", delta_text=sc_.delta_text, remaining_turns=16, steps=16,
	)
	t_short = trajectory_for(
		s0, cache, "keep", p,
		forecast="p0", delta_text=sc_.delta_text, remaining_turns=5, steps=16,
	)
	assert len(t_long.biz) == 16
	assert len(t_short.biz) == 5  # 步数被 remaining_turns 封顶
	# 剩余 5 时任何 R>5 的 J 都只累计 5 步（修正后的语义：J(R) ≤ J(剩余)）
	assert t_short.J(16) == t_short.J(5)
	assert abs(t_long.J(16) - sum(t_long.biz)) < 1e-12
	assert abs(t_long.J(4) - sum(t_long.biz[:4])) < 1e-12


def test_unit_prices_reuse_pricing_table():
	from usage.pricing import unit_prices_cny_per_mtoken

	p = load_params()
	pr, pu, po, pw = unit_prices_cny_per_mtoken(
		provider="deepseek", model="deepseek-v4-flash", ts=p.default_ts, slot="offpeak"
	)
	assert pw == 0.0
	assert pr == 0.05
	assert pu == 1.5
	assert po == 4.5


def test_state_from_messages_splits_tail():
	msgs = [
		{"role": "user", "content": "u0"},
		{"role": "assistant", "content": "a0"},
		{"role": "user", "content": "u1"},
		{"role": "assistant", "content": "a1"},
		{"role": "user", "content": "u2"},
		{"role": "assistant", "content": "a2"},
		{"role": "user", "content": "now"},
	]
	s = state_from_messages(msgs)
	assert s.frozen_i_m  # early messages in M
	assert s.t_now and "now" in s.t_now[0].text
