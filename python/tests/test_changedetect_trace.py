"""L1 决策轨迹层测试：注入 + 回路电池的确定性、灵敏度、与 golden 自洽。"""

from __future__ import annotations

import pytest

from evals.changedetect import canon, trace


def test_inject_battery_includes_strategy_variants():
    tr = trace.collect(batteries={"inject"})
    assert "inject/channel_legacy" in tr
    assert "inject/channel_env" in tr
    assert "inject/wrap_up" in tr
    # 两种声道策略的输出必须**不一样**——否则 injection 层的判别力作废
    assert tr["inject/channel_legacy"] != tr["inject/channel_env"]


def test_loop_battery_event_compression_stable():
    a = trace.collect(batteries={"loop"})
    b = trace.collect(batteries={"loop"})
    assert a == b


def test_one_char_change_in_block_text_is_detected(tmp_path):
    """块文本改一个字符 → 注入轨迹必变（灵敏度）。

    载荷原为 ``_wrap_up_block_text``；该块已于 2026-09-15 撤销（用户裁定），
    故改用仍然存活的 ``browser_preview_block``（plain 场景即装配）。
    """
    from prompt import pre_llm_inject as inj
    original = inj.browser_preview_block
    base = original()
    try:
        inj.browser_preview_block = lambda: base + "!"  # type: ignore[assignment]
        tr = trace.collect(batteries={"inject"})
        target = "inject/plain"
        # 把当前渲染写为临时 golden
        gdir = tmp_path / "g"
        (gdir / "trace").mkdir(parents=True)
        (gdir / "trace" / f"{canon.safe_name(target)}.txt").write_text(
            tr[target], encoding="utf-8"
        )
        # 还原函数后再跑一次，应当被侦测到
        inj.browser_preview_block = lambda: base  # type: ignore[assignment]
        tr2 = trace.collect(batteries={"inject"})
        changes = trace.compare(tr2, directory=gdir)
        assert any(c["name"] == target for c in changes)
    finally:
        inj.browser_preview_block = original  # type: ignore[assignment]


def test_trace_check_against_committed_golden_passes():
    tr = trace.collect()
    changes = trace.compare(tr)
    assert changes == [], f"L1 golden 漂移：{[c['name'] for c in changes]}"


def test_compliance_r2_minimal_branch_flagged():
    from evals.changedetect import compliance
    diff = (
        "+++ b/python/engine/x.py\n"
        "+if XEYO_BENCH_MINIMAL:\n"
        "+    return 'lite'\n"
        "+return 'full'\n"
    )
    hits = compliance.scan_added_lines(diff)
    rules = {h.rule for h in hits}
    assert "R2" in rules


def test_compliance_r4_tests_read_flagged():
    from evals.changedetect import compliance
    diff = (
        "+++ b/python/server/x.py\n"
        "+    return open('/tests/results.json').read()\n"
    )
    hits = compliance.scan_added_lines(diff)
    assert any("R4" in h.rule for h in hits)


def test_compliance_clean_diff_no_hits():
    from evals.changedetect import compliance
    diff = (
        "+++ b/python/engine/x.py\n"
        "+def foo(x):\n"
        "+    return x + 1\n"
    )
    hits = compliance.scan_added_lines(diff)
    assert hits == []
