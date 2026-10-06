"""评测档工具面守卫（XEYO_BENCH_MINIMAL=1）：不得再退回 bash-only。

背景（2026-09-14 取证）：该档此前把 Read/Write/Edit/Glob/Grep 连同 Git/WebFetch/
WebSearch/Diagnostics/Agent/Skill/Memory 一起裁掉，只剩 bash —— 等于主动用弱形态
出赛。harbor 自带适配器里 claude-code（默认 --permission-mode=bypassPermissions，
不传 allowed/disallowed tools）与 codex（默认 reasoning_effort=high）一律用**产品
原生工具面**；只有 terminus-2（tmux 键击）/ mini-swe-agent（单 bash 工具）天生
bash-only，那是它们的形态，不是评测口径。

本档只允许排除「在 headless 评测里没有作用对象」的工具；同时必须继续满足红线
「会话自查询工具必须无条件注册」。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.catalog import build_default_registry


#: 评测档允许排除的**全部**工具：人机交互（会把 agent 卡在等一个不存在的用户上）
#: 与宿主 GUI / 微信通道（本进程里没有接口）。
BENCH_EXCLUDED = {"AskUserQuestion", "Screenshot", "SendToWeChat", "XeyoUI"}

#: 文件工具：产品主线的读写面，评测档不得再排除。
FILE_TOOLS = ("Read", "Write", "Edit", "Glob", "Grep")


def _surface(*, bench: bool) -> list[str]:
	"""模型可见工具名（schemas 面，含 exposure=hidden 不进 schemas 的口径一致）。"""
	saved = os.environ.get("XEYO_BENCH_MINIMAL")
	try:
		if bench:
			os.environ["XEYO_BENCH_MINIMAL"] = "1"
		else:
			os.environ.pop("XEYO_BENCH_MINIMAL", None)
		reg = build_default_registry(cwd=".")
		return sorted(
			str(s.get("name"))
			for s in reg.schemas()
			if isinstance(s, dict) and s.get("name")
		)
	finally:
		if saved is None:
			os.environ.pop("XEYO_BENCH_MINIMAL", None)
		else:
			os.environ["XEYO_BENCH_MINIMAL"] = saved


def test_bench_surface_keeps_file_tools() -> None:
	names = _surface(bench=True)
	missing = [name for name in FILE_TOOLS if name not in names]
	assert not missing, f"评测档又退回 bash-only（缺 {missing}）：{names}"


def test_bench_surface_keeps_journal_query() -> None:
	"""红线：会话自查询工具必须无条件注册——评测分支不得排除它。"""
	names = _surface(bench=True)
	assert "JournalQuery" in names
	assert "Bash" in names


def test_bench_surface_diff_is_only_headless_useless() -> None:
	native = set(_surface(bench=False))
	bench = set(_surface(bench=True))
	assert native - bench == BENCH_EXCLUDED, f"评测档多裁了：{sorted(native - bench)}"
	assert bench - native == set(), f"评测档多出了：{sorted(bench - native)}"


def test_surface_id_records_selected_policy(monkeypatch) -> None:  # type: ignore[no-untyped-def]
	monkeypatch.setenv("XEYO_BENCH_MINIMAL", "1")
	monkeypatch.setenv("XEYO_TOOL_SURFACE", "minimal")

	registry = build_default_registry(cwd=".")

	assert registry.tool_surface_id == "minimal@1"
	assert registry.schema_snapshot()["surface_id"] == "minimal@1"


def _with_env(**kv):
	"""临时设/清 env（None=清），返回恢复函数。"""
	import os as _os

	saved = {k: _os.environ.get(k) for k in kv}

	def restore():
		for k, v in saved.items():
			if v is None:
				_os.environ.pop(k, None)
			else:
				_os.environ[k] = v

	for k, v in kv.items():
		if v is None:
			_os.environ.pop(k, None)
		else:
			_os.environ[k] = v
	return restore


def test_tool_deny_removes_named_tools() -> None:
	"""``XEYO_TOOL_DENY``：项目策略落到执行层（工具不在场 = 策略是事实，不再两套话）。"""
	restore = _with_env(XEYO_TOOL_DENY="Agent")
	try:
		names = _surface(bench=False)
		assert "Agent" not in names
		assert "Bash" in names, "deny 只该影响点名的工具"
	finally:
		restore()


def test_tool_deny_default_no_change() -> None:
	restore = _with_env(XEYO_TOOL_DENY=None)
	try:
		assert "Agent" in _surface(bench=False), "默认（未设 deny）不许改行为"
	finally:
		restore()


def test_tool_deny_composes_with_minimal_surface() -> None:
	restore = _with_env(XEYO_TOOL_SURFACE="minimal", XEYO_TOOL_DENY="Agent")
	try:
		names = _surface(bench=False)
		assert "Agent" not in names
		assert "Bash" in names
	finally:
		restore()


def test_tool_deny_typo_fails_loud() -> None:
	"""未知工具名硬失败：静默 typo = 用户以为禁了其实没禁。"""
	import pytest

	restore = _with_env(XEYO_TOOL_DENY="Agnet")
	try:
		with pytest.raises(ValueError):
			build_default_registry(cwd=".")
	finally:
		restore()
