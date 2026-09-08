"""KV 前缀不变量（P0 验收件）：T_now 绝不放逐到 system/前缀、只锚注入尾。

MID-TURN INBOX 的硬约束：排队投递轮请求 =「用户此刻手发一条消息」的逐字节等价。
把三段顺序冻结为不变量并以此测试证明：

    [system 左段(字节稳定)] + [history(只 append)] + [T_now(仅锚注入尾)]

- 断言 A：任何易变块都不进入 role=system 的段（保前缀）。
- 断言 B：易变块只出现在「注入尾」内（legacy=最新 user 消息；
  env_channel=尾插伪对），绝不散落到其它历史消息。
- 断言 C：同一对话下，改最后一条 user 文本（模拟正常手发 vs inbox 投递）后，
  除「注入尾」外，请求逐字节一致 —— 这正是 inbox 轮能命中前缀缓存的依据。
- 断言 D：工具续写轮（末条是 tool）时，易变块以投影-only 消息追加，不改既有段。

断言 B/C/D 双声道参数化（env_channel / legacy）；断言 A 对两种声道同形。
运行：``py -3.11 -m pytest tests/test_cache_prefix_invariant.py -q``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.working import WorkingSnapshot  # noqa: E402
from permissions.policy import set_agent_mode  # noqa: E402
from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject  # noqa: E402


def _msg(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def _bytes(m: dict) -> str:
    """逐字节稳定快照（排序键稳定化，等价同一请求视角）。"""
    return json.dumps(m, sort_keys=True, ensure_ascii=False)


def _text_blobs(msgs: list[dict]) -> list[str]:
    out: list[str] = []
    for m in msgs:
        c = m.get("content")
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "text":
                    out.append(str(b.get("text") or ""))
    return out


def _join(msgs: list[dict]) -> str:
    return "\n".join(_text_blobs(msgs))


def _text_blobs_any(msgs: list[dict]) -> list[str]:
    """text 块 + tool_result 正文（env_channel 伪对正文在 tool_result 里）。"""
    out: list[str] = []
    for m in msgs:
        c = m.get("content")
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, list):
            for b in c:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    out.append(str(b.get("text") or ""))
                elif b.get("type") == "tool_result":
                    out.append(str(b.get("content") or ""))
    return out


def _join_any(msgs: list[dict]) -> str:
    return "\n".join(_text_blobs_any(msgs))


def _ctx(**kw) -> InjectContext:
    return InjectContext(
        working=WorkingSnapshot(session_id="t"),
        cwd="",
        **kw,
    )


@pytest.fixture(autouse=True)
def _reset_mode():
    set_agent_mode("agent")
    yield
    set_agent_mode("agent")


def _activate_blocks(strategy: str = ""):
    """构造一批易变块（directive/inventory 各类），确保注入真实发生。"""
    set_agent_mode("plan")  # → build_mode_context_blocks 产出 Plan 指令块
    kw: dict = {"forced_wrap_up": True}  # wrap-up 指令
    if strategy:
        kw["strategy"] = strategy
    return _ctx(
        runtime_notice="[预算] 本轮已用 $0.42",  # runtime budget notice
        multi_agent=True,             # Multi-Agent hint
        previous_reasoning_tail="上一轮结尾…",   # after_tools 才注入（fresh-user 不注入）
        approved_plan="实现 send-queue 机制。",  # agent mode 下走 approved plan 块
        **kw,
    )


def test_tnow_never_enters_system_segment():
    """断言 A：易变块绝不进 role=system 段（保前缀）。"""
    msgs = [_msg("system", "# You are a coding agent."), _msg("user", "请排队并投递。")]
    ctx = _activate_blocks()
    out = run_pre_llm_inject(msgs, ctx)
    system_text = "\n".join(_text_blobs([m for m in out if m.get("role") == "system"]))
    assert "Wrap-up(预算已尽)" not in system_text
    assert "预算" not in system_text
    assert "你只读" not in system_text  # plan 指令块
    assert "Multi-Agent" not in system_text
    # 系统段内容与注入前逐字节一致（缓存前缀没被污染）。
    assert system_text == _msg("system", "# You are a coding agent.")["content"]


_STRATS = ["env_channel", "legacy"]


@pytest.mark.parametrize("strategy", _STRATS)
def test_tnow_localized_to_tail_only(strategy):
    """断言 B：易变块只出现在注入尾，绝不散落到历史消息。

    legacy = 最新一条 user 消息内；env_channel = 尾插伪对（前缀含末条 user
    原文逐字节不变——用户消息不再被夹持）。
    """
    msgs = [
        _msg("system", "# You are a coding agent."),
        _msg("user", "历史消息一"),
        _msg("assistant", "历史回复一"),
        _msg("user", "历史消息二"),
        _msg("assistant", "历史回复二"),
        _msg("user", "这条是当前任务。"),
    ]
    out = run_pre_llm_inject(msgs, _activate_blocks(strategy=strategy))
    if strategy == "env_channel":
        assert len(out) == len(msgs) + 2
        for a, b in zip(msgs, out[:-2]):
            assert _bytes(a) == _bytes(b)
        tail = _join_any(out[-2:])
        history = _join_any(out[:-2])
    else:
        assert len(out) == len(msgs)
        tail = _join([out[-1]])
        history = _join(out[:-1])
    assert "Wrap-up(预算已尽)" in tail
    assert "预算" not in history
    assert "Multi-Agent" not in history
    assert "你只读" not in history
    assert "Wrap-up(预算已尽)" not in history


@pytest.mark.parametrize("strategy", _STRATS)
def test_inbox_delivery_preserves_prefix_identity(strategy):
    """断言 C：正常手发 vs inbox 投递，除注入尾外逐字节一致 —— 缓存命中依据。"""
    base = [
        _msg("system", "# You are a coding agent."),
        _msg("user", "历史消息一"),
        _msg("assistant", "历史回复一"),
        _msg("user", "历史消息二"),
        _msg("assistant", "历史回复二"),
    ]
    normal = [*base, _msg("user", "请实现键盘快捷键。")]
    inbox = [*base, _msg("user", "【排队投递】请实现键盘快捷键。")]
    out_normal = run_pre_llm_inject(list(normal), _activate_blocks(strategy=strategy))
    out_inbox = run_pre_llm_inject(list(inbox), _activate_blocks(strategy=strategy))
    # legacy fresh-user：块并入末条 user（len 不变）；env_channel：伪对尾插 +2
    assert len(out_normal) == len(normal) + (2 if strategy == "env_channel" else 0)
    assert len(out_inbox) == len(inbox) + (2 if strategy == "env_channel" else 0)
    assert [m.get("role") for m in out_normal] == [m.get("role") for m in out_inbox]
    # system + history（base）逐字节一致——前缀缓存保住；
    # base 之后的各自 user 原文与注入尾允许不同（这正是两场景的差异所在）。
    for m1, m2 in zip(out_normal[: len(base)], out_inbox[: len(base)]):
        assert _bytes(m1) == _bytes(m2)
    # 注入尾承载各自文本（legacy=并入末条 user；env_channel=伪对正文 + 每次随机 id）。
    assert "Wrap-up(预算已尽)" in _join_any(out_normal[len(base):])
    assert "Wrap-up(预算已尽)" in _join_any(out_inbox[len(base):])


@pytest.mark.parametrize("strategy", _STRATS)
def test_after_tools_projection_only_tail_appended(strategy):
    """断言 D：工具续写轮（末条是 tool）→ 注入以投影-only 消息追加，不改既有段。

    legacy = 追加一条投影-only user；env_channel = 追加伪对
    （assistant tool_use + user tool_result）。
    """
    msgs = [
        _msg("system", "# You are a coding agent."),
        _msg("user", "改文件。"),
        _msg("assistant", "我用 Edit 工具。"),
        {"role": "tool", "content": "已修改 src/a.py"},
    ]
    out = run_pre_llm_inject(msgs, _activate_blocks(strategy=strategy))
    n_tail = 2 if strategy == "env_channel" else 1
    assert len(out) == len(msgs) + n_tail
    if strategy == "env_channel":
        assert out[-2].get("role") == "assistant"
        assert out[-1].get("role") == "user"
        assert "Wrap-up(预算已尽)" in _join_any([out[-1]])
    else:
        assert out[-1].get("role") == "user"
        assert "Wrap-up(预算已尽)" in _join([out[-1]])
    # system 与既有 history 段未变
    for i in range(len(msgs)):
        assert _bytes(out[i]) == _bytes(msgs[i])
