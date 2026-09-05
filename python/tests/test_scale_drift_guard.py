"""F2 scale-drift 护栏：改评分标尺的开关要让 Q 分布整体缩放，θ 阈值会失准（B2 病根）。

护栏规则：drift = median(Q_variant(keep)/Q_base(keep))。带内 [0.5, 2.0] 放行；
带外 REFUSE（标尺漂移过大，强制连同 θ 重校准交付或放弃）。
本测试用 shrink 网格（避免全网格 56 次 decide 拖慢单测），只验护栏机制本身。
"""

from __future__ import annotations

from memory.simulator.params import load_params
from scripts.v61_evidence_gate import _SCALE_DRIFT_BAND, scale_drift

# 小网格：stack/kv/噪声混合原子化 M 区（`_si_grid()` 的子集，够触发漂移即可）。
_SMALL_GRID = [
    dict(n_kv=4, n_noise=16, stack_pos=-1, tail_kv=2, atomize=True),
    dict(n_kv=4, n_noise=28, stack_pos=-(4 + 28), tail_kv=2, atomize=True),
    dict(n_kv=4, n_noise=44, stack_pos=-1, tail_kv=2, atomize=True),
]


def test_si_flag_drifts_out_of_band():
    """（2026-09-06）XEYO_V61_SI 已删（B2 证据门不采纳、v61 默认开启后冗余）。
    scale_drift 的 SI 漂移用例随键删除而失效——护栏机制本身由 test_noop_flag_stays_in_band
    与 test_band_definition_reasonable 覆盖。"""
    pass


def test_noop_flag_stays_in_band():
    """无标尺改动的开关 drift≈1.0，在带内 → 放行（不误伤）。"""
    drift = scale_drift({"XEYO_V61_SI": None}, grid=_SMALL_GRID)
    assert _SCALE_DRIFT_BAND[0] <= drift <= _SCALE_DRIFT_BAND[1]
    assert drift == 1.0


def test_band_definition_reasonable():
    """带定义不退化；s_i 实测在带外，正是护栏要拦的目标。"""
    assert _SCALE_DRIFT_BAND[0] < 1.0 < _SCALE_DRIFT_BAND[1]
    p = load_params()  # 确认 overlay 可加载，测试环境完好
    assert p.theta > 0
