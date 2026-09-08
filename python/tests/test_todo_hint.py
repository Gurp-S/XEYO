"""engine/todo_hint + pre_llm_inject 装配点的离线测试（#2 完成度提示）。

纯函数部分全覆盖；装配点走 run_pre_llm_inject 全管线（stub 掉 repeat_guard
），验证：
- advice 为空 → 不注入（常态零开销）；
- advice 非空但 todo 不足 2 项 / 全 done → 不注入；
- advice 非空 + 有待办 → 并入 repeat_guard 块渲染 X/Y + 剩余项；
- 可经 XEYO_T_NOW_SKIP=repeat_guard 一并消融（同块消费，不新增登记条目）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.todo_hint import build_todo_hint, todo_counts  # noqa: E402


def _t(content: str, status: str = "pending") -> dict:
	return {"content": content, "status": status}


# ---------- 纯函数 ----------

class TestTodoCounts:
	def test_empty(self):
		assert todo_counts(None) == (0, 0)
		assert todo_counts([]) == (0, 0)

	def test_ignores_no_content(self):
		assert todo_counts([{}, {"status": "done"}, {"content": "  "}]) == (0, 0)

	def test_done_vs_open(self):
		todos = [_t("a", "completed"), _t("b", "in_progress"), _t("c", "pending")]
		assert todo_counts(todos) == (3, 2)


class TestBuildTodoHint:
	def test_none_or_fewer_than_two_is_empty(self):
		assert build_todo_hint(None) == ""
		assert build_todo_hint([]) == ""
		assert build_todo_hint([_t("only")]) == ""

	def test_all_done_is_empty(self):
		assert build_todo_hint([_t("a", "completed"), _t("b", "done")]) == ""

	def test_partial_progress_renders_xy_and_open_items(self):
		todos = [
			_t("写解析器", "completed"),
			_t("跑测试", "in_progress"),
			_t("补 README", "pending"),
		]
		out = build_todo_hint(todos)
		assert out.startswith("# Todo progress")
		assert "1/3" in out
		assert "写解析器" not in out.split("尚未完成的项")[1]  # 已完成不进剩余清单
		assert "跑测试" in out and "[进行中]" in out
		assert "补 README" in out and "[待办]" in out

	def test_missing_status_counts_as_open(self):
		out = build_todo_hint([_t("a", "completed"), _t("b")])
		assert out and "1/2" in out and "[待办]" in out

	def test_open_beyond_max_is_truncated(self):
		todos = [_t("a", "completed")] + [_t(f"item-{i}") for i in range(10)]
		out = build_todo_hint(todos)
		assert out
		assert "其余 4 项省略" in out  # 11 - 1 done - 6 展示 = 4
		assert out.count("[待办]") == 6

	def test_malformed_entries_survive(self):
		todos = ["junk", None, _t("ok", "in_progress"), _t("a", "completed")]
		out = build_todo_hint(todos)
		assert out and "1/2" in out


# ---------- 装配点（run_pre_llm_inject 全管线） ----------

def _make_projected() -> list[dict]:
	"""一条 assistant(工具调用) + 一条 tool_result —— ends_with_tool_result=True。"""
	return [
		{
			"role": "assistant",
			"content": [{"type": "tool_use", "id": "t1", "name": "Bash",
						 "input": {"command": "ls"}}],
		},
		{
			"role": "user",
			"content": [{"type": "tool_result", "tool_use_id": "t1",
						 "content": "ok", "is_error": False}],
		},
	]


@pytest.fixture
def stub_advice(monkeypatch):
	"""把真模块 repeat_guard 的 advice 槽替换成可写 stub。

	用 monkeypatch 属性替换（自动还原），不换 sys.modules——后者会污染同进程
	后续测试的惰性 import（实测：非空 advice 泄漏到下游 env_channel 用例）。
	"""
	import engine.repeat_guard as rg

	class _Slot:
		advice = ""

	slot = _Slot()
	monkeypatch.setattr(rg, "current_advice", lambda: slot.advice)
	return slot


def _run_inject(monkeypatch, slot, todos, *, env_skip: str | None = None) -> str:
	from memory.working import WorkingSnapshot
	from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject

	working = WorkingSnapshot(session_id="s1", agent_id="main", todos=todos)
	ctx = InjectContext(working=working, cwd="", strategy="env_channel")
	old = os.environ.get("XEYO_T_NOW_SKIP")
	if env_skip is not None:
		os.environ["XEYO_T_NOW_SKIP"] = env_skip
	elif old is None:
		os.environ.pop("XEYO_T_NOW_SKIP", None)
	try:
		out = run_pre_llm_inject(_make_projected(), ctx)
	finally:
		if old is None:
			os.environ.pop("XEYO_T_NOW_SKIP", None)
		else:
			os.environ["XEYO_T_NOW_SKIP"] = old
	return "\n".join(str(m) for m in out)


class TestInjectWiring:
	def test_no_advice_no_hint(self, stub_advice, monkeypatch):
		text = _run_inject(monkeypatch, stub_advice,
						   [_t("a", "completed"), _t("b", "pending")])
		assert "Todo progress" not in text
		assert "Repeat guard" not in text

	def test_advice_without_todo_condition_no_hint(
			self, stub_advice, monkeypatch):
		stub_advice.advice = "重复调用提醒"
		text = _run_inject(monkeypatch, stub_advice, [_t("only")])
		assert "Repeat guard" in text
		assert "Todo progress" not in text  # total<2

	def test_advice_with_all_done_no_hint(self, stub_advice, monkeypatch):
		stub_advice.advice = "重复调用提醒"
		text = _run_inject(monkeypatch, stub_advice,
						   [_t("a", "completed"), _t("b", "done")])
		assert "Repeat guard" in text
		assert "Todo progress" not in text  # 全 done

	def test_advice_with_open_todos_injects_hint(self, stub_advice, monkeypatch):
		stub_advice.advice = "重复调用提醒"
		text = _run_inject(
			monkeypatch, stub_advice,
			[_t("a", "completed"), _t("b", "in_progress"), _t("c", "pending")])
		assert "Repeat guard" in text
		assert "Todo progress" in text
		assert "1/3" in text and "[进行中]" in text and "[待办]" in text

	def test_ablated_via_skip_env(self, stub_advice, monkeypatch):
		stub_advice.advice = "重复调用提醒"
		text = _run_inject(
			monkeypatch, stub_advice,
			[_t("a", "completed"), _t("b", "pending")],
			env_skip="repeat_guard")
		assert "Repeat guard" not in text
		assert "Todo progress" not in text
