"""已知缺口（strict xfail，等裁定）：批次中间插入裸 user 行 ⇒ 守卫丢结果却留下调用 ⇒ 结构性 400。

`session/tool_sequence.discard_unpaired_tool_results` 的口径写在它自己 docstring 里：
"宁可这一条结果不进上下文（模型仍可重读），也不能让整个会话报废"。
实测（本文件第二条）恰恰相反：它丢掉**没配上的那条结果**，却把 **assistant 的 tool_use 块留着**，
于是发射投影里出现悬空 ``tool_calls`` ——
DeepSeek/OpenAI 都按"assistant 的 tool_calls 必须有逐条应答"校验请求体，
投影每轮从同一状态重算同一个坏形状 ⇒ 该会话对之后每一条消息都以 400 失败
（与 2026-09-20 那次事故同族，只是方向相反：那次是"多一条无主结果"，这次是"少一条应答"）。

现网发生率（先量再动手，2026-10-03 全量转录 421 份 / 14,457 个工具批次）：
- **原始转录行**里"裸 user 插在 assistant(tool_use) 与它的 tool 行之间"= **78 批（0.54%）**；
- 但这些行经 `messages_from_rows` 载入后不进模型历史（实测三个样本文件的
  tool 行数 12/9/62 一条没少、悬空 0），所以**从转录恢复这条路当前不产生该形状**；
- 因此本缺口是**合成可复现、两条真路径都被闸住**：
  ① 转录恢复：这些 user 行经 `messages_from_rows` 不进模型历史（实测三个样本文件 tool 行
     12/9/62 一条没少、悬空 0）；
  ② 进程内：一个 turn 正在跑时第二条消息进不来 —— `engine/query_engine.py:625-632`
     直接 `raise "engine is busy: ... already running a turn"`（外层还有 SessionPool busy 表 +
     TurnRunner 双闸），所以裸 user 落不进未收尾的批次。
  ⇒ 不是现行故障，是"守卫自相矛盾"的结构性缺口：将来任何允许中途插话/回滚改写历史的通路一开，
  它就变成真的整会话报废。修法会改到模型可见历史的形状（删 assistant 的 tool_use 块），
  属机制面 ⇒ 挂 strict xfail 等裁定，不自行动手。

三档修法与代价（交决策）：
A. 丢结果时同步摘掉 assistant 对应 tool_use 块（块空了则整行只留文本/思考）。
   代价：模型看不到"自己曾发起过这次调用"；好处：会话不报废，且与现有 fail-open 口径一致。
B. 给没配上的调用补一条确定性"结果缺失"应答（形如 hydrate 的 TOOL_OUTCOME_UNKNOWN）。
   代价：与 docstring "绝不 invent a model action" 冲突，且把未知写成已知。
C. 什么都不改，只在守卫里检测出"丢过结果 + 仍有悬空调用"时出声（WARNING + 账本），
   等真出现再修。代价：真出现时仍是整会话报废，只是能归因。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model._openai_common import normalize_messages_for_openai, prune_orphan_tool_rows
from msgtypes.message import ToolUse, assistant_text_message, tool_result_message, user_message
from session.message_store import MessageStore


def _dangling(wire):
    out = []
    i = 0
    while i < len(wire):
        m = wire[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            need = {str(c.get("id")) for c in m["tool_calls"] if c.get("id")}
            got = set()
            j = i + 1
            while j < len(wire) and wire[j].get("role") == "tool":
                got.add(str(wire[j].get("tool_call_id") or ""))
                j += 1
            if need - got:
                out.extend(sorted(need - got))
            i = j
            continue
        i += 1
    return out


_USES = [
    ToolUse(id="c0", name="Read", input={"file_path": "a.py"}),
    ToolUse(id="c1", name="Glob", input={"pattern": "*.py"}),
]


def _wire(msgs):
    api = MessageStore(msgs).as_api_messages()
    wire = normalize_messages_for_openai(api, provider="deepseek", model="x")
    return prune_orphan_tool_rows(wire)


def test_orphan_direction_fail_open_still_holds():
    """在册的那一半（无主结果被摘）继续成立——别把修 A 做成"结果反而回来了"。"""
    msgs = [
        user_message("go"),
        tool_result_message("cZ", "Read", "stray"),
        assistant_text_message("", tool_uses=_USES),
        tool_result_message("c0", "Read", "r0"),
        tool_result_message("c1", "Glob", "r1"),
    ]
    wire, dropped = _wire(msgs)
    assert dropped == []  # 内部守卫已经摘掉，不需要最后一公里出手
    assert [r.get("role") for r in wire] == ["user", "assistant", "tool", "tool"]
    assert _dangling(wire) == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "已知缺口（等裁定）：裸 user 插在批次中间时，discard_unpaired_tool_results 丢掉未配上的结果、"
        "却保留 assistant 的 tool_use 块 ⇒ 投影留下悬空 tool_calls，会话对之后每条消息 400。"
        "三档修法见模块 docstring；改的是模型可见历史形状，属机制面，未获批不动手。"
    ),
)
def test_interrupted_batch_must_not_leave_dangling_tool_calls():
    msgs = [
        user_message("go"),
        assistant_text_message("", tool_uses=_USES),
        tool_result_message("c0", "Read", "r0"),
        user_message("（中途插入的一条裸用户行）"),
        tool_result_message("c1", "Glob", "r1"),
    ]
    wire, _dropped = _wire(msgs)
    # 期望的终态：要么两条应答都在，要么没应答的调用也不留在投影里——绝不能"有调用没应答"。
    assert _dangling(wire) == [], f"悬空 tool_calls 会让该会话之后每一枪都 400：{_dangling(wire)}"
