"""声道 B（``system_channel``）回归：易变块走**原生 system 消息**，不再伪造 tool 对。

## 目的（缺陷修复，不是优化）

``env_channel`` 的伪对 ``assistant(tool_use: xeyo_env_notice) → tool_result``
在结构上与「模型自己的工具调用」**完全同形** ⇒ 模型在投影里看到自己调过该
工具，得出「我有这个工具」并真的去调它。

第七轮单会话实测 **60+ 次**（其中 ≥7 次整条响应体只有这一个调用），且：

- **意图抑制无效**：交接文档已明确预警该现象，模型仍每次发生；
- **host 侧应答者存在**：伪对产出的调用被真实应答（回灌一份新的环境通知），
  并被引擎转成「工具续写轮」再注入 ``# Continue（工具结果后）`` ⇒
  **自催化闭环**：上下文里不断积累"我调用过它"的先例。

⇒ **不可调用性必须来自形态本身**。system 是"引擎注入的状态"的原生声道：
既不是 user（说话人隔离成立），也不是 assistant（不伪装成模型自身行为）。
本文件把这条红线钉死。

## 五条断言（照 §5 清单）

① 尾部只新增一条 system；
② MessageStore / JSONL 零污染（输入列表与消息对象逐字节不变）；
③ 既有前缀逐字节不动（只延长尾部）；
④ **投影里不存在 tool_use 形态的注入承载**（回归锚 = 本改动的全部目的）；
⑤ ``env_channel`` 档在旁路期不受影响。

另补：两套归一化层（OpenAI / Anthropic）的落点，与策略解析不再回落。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from model._openai_common import normalize_messages_for_openai
from model.anthropic import normalize_messages_for_anthropic
from permissions.policy import set_agent_mode
from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject
from prompt.t_now_strategy import (
	STRATEGY_ENV_CHANNEL,
	STRATEGY_SYSTEM_CHANNEL,
	env_unsupported_key,
	mark_env_channel_unsupported,
	reset_env_unsupported_for_test,
	resolve_t_now_strategy,
	set_t_now_strategy,
)
from prompt.turn_context import append_system_notice

_BASE: list[dict] = [
	{"role": "system", "content": "# You are a coding agent."},
	{"role": "user", "content": "历史消息一"},
	{"role": "assistant", "content": "历史回复一"},
	{"role": "user", "content": "这条是当前任务。"},
]


def _bytes(obj: object) -> str:
	return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def _activate(**kw: object) -> InjectContext:
	# 挂"仍然存活"的块，确保注入真实发生（撤块后不再有 wrap_up/runtime_notice）
	return InjectContext(cwd="", multi_agent=True, approved_plan="实现 send-queue。", **kw)


@pytest.fixture(autouse=True)
def _clean_state():
	set_t_now_strategy(None)
	reset_env_unsupported_for_test()
	set_agent_mode("agent")
	yield
	set_t_now_strategy(None)
	reset_env_unsupported_for_test()
	set_agent_mode("agent")


# ---------------------------------------------------------------------------
# ① 形态：尾部一条原生 system
# ---------------------------------------------------------------------------


def test_tail_is_single_native_system_message() -> None:
	out = run_pre_llm_inject(
		[dict(m) for m in _BASE], _activate(strategy=STRATEGY_SYSTEM_CHANNEL)
	)
	assert out[-1]["role"] == "system"
	assert isinstance(out[-1]["content"], str)
	assert out[-1]["content"].startswith("[system-environment]")
	assert "Multi-Agent" in out[-1]["content"]
	# 只有「原有 system」与「尾部新增 system」两条，且原 system 未被改写
	sys_idx = [i for i, m in enumerate(out) if m.get("role") == "system"]
	assert sys_idx == [0, len(out) - 1]
	assert out[0]["content"] == _BASE[0]["content"]


def test_empty_blocks_append_nothing() -> None:
	"""无块时不追加空 system（避免无意义的环境消息）。"""
	msgs = [{"role": "user", "content": "hi"}]
	assert append_system_notice(msgs, "") == msgs
	assert append_system_notice(msgs, "   ") == msgs
	out = run_pre_llm_inject(
		[{"role": "user", "content": "hi"}], InjectContext(cwd="", strategy=STRATEGY_SYSTEM_CHANNEL)
	)
	assert out == [{"role": "user", "content": "hi"}]


# ---------------------------------------------------------------------------
# ② 零污染 + ③ 前缀逐字节不动
# ---------------------------------------------------------------------------


def test_input_never_mutated_and_store_jsonl_untouched() -> None:
	projected = [dict(m) for m in _BASE]
	frozen = _bytes(projected)
	out = run_pre_llm_inject(projected, _activate(strategy=STRATEGY_SYSTEM_CHANNEL))
	assert _bytes(projected) == frozen, "注入修改了入参（= MessageStore 权威内容）"
	assert out is not projected
	# 尾部追加 ⇒ 只在尾部新增一条消息对象，其余对象是同一引用
	assert all(a is b for a, b in zip(projected, out))


def test_prefix_is_byte_identical_only_tail_extended() -> None:
	out = run_pre_llm_inject(
		[dict(m) for m in _BASE], _activate(strategy=STRATEGY_SYSTEM_CHANNEL)
	)
	assert len(out) == len(_BASE) + 1
	for a, b in zip(_BASE, out):
		assert _bytes(a) == _bytes(b), "前缀被改动 ⇒ KV 前缀缓存失效"


# ---------------------------------------------------------------------------
# ④ 回归锚：投影里不存在 tool_use 形态的承载（本改动的全部目的）
# ---------------------------------------------------------------------------


def test_no_tool_use_carrier_in_projection() -> None:
	"""伪对是缺陷本身：投影里绝不能再出现"模型自己发出的工具调用"。"""
	out = run_pre_llm_inject(
		[dict(m) for m in _BASE], _activate(strategy=STRATEGY_SYSTEM_CHANNEL)
	)
	blob = _bytes(out)
	assert "tool_use" not in blob
	assert "tool_result" not in blob
	assert "xeyo_env_notice" not in blob
	# 参考：伪对档必然命中（证明本断言不是空洞的）
	env_out = run_pre_llm_inject([dict(m) for m in _BASE], _activate())
	assert "tool_use" in _bytes(env_out) and "xeyo_env_notice" in _bytes(env_out)


# ---------------------------------------------------------------------------
# ⑤ env_channel 档不受影响（旁路期两档并存；默认未切）
# ---------------------------------------------------------------------------


def test_env_channel_untouched_during_bypass_window() -> None:
	assert resolve_t_now_strategy() == STRATEGY_ENV_CHANNEL
	out = run_pre_llm_inject([dict(m) for m in _BASE], _activate())
	assert out[-2]["role"] == "assistant"
	assert out[-1]["role"] == "user"
	assert "xeyo_env_notice" in _bytes(out)


def test_system_channel_no_longer_falls_back_to_env_channel() -> None:
	set_t_now_strategy(STRATEGY_SYSTEM_CHANNEL)
	assert resolve_t_now_strategy() == STRATEGY_SYSTEM_CHANNEL
	# env_channel 的厂商备忘只作用于 env_channel 档，不牵连声道 B
	mark_env_channel_unsupported(env_unsupported_key("openai", "gpt-x"))
	assert resolve_t_now_strategy("openai", "gpt-x") == STRATEGY_SYSTEM_CHANNEL


# ---------------------------------------------------------------------------
# 归一化层落点（协议分工：OpenAI 原样保留 system；Anthropic 上提顶层字段）
# ---------------------------------------------------------------------------


def test_openai_normalization_keeps_injected_system_at_tail() -> None:
	out = run_pre_llm_inject(
		[dict(m) for m in _BASE], _activate(strategy=STRATEGY_SYSTEM_CHANNEL)
	)
	norm = normalize_messages_for_openai(out)
	assert norm[-1]["role"] == "system"
	assert "[system-environment]" in str(norm[-1]["content"])
	assert [m["role"] for m in norm].count("system") == 2


def test_anthropic_normalization_lifts_system_to_top_level_field() -> None:
	out = run_pre_llm_inject(
		[dict(m) for m in _BASE], _activate(strategy=STRATEGY_SYSTEM_CHANNEL)
	)
	system_text, msgs = normalize_messages_for_anthropic(out)
	# Messages API 不接受 messages 里的 system role
	assert all(m.get("role") != "system" for m in msgs)
	assert "[system-environment]" in system_text
	assert system_text.startswith("# You are a coding agent.")
	# 对话前缀未被污染（只被 system 字段承载）
	assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
