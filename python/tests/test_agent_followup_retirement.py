"""F7：已消费 follow-up 的 meta 退休 + 双存储（meta/运行时）计数与重投配对。

根因链：retry 把 meta.pending_followups 放回运行时队列，消费后 meta 无清除点——
① /agents 计数把已消费项一直算在内（幽灵）；② 下一次 retry 把同一条再投一次
（重放），且 abort 窗口里两处各一份会被送成两条。修法 A：消费点退休 +
retry 多重集配对 + 并集计数。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import engine.live_agents as la
from engine import subagent_runner as sr


@pytest.fixture(autouse=True)
def _clean():
	la.clear_all_for_tests()
	yield
	la.clear_all_for_tests()


@pytest.fixture()
def side(tmp_path, monkeypatch):
	monkeypatch.setattr(sr, "_sidechain_dir", lambda _sid: tmp_path / "agents")
	return tmp_path / "agents"


def _meta(aid: str = "agent-f7") -> dict:
	return json.loads(sr._meta_path("sess-f7", aid).read_text(encoding="utf-8"))


def _seed(aid: str = "agent-f7", pending=("A", "B"), tokens: int = 42) -> None:
	sr.upsert_subagent_meta(
		"sess-f7",
		agent_id=aid,
		task_desc="任务F7",
		status="done",
		tokens_used=tokens,
		pending_followups=list(pending),
	)


def test_retire_removes_only_consumed_and_preserves_meta(side):
	_seed(pending=["A", "B"])
	sr.retire_consumed_followups("sess-f7", "agent-f7", ["A"])
	m = _meta()
	assert m["pending_followups"] == ["B"]
	assert m["task_desc"] == "任务F7"
	assert m["status"] == "done"
	assert m["tokens_used"] == 42


def test_retire_absent_text_is_noop(side):
	# 无 meta 文件：退休不凭空造文件
	sr.retire_consumed_followups("sess-f7", "agent-f7", ["X"])
	assert not sr._meta_path("sess-f7", "agent-f7").is_file()
	# 有 meta 但文本缺席：列表不动
	_seed(pending=["B"])
	sr.retire_consumed_followups("sess-f7", "agent-f7", ["X"])
	assert _meta()["pending_followups"] == ["B"]


def test_retire_one_instance_of_duplicates(side):
	_seed(pending=["A", "A"])
	sr.retire_consumed_followups("sess-f7", "agent-f7", ["A"])
	assert _meta()["pending_followups"] == ["A"]


def test_retire_corrupt_meta_is_silent(side):
	path = sr._meta_path("sess-f7", "agent-f7")
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text("{not json", encoding="utf-8")
	sr.retire_consumed_followups("sess-f7", "agent-f7", ["A"])  # 不抛
	assert path.read_text(encoding="utf-8") == "{not json"


def test_consume_parked_followup_retires_and_keeps_rest(side):
	from session.message_store import MessageStore

	_seed(pending=["A", "B"])
	la.post_to_agent("sess-f7", "agent-f7", "A")
	la.post_to_agent("sess-f7", "agent-f7", "B")
	store = MessageStore()
	assert sr._consume_parked_followup("sess-f7", "agent-f7", store) is True
	# 消费了 A：transcript 一条、运行时剩 B、meta 退休 A
	assert len(store.items) == 1
	assert la.inbox_texts("sess-f7", "agent-f7") == ["B"]
	assert _meta()["pending_followups"] == ["B"]
	assert sr._consume_parked_followup("sess-f7", "agent-f7", store) is True
	assert len(store.items) == 2
	assert _meta()["pending_followups"] == []
	assert sr._consume_parked_followup("sess-f7", "agent-f7", store) is False


def test_reattach_pairs_duplicate_copy(side):
	from server.routers.sessions import _reattach_pending_followups

	# abort 窗口：retry 放回后未消费 —— 运行时与 meta 各有一份
	la.post_to_agent("sess-f7", "agent-f7", "A")
	la.post_to_agent("sess-f7", "agent-f7", "B")
	n = _reattach_pending_followups("sess-f7", "agent-f7", ["A", "B"])
	assert n == 2
	assert la.inbox_texts("sess-f7", "agent-f7") == ["A", "B"]  # 两条，不翻倍


def test_reattach_leftover_first_then_meta_only(side):
	from server.routers.sessions import _reattach_pending_followups

	la.post_to_agent("sess-f7", "agent-f7", "B")  # 更早排队的残留
	_reattach_pending_followups("sess-f7", "agent-f7", ["A", "B"])
	assert la.inbox_texts("sess-f7", "agent-f7") == ["B", "A"]


def test_second_retry_no_replay(side):
	from server.routers.sessions import _reattach_pending_followups
	from session.message_store import MessageStore

	_seed(pending=["A"])
	# retry#1：放回 → 消费（退休）
	assert _reattach_pending_followups("sess-f7", "agent-f7", ["A"]) == 1
	store = MessageStore()
	assert sr._consume_parked_followup("sess-f7", "agent-f7", store) is True
	assert _meta()["pending_followups"] == []
	# retry#2：无残留、无 meta 待办 → 零投递（旧行为：A 再送一遍）
	n = _reattach_pending_followups(
		"sess-f7", "agent-f7", _meta()["pending_followups"]
	)
	assert n == 0
	assert la.inbox_texts("sess-f7", "agent-f7") == []


def test_combined_inbox_count_dedups(side):
	from server.routers.sessions import _combined_inbox_count

	la.post_to_agent("sess-f7", "agent-f7", "A")
	la.post_to_agent("sess-f7", "agent-f7", "B")
	assert _combined_inbox_count("sess-f7", "agent-f7", ["A", "B"]) == 2  # 不是 4
	assert _combined_inbox_count("sess-f7", "agent-f7", ["A", "B", "C"]) == 3
	assert _combined_inbox_count("sess-f7", "agent-f7", []) == 2


def test_routes_roundtrip_retire_and_delete(side):
	"""路由级：投递 → 计数 → 消费退休 → 计数归零；删除连运行时残留一起清。"""
	from server.routers.sessions import (
		AgentFollowupRequest,
		session_agent_followup,
		session_agent_followup_remove,
		session_agents,
	)

	r = session_agent_followup("sess-f7", "agent-f7", AgentFollowupRequest(text="A"))
	assert r["deliver"] == "pending"
	assert r["inboxCount"] == 1
	assert _meta()["pending_followups"] == ["A"]

	# 造 desync：retry 放回后 abort —— 运行时也有同文本一份
	la.post_to_agent("sess-f7", "agent-f7", "A")
	agents = session_agents("sess-f7")["agents"]
	assert agents[0]["inboxCount"] == 1  # 两份 = 一条，不虚报 2

	# 删除：meta 与运行时残留一起清，不复活
	rm = session_agent_followup_remove("sess-f7", "agent-f7", "A")
	assert rm["removed"] is True
	assert rm["inboxCount"] == 0
	assert la.inbox_texts("sess-f7", "agent-f7") == []
	assert _meta()["pending_followups"] == []

	# 消费退休路径：再投一条、直接消费 → 计数归零（旧行为：一直挂着）
	session_agent_followup("sess-f7", "agent-f7", AgentFollowupRequest(text="B"))
	from session.message_store import MessageStore

	la.post_to_agent("sess-f7", "agent-f7", "B")  # 模拟 retry 放回
	store = MessageStore()
	assert sr._consume_parked_followup("sess-f7", "agent-f7", store) is True
	assert _meta()["pending_followups"] == []
	assert session_agents("sess-f7")["agents"][0]["inboxCount"] == 0
