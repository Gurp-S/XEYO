"""reporting_shadow 门槛/证明性测试（⑤）。

覆盖：
- 关（默认）：enabled=False。
- build_report 恒含 4 字段（standard/strict/Δ/leakage_rate）。
- 只有 accuracy 时：strict/Δ/leakage_rate=None，capability 保守归「编码+检索能力」。
- strict 有值时 Δ = standard - strict。
- assert_no_single_accuracy：单 accuracy 报告返回 False；含 4 字段返回 True。
- fail-open：空/异常输入返回带兜底的字典，不丢分。
"""

from __future__ import annotations

import pytest

from evals.reporting_shadow import (
    assert_no_single_accuracy,
    build_report,
    enabled,
)


@pytest.fixture()
def rep_off(monkeypatch):
    monkeypatch.delenv("XEYO_EVAL_REPORTING", raising=False)
    monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "0")


def test_default_disabled(rep_off):
    assert enabled() is False


def test_build_report_always_has_4_fields():
    r = build_report({"accuracy": 0.85})
    for k in ("standard", "strict", "delta", "leakage_rate"):
        assert k in r


def test_single_accuracy_note():
    r = build_report({"accuracy": 0.85})
    assert r["standard"] == 0.85
    assert r["strict"] is None
    assert r["delta"] is None
    assert r["leakage_rate"] is None
    assert r["capability"] == "编码+检索能力"  # 保守归混合


def test_delta_when_strict_present():
    r = build_report({"accuracy": 0.85, "strict": 0.70, "leakage_rate": 0.18})
    assert r["standard"] == 0.85
    assert r["strict"] == 0.70
    assert r["delta"] == 0.15
    assert r["leakage_rate"] == 0.18


def test_capability_label_override():
    r = build_report({"accuracy": 0.9}, mode_label="编码能力")
    assert r["capability"] == "编码能力"


def test_assert_no_single_accuracy():
    # 只报 accuracy（无 strict/Δ/leak）→ 不满足。
    assert assert_no_single_accuracy({"accuracy": 0.85}) is False
    # 含 strict + Δ + leakage → 满足。
    assert (
        assert_no_single_accuracy(
            {"standard": 0.85, "strict": 0.70, "delta": 0.15, "leakage_rate": 0.18}
        )
        is True
    )
    # 非 dict → 不满足。
    assert assert_no_single_accuracy(None) is False


def test_fail_open_empty():
    r = build_report({})
    assert r["standard"] is None
    assert r["delta"] is None
