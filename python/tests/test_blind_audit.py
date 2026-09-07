"""blind_audit_shadow 门槛/证明性测试（③）。

覆盖：
- 关（默认）：available=False（审计关闭）。
- 解析：合法 JSON → 正确类别/证据；坏 JSON → 回退 clean。
- aggregate：多轨迹 → 各类占比 + leakage_rate。
- fail-open：无 DEEPSEEK_API_KEY → available=False + error（不抛，不阻塞评测）。
"""

from __future__ import annotations

import pytest

from evals.blind_audit_shadow import (
    BlindAuditResult,
    _parse_category,
    aggregate,
    audit_transcript,
    enabled,
)


@pytest.fixture()
def audit_off(monkeypatch):
    monkeypatch.delenv("XEYO_EVAL_BLIND_AUDIT", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("XEYO_SIDEMOD_PROMOTE", "0")


def test_default_disabled(audit_off):
    assert enabled() is False
    r = audit_transcript("transcript", question="q")
    assert r.available is False
    assert "disabled" in r.error


def test_parse_valid_json():
    cat, ev = _parse_category('{"category": "git_history_mining", "evidence": "cherry-picked fix commit"}')
    assert cat == "git_history_mining"
    assert "cherry-picked" in ev


def test_parse_invalid_falls_to_clean():
    assert _parse_category("not json") == ("clean", "not json")


def test_parse_unknown_category_normalizes_to_clean():
    cat, _ev = _parse_category('{"category": "something_else", "evidence": "x"}')
    assert cat == "clean"


def test_aggregate_rates():
    results = [
        BlindAuditResult(available=True, category="upstream_lookup"),
        BlindAuditResult(available=True, category="upstream_lookup"),
        BlindAuditResult(available=True, category="git_history_mining"),
        BlindAuditResult(available=True, category="clean"),
        BlindAuditResult(available=False, error="no key"),
    ]
    agg = aggregate(results)
    assert agg["total"] == 5
    assert agg["by_category"]["upstream_lookup"] == 2
    assert agg["by_category"]["git_history_mining"] == 1
    # leak = 3 (2+1) / total5 = 0.6；「clean」与「不可得」不计 leak。
    assert agg["leakage_rate"] == 0.6


def test_fail_open_no_api_key(monkeypatch):
    """无 DEEPSEEK_API_KEY → chat 抛 EvalError → 返回 available=False，不抛。"""
    monkeypatch.setenv("XEYO_EVAL_BLIND_AUDIT", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert enabled() is True
    r = audit_transcript("t", question="q")
    assert r.available is False
    assert r.error  # 带原因
