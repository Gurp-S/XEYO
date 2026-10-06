"""inbox 排队消息的**边界投递**（2026-09-20 事故回归）。

事故面：忙时消息进 inbox，而 inbox 只在 ``on_turn_settled`` 投递 ⇒ 长回合
（读—改—读）不 settle 时用户消息整轮进不了模型输入。回归口径：
1) 边界取件只拿非 stuck 项、stuck 留在队内；
2) 边界投递把消息变成真 user 消息进 store，且 inbox 不再持有它（settle 不重投）；
3) steer 队列满（push False）时原样放回 inbox，不丢消息、不计 attempts。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import t_now_inbox, t_now_steer  # noqa: E402
from server.inbox_registry import InboxRegistry  # noqa: E402
from session.message_store import MessageStore  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_persistence(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))


def _fresh_registry() -> InboxRegistry:
	return InboxRegistry()


@pytest.fixture
def boundary_on(monkeypatch):
	"""本文件测「边界声道」本身；该声道 2026-09-30 起默认关（对齐市面排队语义），
	故用例显式打开——默认值由 ``test_boundary_channel_off_by_default`` 钉住。"""
	monkeypatch.setenv("XEYO_INBOX_BOUNDARY", "1")


def test_consume_for_boundary_takes_active_and_leaves_stuck() -> None:
	reg = _fresh_registry()
	reg.enqueue("s1", "第一条")
	second = reg.enqueue("s1", "第二条")
	second.state = "stuck"

	got = reg.consume_for_boundary("s1")

	assert [it.text for it in got] == ["第一条"]
	assert reg.peek("s1") is second
	assert reg.consume_for_boundary("") == []


def test_boundary_delivery_lands_in_store_and_clears_inbox(monkeypatch, boundary_on) -> None:
	reg = _fresh_registry()
	reg.enqueue("s1", "停一下，先回答我的问题", message_id="m1")
	monkeypatch.setattr(t_now_inbox, "_registry", lambda: reg)
	store = MessageStore()

	added = t_now_inbox.deliver_queued_users("s1", store)

	assert len(added) == 1
	assert len(store.items) == 1
	assert store.items[0].id == "m1"
	# 已投递 ⇒ inbox 里没有残留（settle 侧不会再合成一轮）
	assert reg.consume_for_boundary("s1") == []


def test_boundary_delivery_idempotent_on_same_message_id(monkeypatch, boundary_on) -> None:
	reg = _fresh_registry()
	reg.enqueue("s1", "再来一次", message_id="m2")
	monkeypatch.setattr(t_now_inbox, "_registry", lambda: reg)
	store = MessageStore()

	first = t_now_inbox.deliver_queued_users("s1", store)
	reg.enqueue("s1", "再来一次", message_id="m2")
	second = t_now_inbox.deliver_queued_users("s1", store)

	assert len(first) == 1
	# 幂等：不二次追加；但第二次仍要报"已进模型输入"，否则边界回执发不出去、
	# 前端的排队卡撤不掉（返回语义 2026-09-22 起 = 已落地，不是"新追加"）。
	assert [m.id for m in second] == ["m2"]
	assert len(store.items) == 1


def test_push_failure_restores_items_without_attempt_bump(monkeypatch, boundary_on) -> None:
	reg = _fresh_registry()
	item = reg.enqueue("s1", "排队中", message_id="m3")
	monkeypatch.setattr(t_now_inbox, "_registry", lambda: reg)
	monkeypatch.setattr(t_now_steer, "push", lambda *a, **k: False)

	added = t_now_inbox.deliver_queued_users("s1", MessageStore())

	assert added == []
	assert reg.peek("s1") is item
	assert item.attempts == 0
	assert item.state == "queued"


def test_boundary_channel_can_be_disabled(monkeypatch) -> None:
	reg = _fresh_registry()
	reg.enqueue("s1", "别投", message_id="m4")
	monkeypatch.setattr(t_now_inbox, "_registry", lambda: reg)
	monkeypatch.setenv("XEYO_INBOX_BOUNDARY", "0")

	assert t_now_inbox.deliver_queued_users("s1", MessageStore()) == []
	assert reg.peek("s1") is not None


def test_boundary_channel_off_by_default(monkeypatch) -> None:
	"""默认不中途投递（2026-09-30 对齐市面）：排队 = 回合结束后投递。

	Codex 队列文案 ``Messages to be submitted at end of turn``（另有显式
	``turn/steer``）、Claude Code 的统一命令队列只在 query idle 时消费。边界声道
	默认关 ⇒ 排队消息留在 inbox 等 settle 排水；要中途注入用 Ctrl+Enter 引导。
	"""
	reg = _fresh_registry()
	reg.enqueue("s1", "排队到回合结束后投递", message_id="m-default")
	monkeypatch.setattr(t_now_inbox, "_registry", lambda: reg)
	monkeypatch.delenv("XEYO_INBOX_BOUNDARY", raising=False)

	assert t_now_inbox.deliver_queued_users("s1", MessageStore()) == []
	assert reg.peek("s1") is not None
