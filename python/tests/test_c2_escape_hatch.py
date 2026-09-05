"""A3 C2 逃生舱：最近 1 条完整 Traceback + 最后 3 个文件路径不可被压缩。"""

from __future__ import annotations

import pytest

from memory import runtime
from memory.working import WorkingSnapshot


def _tool_result_msg(i: int, text: str) -> dict:
    return {
        "role": "tool",
        "tool_call_id": f"c{i}",
        "content": [{"type": "tool_result", "tool_use_id": f"c{i}", "content": text}],
    }


def _tool_use_msg(i: int, name: str, **inp) -> dict:
    return {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": f"c{i}", "name": name, "input": dict(inp)}
        ],
    }


STACK = (
    "Traceback (most recent call last):\n"
    '  File "app.py", line 42, in run\n'
    "    theta = cfg[\"theta\"]\n"
    "KeyError: theta\n"
)


def _left_with_hatch_facts() -> list[dict]:
    left: list[dict] = []
    # 早于栈的旧路径（应被更近的挤掉）
    left.append(_tool_use_msg(0, "Read", file_path="D:/old/first.py"))
    left.append(_tool_result_msg(1, "old file body\n" * 50))
    # 噪声大输出
    for i in range(2, 30):
        left.append(_tool_use_msg(i, "Grep", pattern="x", path="D:/proj"))
        left.append(_tool_result_msg(i + 1, "noise line\n" * 60))
    # 最后的报错栈与最近 3 个路径（分散在栈前后的工具参数里）
    left.append(_tool_use_msg(40, "Read", file_path="D:/proj/conf/params.json"))
    left.append(_tool_result_msg(41, "key=value noise\n" * 30))
    left.append(_tool_use_msg(42, "Edit", file_path="D:/proj/app.py"))
    left.append(_tool_result_msg(43, STACK))
    left.append(_tool_use_msg(44, "Read", file_path="D:/proj/tests/test_app.py"))
    left.append(_tool_result_msg(45, "ok\n"))
    return left


def test_hatch_block_contains_verbatim_stack_and_paths():
    left = _left_with_hatch_facts()
    block = runtime.c2_escape_hatch_block(left)
    assert block, "有栈有路径必须产出逃生舱"
    tb_idx, tb_text = runtime._last_traceback_atom(left)
    assert f"notes:msg:{tb_idx}" in block and tb_idx == 61  # 栈在最后一条 tool_result
    assert "<last_traceback" in block
    assert "KeyError: theta" in block and "Traceback (most recent call last):" in block
    assert tb_text.startswith("Traceback")  # 完整栈（含帧起点）
    assert "<last_paths>" in block
    # 最近 3 个不同路径，从新到旧：44 的 test_app、42 的 app.py、40 的 params.json
    assert "D:/proj/tests/test_app.py" in block
    assert "D:/proj/app.py" in block
    assert "D:/proj/conf/params.json" in block
    assert "D:/old/first.py" not in block  # 被更近的挤掉


def test_hatch_deterministic():
    left = _left_with_hatch_facts()
    assert runtime.c2_escape_hatch_block(left) == runtime.c2_escape_hatch_block(left)


def test_hatch_fixed_on(tmp_path, monkeypatch):
    """A3 逃生舱已固化开启：settings/env 均关不掉（键已出注册表）。"""
    monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XEYO_CWD", str(tmp_path))
    from memory import memory_switches

    with pytest.raises(ValueError):
        memory_switches.save({"XEYO_C2_ESCAPE_HATCH": "0"}, cwd=str(tmp_path))
    assert runtime._c2_escape_hatch_enabled() is True


def test_hatch_empty_without_facts():
    left = [_tool_result_msg(0, "plain text, no errors"), _tool_use_msg(1, "Grep", pattern="q")]
    assert runtime.c2_escape_hatch_block(left) == ""


def test_hatch_applied_in_apply_c2_messages(monkeypatch, tmp_path):
    monkeypatch.delenv("XEYO_C2_ESCAPE_HATCH", raising=False)
    working = WorkingSnapshot(session_id="sess_hatch1")
    left = [
        _tool_use_msg(0, "Read", file_path="D:/proj/app.py"),
        _tool_result_msg(1, STACK),
        _tool_result_msg(2, "plain output\n"),
    ]
    working.compact_cursor = len(left)
    messages = left + [{"role": "user", "content": "continue"}]
    proj = runtime.apply_c2_messages(messages, working)
    summary = proj[0]["content"]
    assert "[C2] 逃生舱" in summary
    assert "KeyError: theta" in summary
    assert "D:/proj/app.py" in summary


def test_hatch_survives_tiny_budget(monkeypatch):
    """极小预算压力：确定性摘要预算耗尽后逃生舱仍在场（先扣预留）。"""
    monkeypatch.delenv("XEYO_C2_ESCAPE_HATCH", raising=False)
    monkeypatch.setattr(runtime, "C2_SUMMARY_BUDGET", 300)
    working = WorkingSnapshot(session_id="sess_hatch2")
    working.compact_cursor = len(_left_with_hatch_facts())
    messages = _left_with_hatch_facts()
    proj = runtime.apply_c2_messages(messages, working)
    summary = proj[0]["content"]
    assert "KeyError: theta" in summary  # 栈逐字在场
    assert "D:/proj/tests/test_app.py" in summary  # 路径在场
    assert "[C2] 逃生舱" in summary


def test_hatch_bytes_stable_across_freeze(monkeypatch):
    monkeypatch.delenv("XEYO_C2_ESCAPE_HATCH", raising=False)
    messages = _left_with_hatch_facts()
    w1 = WorkingSnapshot(session_id="s1")
    w1.compact_cursor = len(messages)
    w2 = WorkingSnapshot(session_id="s1")
    w2.compact_cursor = len(messages)
    s1 = runtime.apply_c2_messages(messages, w1)[0]["content"]
    s2 = runtime.apply_c2_messages(messages, w2)[0]["content"]
    assert s1 == s2  # 同 left → 同字节（KV 前缀稳定）


def test_last_traceback_picks_newest():
    old = _tool_result_msg(0, "Traceback (most recent call last):\nValueError: old\n")
    new = _tool_result_msg(1, "Traceback (most recent call last):\nTypeError: new\n")
    idx, text = runtime._last_traceback_atom([old, new])
    assert idx == 1 and "TypeError: new" in text and "old" not in text
