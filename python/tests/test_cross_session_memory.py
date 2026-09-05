"""跨会话共享记忆：search_session_notes / Memory 工具跨会话段 / peer 话题。

- 记忆 memdir 按 workspace_id 隔离（同工作区天然共享）；
- 会话级记忆（L5b session.md）默认只回灌本会话 —— search 逻辑修改后，
  同工作区其他对话的 session notes 可被检索并带会话归属返回。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from memory.search import search_session_notes
from memory.session_md import path_for as session_md_path
from session.ws_index import record_session_workspace, reset_for_tests


@pytest.fixture()
def sessions_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 sessions 目录重定向到 tmp，并重置索引缓存。"""
    root = tmp_path / "sessions"
    root.mkdir()
    monkeypatch.setenv("XEYO_SESSIONS_DIR", str(root))
    reset_for_tests()
    return root


def _write_session_note(sid: str, goal: str, current: str = "(none)") -> None:
    path = session_md_path(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Session\n## Goal\n"
        f"{goal}\n## Current state\n{current}\n## Completed\n(none)\n"
        "## Important discoveries\n(none yet)\n## Key facts\n(none yet)\n"
        "## Open questions\n(none)\n## Next action\n(continue)\n",
        encoding="utf-8",
    )


def test_peer_session_note_found_same_workspace(sessions_env: Path, tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    record_session_workspace("sess-aaaa", str(ws))
    record_session_workspace("sess-bbbb", str(ws))
    _write_session_note("sess-aaaa", "把 PostgreSQL 17 升级计划定稿")

    hits = search_session_notes(
        "PostgreSQL", cwd=str(ws), self_session_id="sess-bbbb"
    )
    assert len(hits) == 1
    assert hits[0].session_id == "sess-aaaa"
    assert "PostgreSQL" in hits[0].excerpt or "PostgreSQL" in hits[0].title


def test_self_and_other_workspace_excluded(sessions_env: Path, tmp_path: Path) -> None:
    ws_a = tmp_path / "a"
    ws_b = tmp_path / "b"
    ws_a.mkdir()
    ws_b.mkdir()
    record_session_workspace("sess-self", str(ws_a))
    record_session_workspace("sess-peer", str(ws_a))
    record_session_workspace("sess-other-ws", str(ws_b))
    _write_session_note("sess-self", "本会话的私密话题 xyzzy")
    _write_session_note("sess-peer", "邻居会话的 xyzzy 话题")
    _write_session_note("sess-other-ws", "别的工作区的 xyzzy 话题")

    hits = search_session_notes("xyzzy", cwd=str(ws_a), self_session_id="sess-self")
    assert [h.session_id for h in hits] == ["sess-peer"]


def test_subagent_scoped_sessions_are_not_peers(sessions_env: Path, tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    record_session_workspace("sess-main", str(ws))
    record_session_workspace("sess-main__agent__worker", str(ws))
    _write_session_note("sess-main__agent__worker", "侧链内部话题 qqq")

    # 主会话检索：自己的子 agent 侧链不算「别的对话」。
    hits = search_session_notes("qqq", cwd=str(ws), self_session_id="sess-main")
    assert hits == []


def test_unmatched_query_returns_empty(sessions_env: Path, tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    record_session_workspace("sess-aaaa", str(ws))
    _write_session_note("sess-aaaa", "数据库迁移计划")
    assert search_session_notes("完全无关的查询词", cwd=str(ws)) == []


def test_memory_tool_search_includes_cross_session_section(
    sessions_env: Path, tmp_path: Path
) -> None:
    from tools.memory_tool.memory_tool import MemoryTool

    ws = tmp_path / "proj"
    ws.mkdir()
    record_session_workspace("sess-aaaa", str(ws))
    record_session_workspace("sess-bbbb", str(ws))
    _write_session_note("sess-aaaa", "部署脚本要用 Python 3.11")

    tool = MemoryTool(cwd=str(ws))
    tool.set_session_id("sess-bbbb")
    from engine.abort import AbortController

    result = asyncio.run(
        tool.execute({"action": "search", "query": "Python 3.11"}, AbortController())
    )
    assert result.is_error is False
    assert "跨会话记忆" in result.content
    assert "sess-aaaa" in result.content


def test_memory_tool_peers_lists_topic(
    sessions_env: Path, tmp_path: Path
) -> None:
    """peer 话题工具化：Memory(action=peers) 返回结构化在场 + 正在聊话题。"""
    from engine.abort import AbortController
    from engine.session_presence import (
        default_session_presence,
        reset_session_presence_for_tests,
    )
    from tools.memory_tool.memory_tool import MemoryTool

    ws = tmp_path / "proj"
    ws.mkdir()
    record_session_workspace("sess-self", str(ws))
    record_session_workspace("sess-peer", str(ws))
    _write_session_note("sess-peer", "重构滚动条跟尾逻辑")
    reset_session_presence_for_tests()
    default_session_presence().touch_busy(
        str(ws), "sess-peer", busy=True, title="邻居对话"
    )

    tool = MemoryTool(cwd=str(ws))
    tool.set_session_id("sess-self")
    result = asyncio.run(tool.execute({"action": "peers"}, AbortController()))
    assert result.is_error is False
    assert "同工作区其他会话（1）:" in result.content
    assert "会话「邻居对话」" in result.content
    assert "忙碌中" in result.content
    assert "正在聊: 重构滚动条跟尾逻辑" in result.content
    assert "另有" not in result.content  # beacon 措辞属于 T_now，不进工具结果


def test_memory_tool_peers_subagent_context_empty(
    sessions_env: Path, tmp_path: Path
) -> None:
    """T14 净化清单：子代理上下文 action=peers 返回空，不见 peer presence。"""
    from engine.abort import AbortController
    from engine.session_presence import (
        default_session_presence,
        reset_session_presence_for_tests,
    )
    from tools.memory_tool.memory_tool import MemoryTool

    ws = tmp_path / "proj"
    ws.mkdir()
    record_session_workspace("sess-self", str(ws))
    _write_session_note("sess-peer", "邻居会话的隐秘话题 zzz")
    reset_session_presence_for_tests()
    default_session_presence().touch_busy(
        str(ws), "sess-peer", busy=True, title="邻居对话"
    )

    tool = MemoryTool(cwd=str(ws))
    tool.set_session_id("sess-self")
    tool.set_agent_id("agent-sub-1")
    result = asyncio.run(tool.execute({"action": "peers"}, AbortController()))
    assert result.is_error is False
    assert result.content == "(no peers)"


def test_memory_tool_peers_excludes_same_tree(
    sessions_env: Path, tmp_path: Path
) -> None:
    """同会话树（主会话 + 子 agent）不算其他会话。"""
    from engine.abort import AbortController
    from engine.session_presence import (
        default_session_presence,
        reset_session_presence_for_tests,
    )
    from tools.memory_tool.memory_tool import MemoryTool

    ws = tmp_path / "proj"
    ws.mkdir()
    record_session_workspace("sess-main", str(ws))
    record_session_workspace("sess-main__agent__worker", str(ws))
    _write_session_note("sess-main__agent__worker", "侧链内部话题 ppp")
    reset_session_presence_for_tests()
    default_session_presence().touch_busy(
        str(ws), "sess-main__agent__worker", busy=True, title="侧链"
    )

    tool = MemoryTool(cwd=str(ws))
    tool.set_session_id("sess-main")
    result = asyncio.run(tool.execute({"action": "peers"}, AbortController()))
    assert result.content == "(no peers)"


def test_peer_activity_block_no_longer_carries_topic(
    sessions_env: Path, tmp_path: Path
) -> None:
    """推送面收敛：块里不再有「正在聊:」话题行（明细改走 Memory 工具）。"""
    from engine.session_presence import (
        peer_activity_block,
        reset_session_presence_for_tests,
    )

    ws = tmp_path / "proj"
    ws.mkdir()
    reg = reset_session_presence_for_tests()
    reg.touch_busy(str(ws), "sess-peer", busy=True, title="邻居对话")
    _write_session_note("sess-peer", "重构滚动条跟尾逻辑")

    block = peer_activity_block(str(ws), "sess-self")
    assert "另有 1 个会话运行中" in block
    assert "Memory(action=peers / search)" in block
    assert "正在聊:" not in block
    assert "重构滚动条跟尾逻辑" not in block
    assert "邻居对话" not in block
