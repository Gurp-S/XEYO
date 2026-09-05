"""续跑指令（[Resume] 契约）投影-only 通道契约。

修订2（设计32）：续跑富化指令不再落库成真实 user 消息——
- 落库面：引擎把 submit prompt 原样存为 user 消息 → chat 层 submit_text 必须是
  真实用户文本（源码契约：chat.py 不再把 _build_enriched_resume_prompt 赋给 submit_text）
- 送达面：指令经 submit_options.resume_directive → contextvar → pre_llm_inject
  在本轮每次 model 调用前送达（事件类，预算不裁；子代理上下文不继承）
- 生命周期：submit_message finally 清 contextvar（防泄漏到下一轮）
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.resume_directive import (
	clear_resume_directive,
	get_resume_directive,
	set_resume_directive,
)
from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject

_DIRECTIVE = (
	"[Resume] The user asked to continue an interrupted turn.\n"
	"Original goal:\n修复登录 bug"
)


def _env_blob(out: list[dict]) -> str:
	return "\n".join(
		str(b.get("content") or "")
		for m in out
		if isinstance(m, dict) and isinstance(m.get("content"), list)
		for b in m["content"]
		if isinstance(b, dict) and b.get("type") == "tool_result"
	)


def test_chat_layer_persists_real_user_text_not_directive():
	"""源码契约：chat.py 的落库文本（submit_text）必须是用户原文，富化指令
	只进 submit_options.resume_directive。"""
	src = (
		Path(__file__).resolve().parents[1]
		/ "server"
		/ "routers"
		/ "chat.py"
	).read_text(encoding="utf-8")
	assert 'submit_text = _build_enriched_resume_prompt' not in src
	assert 'submit_options["resume_directive"]' in src
	# resume 分支仍构建富化指令（只是不再落库）
	assert "resume_directive_text = _build_enriched_resume_prompt(" in src


def test_directive_injected_via_env_channel_and_cleared():
	clear_resume_directive()
	# 无指令 → 不注入
	out0 = run_pre_llm_inject(
		[{"role": "user", "content": "继续"}], InjectContext(cwd="")
	)
	assert "Resume" not in _env_blob(out0)
	# 有指令 → 事件类注入（env_channel 伪对内），预算不裁
	set_resume_directive(_DIRECTIVE)
	out1 = run_pre_llm_inject(
		[{"role": "user", "content": "继续"}], InjectContext(cwd="")
	)
	blob = _env_blob(out1)
	assert "# Resume（续跑指令 — background only）" in blob
	assert "Original goal" in blob
	assert "修复登录 bug" in blob
	# 用户消息原样，不被夹持
	assert out1[0]["content"] == "继续"
	clear_resume_directive()
	out2 = run_pre_llm_inject(
		[{"role": "user", "content": "继续"}], InjectContext(cwd="")
	)
	assert "Original goal" not in _env_blob(out2)


def test_directive_injected_via_legacy_channel_too():
	"""legacy 档：指令随尾插送达（同样不落库）。"""
	set_resume_directive(_DIRECTIVE)
	try:
		out = run_pre_llm_inject(
			[{"role": "user", "content": "继续"}],
			InjectContext(cwd="", strategy="legacy"),
		)
		joined = "\n".join(
			str(b.get("text") or "")
			for b in out[-1]["content"]
			if isinstance(b, dict)
		)
		assert "# Resume（续跑指令 — background only）" in joined
	finally:
		clear_resume_directive()


def test_subagent_context_does_not_inherit_directive():
	"""T14：子代理上下文不继承主会话续跑指令。"""
	set_resume_directive(_DIRECTIVE)
	try:
		out = run_pre_llm_inject(
			[{"role": "user", "content": "侧链任务"}],
			InjectContext(cwd="", subagent=True),
		)
		assert "Original goal" not in _env_blob(out)
	finally:
		clear_resume_directive()


def test_contextvar_semantics():
	clear_resume_directive()
	assert get_resume_directive() == ""
	set_resume_directive("  ")
	# 空白 → 视为无指令
	assert get_resume_directive() == ""
	set_resume_directive(_DIRECTIVE)
	assert "Original goal" in get_resume_directive()
	clear_resume_directive()
	assert get_resume_directive() == ""


def test_query_engine_wires_resume_directive():
	"""源码契约：query_engine 读取 options.resume_directive 并在轮末清理。"""
	src = (
		Path(__file__).resolve().parents[1] / "engine" / "query_engine.py"
	).read_text(encoding="utf-8")
	assert 'options_dict.get("resume_directive")' in src
	assert "set_resume_directive" in src
	# submit_message finally 里清理
	assert "clear_resume_directive()" in src
