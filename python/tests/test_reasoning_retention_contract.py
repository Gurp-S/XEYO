"""reasoning 全保留契约测试（用户决策 2026-09-10：不裁剪，全保留）。

背景（《S1-取证报告-reasoning裁剪与计费.md》实测结论）：
  1) 厂商把回传的 `reasoning_content` **排除在 `prompt_tokens` 计费基数之外**
     （实测：塞入 5.92 万 token 的 reasoning，`prompt_tokens` 只涨 3,589）
     → 全保留的**成本 ≈ 0**，裁剪的「省成本」动机不存在。
  2) 旧轮 reasoning 技术上可裁（TRIM 组全 200），但厂商**并不强制**
     → 全保留是协议上**最保守**的一侧，永不触发 400。
  3) 全保留 = KV 前缀**逐字节不动**，最利于缓存命中。

故决策：**reasoning 全量进压缩域、永不裁剪**。`engine/compact.py` 里
**不应有任何** reasoning 相关分支 —— 现状「原样透传」即为目标行为。

本测试反向锁定该决策：任何未来「顺手加个裁剪」的改动都会红。

覆盖：
  1) project() 不改写 reasoning block（冻结区/近档/aging 全档位）。
  2) reasoning 在投影后**逐字节等价**（不做 strip/截断/重排）。
  3) reasoning 与同消息的 text/tool_use **配对完整、顺序不变**。
  4) compact 模块**零 reasoning 符号**（结构性防回归：新增即红）。
  5) 投影输出经 OpenAI 序列化后仍还原为 `reasoning_content`（端到端）。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import compact as compact_mod  # noqa: E402
from engine.compact import project  # noqa: E402
from model._openai_common import normalize_messages_for_openai  # noqa: E402

RAW_REASONING = (
    "\n  我先看 a.py。\n"
    '它导入 `socket`，是 "core" 模块。\n'
    "结论：先 Read 再 Edit。🙂\n\n"
)


def _assistant_with_reasoning(uid: str, *, text: str = "读一下", reasoning: str = RAW_REASONING) -> dict:
    blocks: list[dict] = []
    if reasoning:
        blocks.append({"type": "reasoning", "text": reasoning})
    if text:
        blocks.append({"type": "text", "text": text})
    blocks.append({"type": "tool_use", "id": uid, "name": "Read", "input": {"p": "a.py"}})
    return {"role": "assistant", "content": blocks}


def _tool_row(uid: str, content: str = "file body") -> dict:
    return {"role": "tool", "tool_call_id": uid, "content": content}


def _history(n: int = 6) -> list[dict]:
    """n 轮工具对话，每轮 assistant 都带 reasoning。"""
    msgs: list[dict] = [{"role": "system", "content": "sys"}]
    for i in range(n):
        msgs.append({"role": "user", "content": f"任务 {i}"})
        msgs.append(_assistant_with_reasoning(f"c{i}"))
        msgs.append(_tool_row(f"c{i}", f"结果 {i}"))
    msgs.append({"role": "user", "content": "继续"})
    return msgs


def _reasonings(msgs: list[dict]) -> list[str]:
    out: list[str] = []
    for m in msgs:
        c = m.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "reasoning":
                    out.append(str(b.get("text") or ""))
    return out


# ------------------------------------------- 1) 结构性防回归（最强那条）


def test_compact_module_has_no_reasoning_symbols() -> None:
    """★ 契约：compact.py 里不得出现任何 reasoning 相关符号。

    这是「全保留」决策的结构性保证 —— reasoning 与其他 block 一视同仁地
    被原样复制。若未来有人加裁剪逻辑，必然引入 reasoning 字样，此测试即红。
    """
    src = inspect.getsource(compact_mod)
    lowered = src.lower()
    for needle in ("reasoning", "thinking_block", "thought"):
        assert needle not in lowered, (
            f"engine/compact.py 出现 `{needle}` —— 与「reasoning 全保留」决策冲突。"
            " 若确要裁剪，请先改 docs/S1-取证报告 的决策与本节契约。"
        )


# ---------------------------------------------- 2) 投影保真（全档位）


@pytest.mark.parametrize("frozen_until", [0, 2, 4, 100])
def test_project_preserves_reasoning_bytes(frozen_until: int) -> None:
    """任意冻结边界下，reasoning 逐字节不变且条数不丢。"""
    msgs = _history()
    before = _reasonings(msgs)
    assert len(before) == 6  # 前置：确实有 6 条

    out = project(msgs, frozen_until=frozen_until)
    after = _reasonings(out)
    assert after == before, f"frozen_until={frozen_until} 时 reasoning 被改动或丢失"


def test_project_preserves_reasoning_order_and_pairing() -> None:
    """reasoning 仍在消息首位，text/tool_use 顺序与配对不动。"""
    msgs = _history(3)
    out = project(msgs, frozen_until=1)
    for m in out:
        c = m.get("content")
        if not isinstance(c, list):
            continue
        types = [b.get("type") for b in c if isinstance(b, dict)]
        if "reasoning" in types:
            assert types[0] == "reasoning", f"reasoning 未在首位: {types}"
            assert "tool_use" in types
            tids = [b.get("id") for b in c if isinstance(b, dict) and b.get("type") == "tool_use"]
            assert all(tids)


def test_project_returns_same_object_when_no_tool_result_to_rewrite() -> None:
    """纯 assistant+reasoning 历史：project 应原对象返回（未触碰）。"""
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        _assistant_with_reasoning("c1"),
    ]
    out = project(msgs, frozen_until=0)
    assert out[2] is msgs[2], "无 tool_result 可重写时不应复制/改动 assistant 消息"


# ------------------------------------------------ 3) 端到端：投影后仍回放


@pytest.mark.parametrize("frozen_until", [0, 3, 100])
def test_projected_history_still_replays_reasoning_content(frozen_until: int) -> None:
    """★ 端到端：投影 → OpenAI 序列化后，每条 reasoning 仍还原为字段。"""
    msgs = _history()
    projected = project(msgs, frozen_until=frozen_until)
    wire = normalize_messages_for_openai(projected)
    got = [
        m["reasoning_content"]
        for m in wire
        if m.get("role") == "assistant" and "reasoning_content" in m
    ]
    assert got == _reasonings(msgs)


def test_projection_does_not_inject_reasoning_into_plain_rows() -> None:
    """不得给「本来没有 reasoning」的消息凭空添字段。"""
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": "纯文本回答"},
    ]
    wire = normalize_messages_for_openai(project(msgs, frozen_until=0))
    for m in wire:
        assert "reasoning_content" not in m


# --------------------------------------- 4) 大 reasoning 不被截断（体量边界）


def test_huge_reasoning_not_truncated_by_projection() -> None:
    """超出 blob 阈值的巨型 reasoning 也不得被投影截断。

    真实轨迹单条中位 6,330 字符、最长会话累计 57 万字符 —— 必须完整保留。
    """
    huge = "长思考。" * 5000  # 20,000 字符
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        _assistant_with_reasoning("c1", reasoning=huge),
        _tool_row("c1", "r" * 500),
        {"role": "user", "content": "继续"},
    ]
    out = project(msgs, frozen_until=10)
    assert _reasonings(out) == [huge]


def test_reasoning_survives_with_aging_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """aging 开启时（会折叠 tool_result）reasoning 依然原样保留。

    aging 由 project() 内部按 env 决定（`XEYO_AGING`），不是入参。
    """
    monkeypatch.setenv("XEYO_AGING", "1")
    msgs = _history(4)
    out = project(msgs, frozen_until=100)
    assert _reasonings(out) == _reasonings(msgs)


def test_reasoning_block_not_treated_as_tool_result() -> None:
    """reasoning block 不得被 _iter_tool_result_blocks 误收（类型判定必须精确）。"""
    msg = _assistant_with_reasoning("c1")
    got = compact_mod._iter_tool_result_blocks(msg)
    assert got == [], f"reasoning 被误判为 tool_result: {got}"
