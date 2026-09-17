"""写代码精简（code_compact）T_now 注入：关=不挂；开=有块且不进 system 左段。"""

from __future__ import annotations

from permissions.policy import set_code_compact, set_code_mode
from prompt.pre_llm_inject import (
	CODE_COMPACT_RULES,
	InjectContext,
	code_compact_block,
	run_pre_llm_inject,
)
from prompt.system_prompt import IDENTITY


def test_code_compact_off_empty() -> None:
	set_code_compact(False)
	set_code_mode(None)
	assert code_compact_block() == ""


def test_code_compact_on_has_rules_and_mode() -> None:
	set_code_compact(True)
	set_code_mode("full")
	block = code_compact_block()
	assert "写代码精简状态" in block
	assert "mode=full" in block
	assert CODE_COMPACT_RULES.split("\n", 1)[0] in block
	set_code_compact(False)
	set_code_mode(None)


def test_code_compact_in_tnnow_not_system() -> None:
	set_code_compact(True)
	set_code_mode("lite")
	msgs = [{"role": "user", "content": "实现一个加法函数"}]
	out = run_pre_llm_inject(msgs, InjectContext(cwd=".", include_memory_index=False))
	# 投影最后一条 user 应含注入
	last = out[-1]
	content = last.get("content") if isinstance(last, dict) else ""
	text = content if isinstance(content, str) else str(content)
	assert "写代码精简状态" in text
	assert "mode=lite" in text
	# system 左段身份不含写代码精简
	assert "写代码精简状态" not in IDENTITY
	set_code_compact(False)
	set_code_mode(None)
