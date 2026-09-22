"""最后一公里（wire 出口）丢弃无主 tool 行——fail-open 回归。

事故背景（2026-09-20，会话 sess_mu9oqy8m_63ljiu）：送模型的投影里多出一条
没有对应 assistant tool_calls 的 ``role="tool"`` 行时，厂商（DeepSeek/网关）
报 ``Messages with role 'tool' must be a response to a preceding message with
'tool_calls'``；投影每轮从同一状态重算同一个坏形状，于是该会话对**之后每一条
消息**都以 400 失败（改消息内容无效，结构性卡死）。

``session.tool_sequence.discard_unpaired_tool_results`` 只覆盖 MessageStore
投影之前的内部形状；压缩 / T_now 注入之后的最后一公里原先无守卫。

口径：宁可这一条结果不进上下文（模型仍可重读），也不能让整个会话报废。
"""

from __future__ import annotations

from model._openai_common import (
    normalize_messages_for_openai,
    prune_orphan_tool_rows,
)


def _paired_history() -> list[dict]:
    return [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": [
                {"type": "reasoning", "text": "thinking"},
                {"type": "tool_use", "id": "call_1", "name": "Read", "input": {}},
            ],
        },
        {
            "role": "tool",
            "name": "Read",
            "tool_call_id": "call_1",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": "ok"}
            ],
        },
        {"role": "user", "content": "next"},
    ]


def _orphan_tool_rows(wire: list[dict]) -> list[str]:
    """wire 形状上的孤立 tool 行（无前置 assistant.tool_calls 应答）。"""
    outstanding: set[str] = set()
    orphans: list[str] = []
    for m in wire:
        role = m.get("role")
        if role == "assistant":
            outstanding = {
                str(c.get("id"))
                for c in (m.get("tool_calls") or [])
                if isinstance(c, dict) and c.get("id")
            }
        elif role == "tool":
            tid = str(m.get("tool_call_id") or "")
            if tid and tid in outstanding:
                outstanding.discard(tid)
            else:
                orphans.append(tid)
        else:
            outstanding = set()
    return orphans


def test_paired_history_is_clean_and_untouched() -> None:
    history = _paired_history()
    wire = normalize_messages_for_openai(history)
    assert _orphan_tool_rows(wire) == []
    assert [m["role"] for m in wire] == ["user", "assistant", "tool", "user"]


def test_orphan_tool_row_is_dropped_at_wire_boundary() -> None:
    """多出来的一条 tool 结果（无主）不得进入请求体。"""
    history = _paired_history() + [
        {
            "role": "tool",
            "name": "Bash",
            "tool_call_id": "call_ghost",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_ghost", "content": "x"}
            ],
        }
    ]
    wire = normalize_messages_for_openai(history)
    assert _orphan_tool_rows(wire) == []
    assert [m["role"] for m in wire] == ["user", "assistant", "tool", "user"]
    assert all(m.get("tool_call_id") != "call_ghost" for m in wire)


def test_orphan_tool_result_block_inside_user_row_is_dropped() -> None:
    """投影尾部的伪对残片（user 行里只剩 tool_result 块）同样不得进入请求体。"""
    history = _paired_history() + [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "xeyo_env_deadbeef",
                    "content": "leaked half pair",
                }
            ],
        }
    ]
    wire = normalize_messages_for_openai(history)
    assert _orphan_tool_rows(wire) == []
    assert all(m.get("tool_call_id") != "xeyo_env_deadbeef" for m in wire)


def test_env_notice_pair_survives_wire_guard() -> None:
    """T_now 环境声道伪对是**合法配对**：assistant(tool_use) → user(tool_result)。

    守卫只按配对判定，不得把它一起丢掉（丢掉会静默失去 T_now 送达）。
    """
    history = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "xeyo_env_abc123",
                    "name": "xeyo_env_notice",
                    "input": {},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "xeyo_env_abc123",
                    "content": "state",
                }
            ],
        },
    ]
    wire = normalize_messages_for_openai(history)
    assert _orphan_tool_rows(wire) == []
    tool_rows = [m for m in wire if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_rows] == ["xeyo_env_abc123"]
    assistant = [m for m in wire if m["role"] == "assistant"]
    assert assistant and assistant[0]["tool_calls"][0]["id"] == "xeyo_env_abc123"


def test_prune_keeps_same_object_when_clean_and_reports_ids() -> None:
    """无丢弃时不得重建列表（避免无谓拷贝）；有丢弃时回 id 供定位。"""
    wire = normalize_messages_for_openai(_paired_history())
    same, dropped = prune_orphan_tool_rows(wire)
    assert same is wire
    assert dropped == []

    dirty = wire + [{"role": "tool", "tool_call_id": "ghost", "content": "x"}]
    pruned, dropped = prune_orphan_tool_rows(dirty)
    assert dropped == ["ghost"]
    assert len(pruned) == len(wire)


# ---------------------------------------------------------------------------
# 丢弃必须留得下账（09-23 补：0 需求判决的前提是分母可测）
#
# 为什么只补观测、不做「合成回执」：524 个真实发射面（各会话 working.json 的
# last_x_sent）里孤儿 tool 行 2 例（0.4%）、未回执 tool_call **0 例** ⇒
# Codex 那套"给缺回执的 call 合成 tool 结果"没有测到的需求，按"无收益不并入主链"判死。
# 但丢弃本身此前只写 logging.warning，事后无法统计 ⇒ 09-20 那次事故是厂商 400 才暴露的。
# ---------------------------------------------------------------------------

def _drop_rows(path) -> list[dict]:
    import json

    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("{")
    ]


def test_wire_drop_is_ledgered(monkeypatch, tmp_path) -> None:
    import usage.ledger as L

    monkeypatch.setattr(L, "usage_dir", lambda: tmp_path)
    history = _paired_history() + [
        {
            "role": "tool",
            "name": "Bash",
            "tool_call_id": "call_ghost",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_ghost", "content": "x"}
            ],
        }
    ]
    wire = normalize_messages_for_openai(history)
    assert all(m.get("tool_call_id") != "call_ghost" for m in wire)  # 行为不变：仍然丢弃
    rows = _drop_rows(tmp_path / "wire_drops.jsonl")
    assert len(rows) == 1, rows
    assert rows[0]["type"] == "wire_drop" and rows[0]["dropped"] == 1
    assert "call_ghost" in rows[0]["ids"]


def test_clean_request_writes_no_drop_row(monkeypatch, tmp_path) -> None:
    """没丢就不能留痕——否则账本里的分母是假的。"""
    import usage.ledger as L

    monkeypatch.setattr(L, "usage_dir", lambda: tmp_path)
    normalize_messages_for_openai(_paired_history())
    assert _drop_rows(tmp_path / "wire_drops.jsonl") == []


def test_ledger_failure_cannot_break_the_wire(monkeypatch) -> None:
    """观测失败必须静默：投影/发射永远不能被记账拖住或改形状。"""
    import usage.ledger as L

    def boom(**_kw):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(L, "record_wire_drop", boom)
    history = _paired_history() + [
        {
            "role": "tool",
            "name": "Bash",
            "tool_call_id": "call_ghost",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_ghost", "content": "x"}
            ],
        }
    ]
    wire = normalize_messages_for_openai(history)
    assert [m["role"] for m in wire] == ["user", "assistant", "tool", "user"]
    assert all(m.get("tool_call_id") != "call_ghost" for m in wire)

