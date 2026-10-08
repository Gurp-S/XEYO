"""引导（steer）settle 兜底：滞留项转入 inbox 投递的单测。

事故原型（2026-09-30）：回合在下一次采样前结束 ⇒ steer 队列里的消息既没进
模型输入（``deliver`` 只挂边界），也没有 inbox 兜底（settle 只排 inbox）⇒
「已回 202 + toast 承诺边界投递」但模型整轮没见过它，且 GUI 无任何指示。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest


@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
    from server import inbox_registry

    inbox_registry._registry = None
    r = inbox_registry.get_inbox_registry()
    r._session_idle = lambda sid: True  # type: ignore[assignment]
    yield r
    inbox_registry._registry = None


@pytest.fixture
def steer():
    from engine import t_now_steer

    t_now_steer.clear()
    yield t_now_steer
    t_now_steer.clear()


def test_fallback_moves_pending_steer_into_inbox(reg, steer):
    assert steer.push("s1", "插话一", message_id="mid-1") is True
    from server.steer_settle_fallback import fallback_pending

    assert fallback_pending("s1") == 1
    # 引导队列已交空；条目按原 message_id / 文本 / 状态落进 inbox。
    assert steer.pending_count("s1") == 0
    items = reg.snapshot("s1")["items"]
    assert [it["text"] for it in items] == ["插话一"]
    assert items[0]["message_id"] == "mid-1"
    assert items[0]["state"] == "queued"


def test_fallback_preserves_order_and_media(reg, steer):
    steer.push("s1", "一", message_id="m1", images=["img://a"])
    steer.push("s1", "二", message_id="m2")
    from server.steer_settle_fallback import fallback_pending

    assert fallback_pending("s1") == 2
    items = reg.snapshot("s1")["items"]
    assert [it["text"] for it in items] == ["一", "二"]
    assert items[0]["media_refs"] == ["img://a"]


def test_fallback_is_noop_without_pending(reg, steer):
    from server.steer_settle_fallback import fallback_pending

    assert fallback_pending("s1") == 0
    assert reg.snapshot("s1")["items"] == []


def test_settle_stopped_holds_pending_steer(reg, steer, monkeypatch):
    """用户主动停回合：保持 hold（与 inbox 同口径），不自动续跑。"""
    monkeypatch.setenv("XEYO_INBOX_AUTORUN", "0")
    steer.push("s1", "停回合时未送达", message_id="mid-hold")
    from server.steer_settle_fallback import on_turn_settled

    asyncio.run(on_turn_settled("s1", "stopped", "user_stop"))
    assert steer.pending_count("s1") == 0
    snapshot = reg.snapshot("s1")
    assert snapshot["paused"] is True
    assert snapshot["items"][0]["text"] == "停回合时未送达"
    assert snapshot["items"][0]["state"] == "queued"


def test_settle_succeeded_moves_into_inbox(reg, steer, monkeypatch):
    """正常结束（succeeded/failed）走兜底；autorun 关时只转不投（等手动 resume）。"""
    monkeypatch.setenv("XEYO_INBOX_AUTORUN", "0")
    steer.push("s1", "终答后滞留", message_id="mid-end")
    from server.steer_settle_fallback import on_turn_settled

    asyncio.run(on_turn_settled("s1", "succeeded", "end_turn"))
    assert steer.pending_count("s1") == 0
    items = reg.snapshot("s1")["items"]
    assert [it["text"] for it in items] == ["终答后滞留"]
    assert items[0]["state"] == "queued"


def test_queue_full_keeps_steer_item(reg, steer, monkeypatch):
    """inbox 满：条目原样放回 steer 队首，绝不丢。"""
    monkeypatch.setenv("XEYO_INBOX_MAX_QUEUED", "1")
    reg.enqueue("s1", "已占位", message_id="mid-occupied")
    steer.push("s1", "进不去", message_id="mid-full")
    from server.steer_settle_fallback import fallback_pending

    assert fallback_pending("s1") == 0
    assert steer.pending_count("s1") == 1
    assert [it["text"] for it in reg.snapshot("s1")["items"]] == ["已占位"]


def test_fallback_skips_when_steer_already_delivered(reg, steer):
    """已在上一边界送达（队列为空）⇒ 兜底是 no-op，不产生重复投递。"""
    from server.steer_settle_fallback import fallback_pending

    assert steer.pending_count("s1") == 0
    assert fallback_pending("s1") == 0
    assert reg.snapshot("s1")["items"] == []
