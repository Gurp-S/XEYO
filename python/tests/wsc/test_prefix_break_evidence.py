"""断点取证钩子（`memory/observe.prefix_break_evidence`）的契约测试。

这是"幽灵类事故"（恢复/吸收/外部注入）唯一在运行时可见的指纹：离线回放不含
运行时状态、恒零复现，所以只能靠断点当刻的两份投影字节。两条纪律：
① 正常相邻枪绝不触发（否则审计被淹、等于没记）；② 触发时必须给出可直接指认的
位置与两侧样本。C2 折叠是已知机制、同样触发，消费侧按 action 过滤。
"""

from __future__ import annotations

import json
from pathlib import Path

from memory.observe import prefix_break_evidence


def _canon(msgs):
    return json.dumps(msgs, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _big(value: str) -> list[dict]:
    # ASCII 60k 字符 ≈ 15k token（token_len = utf8 字节/4），稳超 8000 阈值
    return [{"role": "user", "content": value * 60_000}]


def test_normal_adjacent_shot_does_not_fire() -> None:
    msgs = _big("A")
    prev = _canon(msgs)
    cur = _canon(msgs + [{"role": "assistant", "content": "ok"}])
    assert prefix_break_evidence(prev, cur, action="keep") is None


def test_prefix_rewrite_fires_with_position_and_samples() -> None:
    prev = _canon(_big("A"))
    cur = _canon(_big("B"))  # 同长度、前缀只共享到序列化头部
    ev = prefix_break_evidence(prev, cur, action="keep")
    assert ev is not None
    assert ev["action"] == "keep"
    assert ev["prev_tokens"] >= 8_000
    # 断点位置：两串只在开头十几个字符相同（`[{"content":"` 之类的序列化头）
    assert ev["diff_char"] < 200, ev
    assert ev["lcp_tokens"] == ev["diff_token"]
    assert ev["lcp_tokens"] < int(ev["prev_tokens"] * 0.5)
    assert ev["prev_sample"] and ev["cur_sample"]
    assert ev["prev_sample"][:8] == "A" * 8 or ev["prev_sample"].startswith(("[", "A")), ev["prev_sample"]


def test_small_prev_or_empty_never_fires() -> None:
    small_prev = _canon([{"role": "user", "content": "tiny"}])
    big_cur = _canon(_big("B"))
    assert prefix_break_evidence(small_prev, big_cur, action="keep") is None
    assert prefix_break_evidence("", big_cur, action="keep") is None
    assert prefix_break_evidence(big_cur, "", action="keep") is None


def test_extra_fields_pass_through() -> None:
    prev = _canon(_big("A"))
    cur = _canon(_big("B"))
    ev = prefix_break_evidence(prev, cur, action="keep", extra={"cache_age": 12_811.4})
    assert ev is not None and ev["cache_age"] == 12_811.4


def test_observe_shot_emits_audit_event(tmp_path: Path, monkeypatch) -> None:
    """集成：observe_shot 在明显断裂时把证据落进审计（隔离到 tmp，绝不动真实根）。"""
    import audit.log as audit_log
    from memory.observe import observe_shot
    from memory.working import WorkingSnapshot

    monkeypatch.setenv("XEYO_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path / "usage"))
    audit_log.reset_default_audit_log()

    snap = WorkingSnapshot(session_id="sess_break_test")
    snap.last_x_sent = _canon(_big("A"))
    snap.last_action = "keep"
    observe_shot(snap, _big("B"), hit=100, miss=900, enabled=True)

    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(x) for x in lines if x.strip()]
    breaks = [e for e in events if e.get("kind") == "wsc.prefix_break"]
    assert len(breaks) == 1, events
    assert breaks[0]["session_id"] == "sess_break_test"
    assert breaks[0]["diff_char"] >= 0
    assert snap.last_x_sent == _canon(_big("B"))  # 取证不影响既有状态更新
    audit_log.reset_default_audit_log()


def test_observe_shot_quiet_on_normal_shot(tmp_path: Path, monkeypatch) -> None:
    import audit.log as audit_log
    from memory.observe import observe_shot
    from memory.working import WorkingSnapshot

    monkeypatch.setenv("XEYO_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("XEYO_USAGE_DIR", str(tmp_path / "usage"))
    audit_log.reset_default_audit_log()

    msgs = _big("A")
    snap = WorkingSnapshot(session_id="sess_break_test2")
    snap.last_x_sent = _canon(msgs)
    snap.last_action = "keep"
    observe_shot(snap, msgs + [{"role": "assistant", "content": "ok"}], hit=900, miss=100, enabled=True)

    path = tmp_path / "audit.jsonl"
    if path.exists():
        events = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        assert not [e for e in events if e.get("kind") == "wsc.prefix_break"], events
    audit_log.reset_default_audit_log()
