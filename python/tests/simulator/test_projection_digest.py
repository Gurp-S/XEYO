"""P1 缺失2：ProjectionDigest 可重入计量 + decide 的 lcp_keep 重启可重入。

验收（见交接提示词）：
- 杀进程重启后 decide 仍能算出 lcp_keep（= 上一枪冻结前缀长度，无需重放全文）。
- working.flush() → hydrate 能恢复 ProjectionDigest 字段。
"""

from __future__ import annotations

from memory.working import (
    ProjectionDigest,
    WorkingSnapshot,
    flush,
    hydrate,
)
from memory.simulator.cache_model import CacheState
from memory.simulator.cost_model import shot_cost
from memory.simulator.params import load_params
from memory.simulator.projection import project
from memory.simulator.state_model import ContextState, Segment, freeze_s0


def _seg(i: str, text: str, *, kind: str = "tool_result") -> Segment:
    return Segment(
        id=i,
        text=text,
        role="user",
        kind=kind,
        tool_use_id=i if kind == "tool_result" else None,
        tool_name="Read" if kind == "tool_result" else None,
        r=1.0,
    )


def _state() -> ContextState:
    ps = (_seg("ps", "You are XEYO.\n", kind="text"),)
    m = (_seg("tr0", "A" * 4000), _seg("tr1", "B" * 4000))
    tk = (_seg("tk", "tail", kind="text"),)
    tn = (_seg("tn", "now", kind="text"),)
    return freeze_s0(ContextState(p_s=ps, m=m, t_k=tk, t_now=tn))


def test_projection_digest_roundtrip_flush_hydrate():
    """flush → hydrate 能恢复 ProjectionDigest 字段（重启后 lcp_keep 可重入）。"""
    sid = "sess_digest_rt"
    snap = WorkingSnapshot(session_id=sid)
    snap.last_projection = ProjectionDigest(
        prefix_hash="a" * 64,
        total_len=400,
        frozen_len=300,
        tail_len=100,
    )
    flush(sid, snap)
    restored = hydrate(sid)
    assert restored.last_projection is not None
    assert restored.last_projection.prefix_hash == "a" * 64
    assert restored.last_projection.total_len == 400
    assert restored.last_projection.frozen_len == 300
    assert restored.last_projection.tail_len == 100


def test_evaluate_lcp_keep_uses_frozen_len():
    """decide/keep 的 lcp_keep 用 x_prev_frozen_len（= digest.frozen_len），而非依赖全文。"""
    s0 = _state()
    p = load_params()
    # digest.frozen_len 已知（可重入计量）
    digest_frozen = 300
    cache = CacheState(x_prev="", x_prev_frozen_len=digest_frozen)
    _s, shot = shot_cost(s0, "keep", cache, charge_action=True)
    keep_L = project(s0).length
    assert keep_L > digest_frozen
    assert shot.lcp == digest_frozen  # 重启用 frozen_len 估，不回退字符串 LCP
    assert 0 < shot.H <= shot.L


def test_evaluate_lcp_fallback_to_string_when_zero():
    """x_prev_frozen_len=0（未知）时回退字符串 LCP；x_prev 空则 lcp=0（保守）。"""
    s0 = _state()
    cache = CacheState(x_prev="", x_prev_frozen_len=0)
    _s, shot = shot_cost(s0, "keep", cache, charge_action=True)
    assert shot.lcp == 0


def test_update_projection_digest_from_state():
    """runtime.update_projection_digest 从 s0 的冻结前缀计量出 digest。"""
    from memory.runtime import update_projection_digest

    s0 = _state()
    w = WorkingSnapshot(session_id="sess_digest_upd")
    update_projection_digest(w, s0)
    d = w.last_projection
    assert d is not None
    # 精确：emitted token len 之和应 >= p_s token 尺寸
    proj = project(s0)
    assert d.frozen_len == proj.p_end  # 冻结前缀 token 长度 = p_end
    assert d.total_len == proj.length
    assert d.tail_len == max(0, proj.length - proj.p_end)
    assert len(d.prefix_hash) == 64


def test_decide_keep_lcp_reentrant_after_restart():
    """模拟重启：shapshot 只保留 ProjectionDigest，decide 的 keep 分支仍算出 lcp>0。"""
    from memory.simulator.decision import decide

    s0 = _state()
    p = load_params()
    digest = ProjectionDigest(prefix_hash="b" * 64, total_len=8000, frozen_len=1200, tail_len=6800)
    # 重启后只有 digest，_x 全文（last_x_sim）为空字符串
    cache = CacheState(x_prev="", x_prev_frozen_len=digest.frozen_len)
    d = decide(s0, cache, remaining_turns=8, params=p, forecast="p0")
    assert d.branches["keep"].lcp > 0
    assert d.branches["keep"].lcp == min(digest.frozen_len, project(s0).length)
