"""P2 子 agent follow-up inbox 单测：park/排空/计数/移除 + 续跑触发文本。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import engine.live_agents as la


@pytest.fixture(autouse=True)
def _clean():
    la.clear_all_for_tests()
    yield
    la.clear_all_for_tests()


def test_post_and_count():
    n = la.post_to_agent("s1", "a1", "帮我检查 b 文件")
    assert n == 1
    assert la.inbox_count("s1", "a1") == 1
    la.post_to_agent("s1", "a1", "再看 c")
    assert la.inbox_count("s1", "a1") == 2


def test_post_empty_rejected():
    assert la.post_to_agent("s1", "a1", "   ") == -1
    assert la.post_to_agent("", "a1", "hi") == -1
    assert la.inbox_count("s1", "a1") == 0


def test_drain_atomic():
    la.post_to_agent("s1", "a1", "one", message_id="m1")
    la.post_to_agent("s1", "a1", "two", message_id="m2")
    items = la.drain_agent_inbox("s1", "a1")
    assert [i["text"] for i in items] == ["one", "two"]
    assert la.inbox_count("s1", "a1") == 0  # 原子取空


def test_remove_by_message_id():
    la.post_to_agent("s1", "a1", "one", message_id="m1")
    la.post_to_agent("s1", "a1", "two", message_id="m2")
    assert la.remove_agent_inbox_item("s1", "a1", "m1") is True
    assert la.inbox_count("s1", "a1") == 1
    assert la.drain_agent_inbox("s1", "a1")[0]["text"] == "two"


def test_remove_first_when_no_id():
    la.post_to_agent("s1", "a1", "one")
    la.post_to_agent("s1", "a1", "two")
    assert la.remove_agent_inbox_item("s1", "a1", "") is True
    assert la.drain_agent_inbox("s1", "a1")[0]["text"] == "two"


def test_clear_agent_inbox():
    la.post_to_agent("s1", "a1", "one")
    la.clear_agent_inbox("s1", "a1")
    assert la.inbox_count("s1", "a1") == 0


def test_isolation_between_sessions():
    la.post_to_agent("s1", "a1", "one")
    assert la.inbox_count("s2", "a1") == 0


def test_followup_user_text_format():
    from engine.subagent_runner import _followup_user_text

    t = _followup_user_text("  修一下  ")
    assert t.startswith("[Resume] Continue.")
    assert "User follow-up:" in t
    assert "修一下" in t


def test_followup_env_budgets(monkeypatch):
    from engine.subagent_runner import _followup_limit, _followup_max_turns

    monkeypatch.setenv("XEYO_SUB_FOLLOWUP_LIMIT", "5")
    assert _followup_limit() == 5
    monkeypatch.setenv("XEYO_SUB_FOLLOWUP_MAX_TURNS", "9")
    assert _followup_max_turns() == 9
