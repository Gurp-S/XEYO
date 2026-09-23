"""发车闸门的自身回归：`evals/wsc_sid_guard.py` 必须真的能抓出"跨采样点共用 session_id"。

不依赖语料，用假投影器：`leaky` 会按 sid 记住自己见过哪些前缀（模拟 `_STATE` 冻结头），
`pure` 完全不记。同一个测试必须让前者**报警**、后者**通过**——只有一边响的断言才算守卫在干活。
"""

from __future__ import annotations

from evals.wsc_sid_guard import SidLedger, contamination, order_is_stable


def pure(prefix: str, sid: str) -> str:
    """假投影器：完全无状态。sid 只出现在取回文件名里（真实形状），比较时会遮掉。"""
    return f"H[{prefix}] view=offload/wsc/{sid}.txt"


def leaky_builder():
    seen: dict[str, str] = {}

    def leaky(prefix: str, sid: str) -> str:
        # 同一 sid 第二次进来时复用第一次的头——这就是 _STATE + FROZEN_HEAD 的形状
        return seen.setdefault(sid, f"H[{prefix}] view=offload/wsc/{sid}.txt")
    return leaky


PREFIXES = ["abc", "abcd", "abcde", "abcdef"]


def test_unique_sid_is_order_independent() -> None:
    ok, bad = order_is_stable(pure, PREFIXES)
    assert ok and not bad, "唯一 sid 下顺序不该影响输出"


def test_ledger_refuses_reusing_a_sid_for_another_prefix() -> None:
    """执法点：同一个 sid 打第二个不同前缀 ⇒ 必须当场拦住（这才是"每点唯一 sid"的硬闸）。"""
    led = SidLedger()
    led.claim("s-1", "abc")
    led.claim("s-1", "abc")            # 同一点重投影，合法
    try:
        led.claim("s-1", "abcd")
    except SystemExit as exc:
        assert "冻结头" in str(exc), "拒跑信息要说清后果"
    else:
        raise AssertionError("复用 sid 必须被拦")


def test_shared_sid_run_is_flagged_by_contamination() -> None:
    """诊断面：真被污染时（同一 sid 连打多个前缀），差异必须报出来而不是 0。"""
    leaky = leaky_builder()
    diff, ratio, size = contamination(leaky, PREFIXES)
    # 第一个点两边都是它自己 ⇒ 只有后面的点会暴露差异（真实语料上量到 7/8）
    assert diff >= 2, f"共用 sid 时至少两个点该受影响，实际 {diff}"
    assert 0.0 < ratio <= 1.0
    assert abs(size - 1.0) > 1e-6, "共用 sid 的字符量应当与唯一 sid 不同（方向取决于实现）"
    # 真实 V1 上的方向是"共用更大"（+40.6%），见 docs/wsc2-phase5.md §8.1；假件不预设方向。


def test_unique_sid_run_is_clean_by_construction() -> None:
    """正例：唯一 sid ⇒ 与"每次都新鲜"的参照一致，且顺序无关。"""
    ok, bad = order_is_stable(pure, PREFIXES)
    assert ok and not bad
    diff, _r, _s = contamination(pure, PREFIXES)   # 无状态投影 ⇒ 两种策略应当一致
    assert diff == 0, "无状态的投影器不该报出污染"


def test_contamination_reports_magnitude() -> None:
    leaky = leaky_builder()
    shared = [leaky(p, "S") for p in PREFIXES]          # 先被污染一遍
    diff, ratio, size = contamination(lambda p, s: leaky(p, s), PREFIXES)
    assert 0.0 <= ratio <= 1.0
    assert size > 0
    assert len(shared) == len(PREFIXES)



