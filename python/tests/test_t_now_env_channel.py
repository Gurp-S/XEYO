"""方案A 环境声道（t_now_strategy）：伪造对构造、双声道分派、不落库防线。

雷点防线（设计 32 号修订实施注记）：
- 伪造对只存在于 run_pre_llm_inject 的返回投影，输入列表/消息对象逐字节不变
  （→ 不进 MessageStore / JSONL / proj_cache，它们都在注入点之前）
- ENV_TOOL_NAME 不注册进 tools 数组（schemas 会话内冻结红线）
- 环境头身份声明（L404 说话人混淆回归锚）
- normalize_messages_for_openai 把伪对转成良构 assistant(tool_calls)→tool
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model._openai_common import (
	ENV_RELAY_REASONING_PLACEHOLDER,
	normalize_messages_for_openai,
)
from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject
from prompt.t_now_strategy import (
	ENV_ID_PREFIX,
	ENV_NOTICE_HEADER,
	ENV_TOOL_NAME,
	STRATEGY_ENV_CHANNEL,
	STRATEGY_LEGACY,
	STRATEGY_SKIP,
	env_unsupported_key,
	format_env_notice,
	mark_env_channel_unsupported,
	resolve_t_now_strategy,
	reset_env_unsupported_for_test,
	set_t_now_strategy,
	t_now_strategy,
)


def _last_pair(out: list[dict]) -> tuple[dict, dict]:
	assert out[-2]["role"] == "assistant"
	assert out[-1]["role"] == "user"
	use_blocks = out[-2]["content"]
	assert isinstance(use_blocks, list) and use_blocks[0]["type"] == "tool_use"
	assert use_blocks[0]["name"] == ENV_TOOL_NAME
	res = out[-1]["content"][0]
	assert res["type"] == "tool_result"
	assert res["tool_use_id"] == use_blocks[0]["id"]
	return use_blocks[0], res


def test_env_channel_wraps_blocks_in_fabricated_pair():
	set_t_now_strategy(None)
	assert t_now_strategy() == STRATEGY_ENV_CHANNEL
	projected = [{"role": "user", "content": "帮我修 bug"}]
	out = run_pre_llm_inject(projected, InjectContext(cwd="", multi_agent=True))
	_use, res = _last_pair(out)
	assert "Multi-Agent" in res["content"]
	assert res["content"].startswith("[system-environment]")
	# 用户消息保持原样——不再被任何注入块夹持（P1/A1 分仓退役）
	assert out[0]["content"] == "帮我修 bug"
	# 撤块锚（2026-09-15 用户裁定）：任何"预算"文本不得出现在模型可见面
	assert "预算已尽" not in str(out)
	assert "Runtime budget notice" not in str(out)


def test_env_channel_input_never_mutated_and_tool_name_not_in_input():
	"""不落库防线：注入只改返回副本，输入（=store 权威内容）零污染。"""
	projected = [
		{"role": "user", "content": "task"},
		{"role": "assistant", "content": "ok"},
	]
	frozen = copy.deepcopy(projected)
	out = run_pre_llm_inject(projected, InjectContext(cwd="", multi_agent=True))
	assert projected == frozen
	assert out is not projected
	assert ENV_TOOL_NAME not in str(projected)
	assert ENV_TOOL_NAME in str(out)


def test_env_channel_empty_blocks_no_pair():
	"""无任何块时不伪造空对（避免无意义的环境消息）。"""
	set_t_now_strategy(None)
	projected = [{"role": "user", "content": "hi"}]
	out = run_pre_llm_inject(projected, InjectContext(cwd=""))
	assert out == projected


def test_legacy_strategy_preserves_user_tail_insert():
	projected = [{"role": "user", "content": "hi"}]
	out = run_pre_llm_inject(
		projected,
		InjectContext(cwd="", multi_agent=True, strategy=STRATEGY_LEGACY),
	)
	assert out[-1]["role"] == "user"
	content = out[-1]["content"]
	texts = [
		b.get("text")
		for b in content
		if isinstance(b, dict) and b.get("type") == "text"
	]
	assert any("Multi-Agent" in t for t in texts if t)
	assert ENV_TOOL_NAME not in str(out)


def test_normalize_env_pair_to_openai_tool_messages():
	set_t_now_strategy(None)
	projected = [{"role": "user", "content": "hi"}]
	out = run_pre_llm_inject(projected, InjectContext(cwd="", multi_agent=True))
	norm = normalize_messages_for_openai(out)
	assert norm[0] == {"role": "user", "content": "hi"}
	assert norm[1]["role"] == "assistant"
	assert norm[1]["tool_calls"][0]["function"]["name"] == ENV_TOOL_NAME
	assert norm[2]["role"] == "tool"
	assert norm[2]["tool_call_id"] == norm[1]["tool_calls"][0]["id"]
	assert "Multi-Agent" in norm[2]["content"]


def test_normalize_env_pair_gets_relay_reasoning_placeholder():
	"""伪造对 assistant 无思考时，normalize 补结构性占位 reasoning_content。

	实测口径（2026-09-14，`TerminalBench/zero/probe_envpair_400.py`）：
	DeepSeek thinking 模式对「自己没签发过的 tool_call id」强制要求回传
	reasoning_content，缺则 400 `must be passed back to the API`。伪造对
	的 id 是引擎造的（xeyo_env_ 前缀），必须带占位（只声明来源，不含
	指令/评价——引擎铁律：注意力里只出现信息）。
	"""
	set_t_now_strategy(None)
	projected = [{"role": "user", "content": "hi"}]
	out = run_pre_llm_inject(projected, InjectContext(cwd="", multi_agent=True))
	norm = normalize_messages_for_openai(out)
	msg = norm[1]
	assert msg["role"] == "assistant"
	assert msg["tool_calls"][0]["id"].startswith(ENV_ID_PREFIX)
	assert msg["reasoning_content"] == ENV_RELAY_REASONING_PLACEHOLDER


def test_env_notice_header_declares_not_user():
	"""L404 回归锚：环境声道正文自带身份声明，防说话人混淆。"""
	assert ENV_NOTICE_HEADER.startswith("[system-environment]")
	assert "非用户消息" in ENV_NOTICE_HEADER
	# 纯状态陈述：不含行为引导词（runtime mode snapshot 契约同款约束）
	assert "继续" not in ENV_NOTICE_HEADER
	# 裁决（2026-09-08）：环境头只做来源声明，不含"按其中约束"类抬格指令。
	assert "按其中约束" not in ENV_NOTICE_HEADER
	assert "状态通知" in ENV_NOTICE_HEADER
	text = format_env_notice(["# 输出压缩铁律\nx", ""])
	assert "[system-environment]" in text
	assert "# 输出压缩铁律" in text
	assert format_env_notice(["", "  "]) == ""


def test_env_channel_ids_unique_per_call():
	set_t_now_strategy(None)
	projected = [{"role": "user", "content": "hi"}]
	out1 = run_pre_llm_inject(projected, InjectContext(cwd="", multi_agent=True))
	out2 = run_pre_llm_inject(projected, InjectContext(cwd="", multi_agent=True))
	id1 = out1[-2]["content"][0]["id"]
	id2 = out2[-2]["content"][0]["id"]
	assert id1.startswith(ENV_ID_PREFIX) and id2.startswith(ENV_ID_PREFIX)
	assert id1 != id2


def test_strategy_resolution_and_unsupported_fallback(monkeypatch):
	reset_env_unsupported_for_test()
	set_t_now_strategy(None)
	monkeypatch.delenv("XEYO_T_NOW_STRATEGY", raising=False)
	assert resolve_t_now_strategy("openai", "gpt-x") == STRATEGY_ENV_CHANNEL
	# prefill 预留档回落 env_channel（实测通过前不开放）
	set_t_now_strategy("prefill")
	assert resolve_t_now_strategy() == STRATEGY_ENV_CHANNEL
	set_t_now_strategy(None)
	# 备忘仅影响被标记的 provider:model 组合 → 回落 skip（L2：不落 legacy 用户尾插）
	mark_env_channel_unsupported(env_unsupported_key("openai", "gpt-x"))
	assert resolve_t_now_strategy("openai", "gpt-x") == STRATEGY_SKIP
	assert resolve_t_now_strategy("openai", "other") == STRATEGY_ENV_CHANNEL
	# 显式 legacy 不受备忘影响（评测/审计对照档保留）
	set_t_now_strategy("legacy")
	assert resolve_t_now_strategy("openai", "gpt-x") == STRATEGY_LEGACY
	set_t_now_strategy(None)
	# skip 显式设置不注入任何 T_now 块
	out = run_pre_llm_inject(
		[{"role": "user", "content": "hi"}],
		InjectContext(cwd="", forced_wrap_up=True, strategy=STRATEGY_SKIP),
	)
	assert "预算" not in str(out) and len(out) == 1
	# 非法环境变量值忽略 → 默认
	monkeypatch.setenv("XEYO_T_NOW_STRATEGY", "bogus")
	assert t_now_strategy() == STRATEGY_ENV_CHANNEL
	reset_env_unsupported_for_test()


# ---------------------------------------------------------------------------
# env 声道下的 D1 门控 / 事件不门控 / Nested 限窗语义（与 legacy 合同同源）
# ---------------------------------------------------------------------------


def _env_blob(out: list[dict]) -> str:
	"""伪对正文（含环境头与全部块）；断言注入内容用。"""
	return "\n".join(
		str(b.get("content") or "")
		for m in out
		if isinstance(m, dict) and isinstance(m.get("content"), list)
		for b in m["content"]
		if isinstance(b, dict) and b.get("type") == "tool_result"
	)


def _prior_conversation(user_text: str) -> list[dict]:
	return [
		{"role": "user", "content": "帮我看看这个项目的记忆结构"},
		{"role": "assistant", "content": "好的，项目记忆分为 L4 与会话级。"},
		{"role": "user", "content": user_text},
	]


def test_env_vague_turn_drops_inventory_keeps_directives(monkeypatch):
	monkeypatch.setattr(
		"prompt.pre_llm_inject.browser_preview_block",
		lambda: "# 浏览器预览（background only）\nurl: http://localhost:5173",
	)
	from engine import repeat_guard

	monkeypatch.setattr(repeat_guard, "current_advice", lambda: "[repeat] x3")
	out = run_pre_llm_inject(
		_prior_conversation("帮我修改"),
		InjectContext(working=None, include_memory_index=True),
	)
	blob = _env_blob(out)
	# D1：模糊指代轮 → inventory 静默；指令类存活（与 legacy 同一装配，仅换声道）
	assert "浏览器预览" not in blob
	assert "Repeat guard" in blob
	# 用户原文完好、不在伪对里
	assert "帮我修改" not in blob
	assert out[-3]["content"] == "帮我修改"


def test_env_reconcile_event_never_gated(monkeypatch):
	monkeypatch.setattr(
		"prompt.pre_llm_inject.browser_preview_block", lambda: ""
	)
	import extension.reconcile as reconcile_mod

	monkeypatch.setattr(
		reconcile_mod,
		"consume_reconcile_blocks",
		lambda: ["# 工具面变更（background only）\n新增工具 Foo"],
	)
	out = run_pre_llm_inject(
		_prior_conversation("帮我修改"),
		InjectContext(working=None, include_memory_index=True),
	)
	# D1 只静默 inventory；事件类（reconcile，drain 语义）必须存活
	assert "工具面变更" in _env_blob(out)


def test_env_after_tools_continue_inside_pair(monkeypatch):
	monkeypatch.setattr(
		"prompt.pre_llm_inject.browser_preview_block",
		lambda: "# 浏览器预览\nurl: http://localhost:5173",
	)
	projected = [
		{"role": "user", "content": "task"},
		{"role": "assistant", "content": [{"type": "tool_use", "id": "1", "name": "Read"}]},
		{"role": "tool", "tool_call_id": "1", "content": "x"},
	]
	out = run_pre_llm_inject(
		projected, InjectContext(working=None, include_memory_index=True)
	)
	blob = _env_blob(out)
	assert "# Continue" in blob
	assert "浏览器预览" in blob
	assert "Memory index" not in blob
	# 前缀（真实 tool 消息）逐字节不变
	assert out[:3] == projected


def test_env_nested_tail_window(tmp_path, monkeypatch):
	from memory.working import WorkingSnapshot

	pkg = tmp_path / "pkg"
	other = tmp_path / "other"
	pkg.mkdir()
	other.mkdir()
	(pkg / "XEYO.md").write_text("pkg-rule", encoding="utf-8")
	(other / "XEYO.md").write_text("other-rule", encoding="utf-8")
	snap = WorkingSnapshot(
		session_id="t",
		loaded_nested_instruction_paths=[
			str(pkg / "XEYO.md"),
			str(other / "XEYO.md"),
		],
	)
	projected = [
		{"role": "user", "content": "先看一下代码"},
		{
			"role": "assistant",
			"content": [
				{
					"type": "tool_use",
					"id": "r1",
					"name": "Read",
					"input": {"file_path": str(pkg / "foo.py")},
				}
			],
		},
		{
			"role": "tool",
			"tool_call_id": "r1",
			"content": [
				{
					"type": "tool_result",
					"tool_use_id": "r1",
					"content": "x=1",
					"is_error": False,
				}
			],
		},
		{"role": "user", "content": "继续改 pkg/foo.py 的校验逻辑"},
	]
	out = run_pre_llm_inject(
		projected, InjectContext(working=snap, cwd=str(tmp_path))
	)
	blob = _env_blob(out)
	assert "pkg-rule" in blob
	assert "other-rule" not in blob
	# 限窗与声道的结合不改变挂载集合
	assert str(other / "XEYO.md") in (snap.loaded_nested_instruction_paths or [])
