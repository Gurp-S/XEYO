from memory.simulator.cache_model import CacheState
from memory.simulator.cost_model import hat_H
from memory.simulator.decision import decide
from memory.simulator.params import Params
from memory.simulator.r_estimator import RGate
from memory.simulator.state_model import ContextState, Segment


def test_frozen_length_cannot_credit_a_changed_or_missing_prefix():
    for previous in ('old prefix', ''):
        hit, lcp = hat_H(x_a='new prefix', x_prev=previous, L=1000, action='C2',
                         rho=1.0, g=64, x_prev_frozen_len=640)
        assert (hit, lcp) == (0, 0)
    text = 'x' * 4096
    hit, lcp = hat_H(x_a=text + 'a', x_prev=text + 'b', L=2000, action='keep',
                     rho=1.0, g=64, x_prev_frozen_len=640)
    assert hit > 0 and lcp > 640


def test_absent_horizons_do_not_outvote_the_enabled_horizon():
    state = ContextState(m=(Segment('m', 'x' * 16000, kind='tool_result'),),
                         t_now=(Segment('now', 'continue'),), turns_since_middle_edit=99)
    params = Params(theta=0.0, lambda_q=0.0, r_summary=1.0, tau_switch=1.0)
    decision = decide(state, CacheState(x_prev=''), params=params, remaining_turns=16,
                      forecast='p0', r_gate=RGate({4: True, 8: False, 16: False}))
    assert decision.a4 != 'keep'
    assert decision.a_vote == decision.a4
    assert set(decision.feasible) == {4}
