"""P1 主会话 inbox 注册表单测：排队/上限/快照/取消/resume/批投/逐条/stuck/租户。"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from server.inbox_registry import (
    InboxQueueFull,
    get_inbox_registry,
)


@pytest.fixture
def reg():
    # 每测新 singleton：清内存态（registry 由 hub/其它测试共享，必须隔离）。
    from server import inbox_registry

    inbox_registry._registry = None
    r = inbox_registry.get_inbox_registry()
    # 关闭依赖外部单例的判活（turn_runner/_pool），测试自控。
    r._session_idle = lambda sid: True  # type: ignore[assignment]
    r._submit = None
    yield r
    inbox_registry._registry = None


def _recorder(*, ok: bool):
    """构造伪 submit_synthetic：记录调用，返回 ``ok``。"""

    calls: list[dict] = []

    async def fake(session_id, user_text, *, surface, extra_headers=None, media_refs=None, message_id=None):
        calls.append({
            "session_id": session_id,
            "text": user_text,
            "surface": surface,
            "media_refs": list(media_refs or []),
            "message_id": message_id,
            "extra_headers": extra_headers,
        })
        return ok

    return fake, calls


def test_enqueue_and_snapshot(reg):
    a = reg.enqueue("s1", "第一件事")
    b = reg.enqueue("s1", "第二件事", media_refs=["img://1"], message_id="mid-2")
    snap = reg.snapshot("s1")
    assert len(snap["items"]) == 2
    assert snap["items"][0]["queue_id"] == a.queue_id
    assert snap["items"][1]["queue_id"] == b.queue_id
    assert snap["items"][0]["position"] == 1
    assert snap["items"][1]["message_id"] == "mid-2"
    assert snap["items"][1]["media_refs"] == ["img://1"]


def test_enqueue_empty_or_full(reg):
    with pytest.raises(ValueError):
        reg.enqueue("s1", "")
    for _ in range(8):
        reg.enqueue("s1", f"msg-{_}")
    with pytest.raises(InboxQueueFull):
        reg.enqueue("s1", "overflow")


def test_pop_all_empties(reg):
    reg.enqueue("s1", "a")
    reg.enqueue("s1", "b")
    items = reg.pop_all("s1")
    assert [i.text for i in items] == ["a", "b"]
    assert reg.snapshot("s1")["items"] == []


def test_pop_front_order(reg):
    reg.enqueue("s1", "a")
    reg.enqueue("s1", "b")
    assert reg.pop_front("s1").text == "a"
    assert reg.pop_front("s1").text == "b"
    assert reg.snapshot("s1")["items"] == []


def test_remove(reg):
    a = reg.enqueue("s1", "a")
    b = reg.enqueue("s1", "b")
    assert reg.remove("s1", a.queue_id) is True
    snap = reg.snapshot("s1")
    assert len(snap["items"]) == 1 and snap["items"][0]["queue_id"] == b.queue_id
    # delivering 态不可取消
    b.state = "delivering"
    assert reg.remove("s1", b.queue_id) is False


def test_resume_clears_stuck(reg):
    it = reg.enqueue("s1", "a")
    it.state = "stuck"
    it.attempts = 3
    reg.resume("s1")
    snap = reg.snapshot("s1")
    assert snap["items"][0]["state"] == "queued"
    assert snap["items"][0]["attempts"] == 0


def test_drain_batch_submits_merged(reg):
    reg.enqueue("s1", "甲", media_refs=["img://1"])
    reg.enqueue("s1", "乙", media_refs=["img://2"], message_id="mid-乙")
    fake, calls = _recorder(ok=True)
    reg._submit = fake
    asyncio.run(reg._drain_batch("s1"))
    assert len(calls) == 1
    assert calls[0]["text"] == "甲\n\n乙"  # 合并为一个轮
    assert calls[0]["media_refs"] == ["img://1", "img://2"]
    assert calls[0]["message_id"] == "mid-乙"  # 取首个非空 message_id
    assert calls[0]["surface"] == "inbox"
    assert reg.snapshot("s1")["items"] == []  # 已消费


def test_drain_batch_reject_requeues_and_stuck(reg):
    # 直接构造 attempts 已达上限-1 的条目：拒绝后应变 stuck。
    it = reg.enqueue("s1", "a")
    it.attempts = 2  # max_attempts 默认 3
    fake, _calls = _recorder(ok=False)
    reg._submit = fake
    asyncio.run(reg._drain_batch("s1"))
    snap = reg.snapshot("s1")
    assert len(snap["items"]) == 1
    assert snap["items"][0]["state"] == "stuck"
    assert snap["items"][0]["attempts"] == 3


def test_drain_one_per_item(reg, monkeypatch):
    monkeypatch.setenv("XEYO_INBOX_COALESCE", "0")
    reg.enqueue("s1", "only", message_id="mid")
    fake, calls = _recorder(ok=True)
    reg._submit = fake
    asyncio.run(reg._drain_one("s1"))
    assert len(calls) == 1
    assert calls[0]["text"] == "only"
    assert calls[0]["message_id"] == "mid"
    assert reg.snapshot("s1")["items"] == []


def test_drain_one_reject_keeps_and_attempts(reg, monkeypatch):
    monkeypatch.setenv("XEYO_INBOX_COALESCE", "0")
    reg.enqueue("s1", "only")
    fake, _calls = _recorder(ok=False)
    reg._submit = fake
    asyncio.run(reg._drain_one("s1"))
    snap = reg.snapshot("s1")
    assert len(snap["items"]) == 1
    assert snap["items"][0]["attempts"] == 1


def test_on_settled_stopped_holds(reg, monkeypatch):
    scheduled = []
    monkeypatch.setattr(reg, "_maybe_schedule", lambda sid: scheduled.append(sid))
    asyncio.run(reg.on_turn_settled("s1", "stopped", "user_stop"))
    assert scheduled == []  # hold：不排水


def test_on_settled_succeeded_schedules(reg, monkeypatch):
    scheduled = []
    monkeypatch.setattr(reg, "_maybe_schedule", lambda sid: scheduled.append(sid))
    asyncio.run(reg.on_turn_settled("s1", "succeeded", ""))
    assert scheduled == ["s1"]


def test_on_settled_failed_schedules(reg, monkeypatch):
    scheduled = []
    monkeypatch.setattr(reg, "_maybe_schedule", lambda sid: scheduled.append(sid))
    asyncio.run(reg.on_turn_settled("s1", "failed", "RuntimeError"))
    assert scheduled == ["s1"]


def test_autorun_off_no_schedule(reg, monkeypatch):
    monkeypatch.setenv("XEYO_INBOX_AUTORUN", "0")
    scheduled = []
    monkeypatch.setattr(reg, "_maybe_schedule", lambda sid: scheduled.append(sid))
    asyncio.run(reg.on_turn_settled("s1", "succeeded", ""))
    assert scheduled == []


def test_drop_session_clears(reg):
    reg.enqueue("s1", "a")
    reg.drop_session("s1")
    assert reg.snapshot("s1")["items"] == []
    assert reg.counts()["pending"] == 0


def test_counts_stuck(reg):
    it = reg.enqueue("s1", "a")
    it.state = "stuck"
    c = reg.counts()
    assert c["pending"] == 1
    assert c["stuck"] == 1
