"""T_now 管道 1 契约测试：运行中用户消息的边界注入（steer）。

冻结口径：
- 入队只存事实（文本 / 媒体 / 客户端消息 id），不改写用户文本；
- 只在**边界**投递（调用方 ``engine/query_loop`` 负责时机）：drain 取走即清，
  绝不重复投递；
- 投递物是**真 user 消息**（role=user）——不进 system、不伪装 assistant；
- 有界 + fail-open：队列满丢最新并告警，绝不因引导队列故障影响主链路。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import t_now_steer
from engine.t_now_steer import (
	MAX_QUEUED_PER_SESSION,
	MAX_SESSIONS,
	clear,
	drain,
	pending_count,
	push,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
	# 入队即写 transcript（WAL）——测试必须隔离会话目录，别碰真实 ~/.xeyo
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path))
	clear()
	yield
	clear()


def test_push_then_boundary_drain_yields_real_user_message():
	assert push("s1", "先别动文件，只读一遍") is True
	assert pending_count("s1") == 1
	msgs = drain("s1")
	assert len(msgs) == 1
	m = msgs[0]
	# 说话人身份由消息结构保证：这是真 user 消息
	assert m.role == "user"
	assert m.content == "先别动文件，只读一遍"
	# 取走即清：不会重复投递
	assert pending_count("s1") == 0
	assert drain("s1") == []


def test_message_id_and_images_passthrough():
	push(
		"s1",
		"看图",
		images=["data:image/png;base64,AAA", "not-a-media"],
		message_id="m-123",
	)
	m = drain("s1")[0]
	assert m.id == "m-123"
	assert isinstance(m.content, list)
	blocks = [b for b in m.content if isinstance(b, dict)]
	assert [b["type"] for b in blocks] == ["text", "image_url"]
	# 非媒体字符串不进消息体
	assert all("not-a-media" not in str(b) for b in blocks)


def test_empty_input_is_rejected():
	assert push("s1", "") is False
	assert push("", "文本") is False
	assert push("s1", "   ") is False
	assert pending_count("s1") == 0


def test_sessions_are_isolated():
	push("a", "A 的话")
	push("b", "B 的话")
	assert [m.content for m in drain("a")] == ["A 的话"]
	assert [m.content for m in drain("b")] == ["B 的话"]


def test_queue_is_bounded():
	for i in range(MAX_QUEUED_PER_SESSION):
		assert push("s1", f"msg-{i}") is True
	# 超限：丢弃最新并返回 False（不抛、不阻塞主链路）
	assert push("s1", "overflow") is False
	assert pending_count("s1") == MAX_QUEUED_PER_SESSION
	assert len(drain("s1")) == MAX_QUEUED_PER_SESSION


def test_sessions_bounded_never_drops_queued_messages():
	"""会话数硬顶只淘汰**空队列**会话：排队中的消息永不因 LRU 被丢。"""
	clear()
	for i in range(MAX_SESSIONS + 3):
		push(f"s-{i}", "hi")
	# 每个会话都非空 ⇒ 宁可超顶，也不丢消息
	assert pending_count("s-0") == 1
	assert pending_count(f"s-{MAX_SESSIONS + 2}") == 1
	# 空队列会话才会被淘汰
	clear("s-1")
	push(f"s-new-{MAX_SESSIONS + 5}", "hi")
	assert pending_count("s-1") == 0


def test_fifo_order_preserved():
	for i in range(3):
		push("s1", f"第{i}条")
	assert [m.content for m in drain("s1")] == ["第0条", "第1条", "第2条"]


def test_fail_open_on_broken_queue(monkeypatch):
	# 内部异常不得抛出（引导是旁路，不能拖垮主链路）
	class _Boom(dict):
		def get(self, *_a, **_k):  # noqa: D102
			raise RuntimeError("boom")

	monkeypatch.setattr(t_now_steer, "_QUEUES", _Boom())
	assert push("s1", "文本") is False
	assert drain("s1") == []


def test_clear_specific_and_all():
	push("a", "A")
	push("b", "B")
	clear("a")
	assert pending_count("a") == 0
	assert pending_count("b") == 1
	clear()
	assert pending_count("b") == 0


# ------------------------------------------------- 至少一次 + 幂等 + WAL（可靠性）


def test_deliver_appends_real_user_message_and_is_idempotent():
	from session.message_store import MessageStore

	from engine.t_now_steer import deliver

	push("s1", "先只读，别改文件", message_id="m-1")
	store = MessageStore()
	assert len(deliver("s1", store)) == 1
	assert store.items[0].role == "user"
	assert store.items[0].id == "m-1"
	# 幂等：同 message_id 已在历史里 → 重投不重复追加
	push("s1", "先只读，别改文件", message_id="m-1")
	assert deliver("s1", store) == []
	assert len(store) == 1


def test_deliver_requeues_on_append_failure():
	from engine.t_now_steer import deliver

	class _Boom:
		items: list = []

		def append(self, _m):  # noqa: ANN001
			raise RuntimeError("store down")

	push("s1", "别动文件")
	assert deliver("s1", _Boom()) == []
	# 投递失败 → 回队（不丢），下一边界重投
	assert pending_count("s1") == 1


def test_push_writes_wal_transcript():
	from session.persistence import transcript_path
	from session.record_transcript import load_transcript

	push("s-wal", "落盘这条", message_id="m-wal")
	rows = load_transcript(transcript_path("s-wal"))
	assert any(r.get("content") == "落盘这条" for r in rows)
	assert any(str(r.get("id") or "") == "m-wal" for r in rows)


def test_push_without_message_id_reuses_wal_identity_for_delivery():
	from engine.t_now_steer import deliver
	from session.message_store import MessageStore
	from session.persistence import transcript_path
	from session.record_transcript import load_transcript

	assert push("s-auto-id", "身份只生成一次") is True
	wal_rows = [
		r for r in load_transcript(transcript_path("s-auto-id"))
		if r.get("content") == "身份只生成一次"
	]
	assert len(wal_rows) == 1
	wal_id = str(wal_rows[0].get("id") or "")
	assert wal_id

	added = deliver("s-auto-id", MessageStore())
	assert len(added) == 1
	assert added[0].id == wal_id
	assert len(
		[
			r
			for r in load_transcript(transcript_path("s-auto-id"))
			if r.get("content") == "身份只生成一次"
		]
	) == 1
