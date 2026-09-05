"""A2 retrieve 还原：C2 压缩抓拍 → Memory(action=retrieve) 字节级找回。"""

from __future__ import annotations

import pytest

from memory import runtime
from memory.working import WorkingSnapshot

STACK = (
    "Traceback (most recent call last):\n"
    '  File "cfg.py", line 7, in load\n'
    "    theta = raw[\"theta\"]\n"
    "KeyError: theta\n"
)


def _messages() -> list[dict]:
    msgs: list[dict] = []
    msgs.append(
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "u1",
                    "name": "Read",
                    "input": {"file_path": "D:/proj/cfg.py"},
                }
            ],
        }
    )
    msgs.append(
        {
            "role": "tool",
            "tool_call_id": "u1",
            "content": [{"type": "tool_result", "tool_use_id": "u1", "content": STACK}],
        }
    )
    msgs.append(
        {
            "role": "tool",
            "tool_call_id": "u2",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "u2",
                    "content": "noise\n" * 40 + "theta = 0.5\nalpha_hit = 0.95\n",
                }
            ],
        }
    )
    return msgs


@pytest.fixture()
def mem_env(tmp_path, monkeypatch):
    monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / "mem"))
    # 开关走 settings.memory（get_value）：隔离 XEYO_HOME/XEYO_CWD，避免读到真实配置
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XEYO_CWD", str(tmp_path))
    return tmp_path / "mem"


def test_compress_stores_fragments_and_retrieve_restores(mem_env, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    working = WorkingSnapshot(session_id="sess_restore1")
    working.compact_cursor = 3
    proj = runtime.apply_c2_messages(_messages(), working)
    summary = proj[0]["content"]
    assert "[C2] 逃生舱" in summary  # 栈也在场（A3）

    from memory import memindex

    rows = memindex.get_fragments("sess_restore1", 1)
    kinds = {r["kind"] for r in rows}
    assert "stack" in kinds
    stack_text = next(r["text"] for r in rows if r["kind"] == "stack")
    assert stack_text == STACK  # 字节级还原（无截断损失）


def test_memory_tool_retrieve_action(mem_env, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    working = WorkingSnapshot(session_id="sess_restore2")
    working.compact_cursor = 3
    runtime.apply_c2_messages(_messages(), working)

    from tools.memory_tool.memory_tool import MemoryTool

    tool = MemoryTool(cwd=str(tmp_path))
    tool.set_session_id("sess_restore2")
    out = tool._execute_retrieve({"id": "notes:msg:1"})
    assert "KeyError: theta" in out.content
    assert "[stack]" in out.content
    # 非法 id
    bad = tool._execute_retrieve({"id": "whatever"})
    assert bad.is_error
    # 无记录
    empty = tool._execute_retrieve({"id": "notes:msg:999"})
    assert "no fragments" in empty.content


def test_restore_fixed_on(tmp_path, monkeypatch):
    """A2 碎片还原已固化开启：settings 写 0 被拒绝（键已出注册表）。"""
    monkeypatch.chdir(tmp_path)
    from memory import memory_switches

    with pytest.raises(ValueError):
        memory_switches.save({"XEYO_MEMORY_RESTORE": "0"}, cwd=str(tmp_path))
    from memory import memindex

    assert memindex.restore_enabled() is True


def test_schema_declares_retrieve():
    from tools.memory_tool.memory_tool import MemoryTool

    tool = MemoryTool(cwd=".")
    schema = tool.schema() if hasattr(tool, "schema") else tool.schemas()
    assert "retrieve" in str(schema)
