"""行为账本（loop_ledger）测试：信号计数 / 账本渲染 / fold 等价档 / 管线装配。

理念红线执法：账本渲染文本禁导演词（应该/建议/请/勿/优先/推荐）——
理念从"人工自觉"变"测试红"。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from engine.loop_ledger import (
	DEFAULT_LEDGER_AT,
	LoopLedger,
	assistant_head,
	content_digest,
	ledger_enabled,
)


# ====== 措辞执法 ======

_FORBIDDEN = ("应该", "建议", "请", "勿", "优先", "推荐")


def test_render_wording_compliance():
	"""账本渲染文本命中任何导演词 = 红（理念红线机器执法）。"""
	led = LoopLedger()
	for _ in range(10):
		led.observe_tool("Grep", "files: a\nfiles: a")  # 同内容反复
		led.observe_assistant("基于我对代码的深入分析，我发现了问题")
	assert led.render(), "达阈值应渲染"
	rendered = led.render()
	for w in _FORBIDDEN:
		assert w not in rendered, f"账本出现导演词: {w}"


# ====== s1 结果等价 ======

class TestS1Equivalent:
	def test_second_same_content_counts(self):
		"""同工具、不同参数、相同内容 → 等价计数（换花样同结果正是循环特征）。"""
		led = LoopLedger()
		led.observe_tool("Grep", "Found 1 file\npython/a.py")
		assert led.s1 == 0  # 首次出现 = 新信息
		led.observe_tool("Grep", "Found 1 file\npython/a.py")  # 换 pattern 但命中集相同
		assert led.s1 == 1

	def test_new_content_resets(self):
		"""新内容（真增益）→ 清零。"""
		led = LoopLedger()
		led.observe_tool("Grep", "A")
		led.observe_tool("Grep", "A")
		assert led.s1 == 1
		led.observe_tool("Grep", "B")
		assert led.s1 == 0

	def test_not_required_adjacent(self):
		"""不要求相邻：Grep→Read→Grep 同内容仍计数（今晚事故为交替形态）。"""
		led = LoopLedger()
		led.observe_tool("Grep", "X")
		led.observe_tool("Read", "Y")
		led.observe_tool("Grep", "X")
		assert led.s1 == 1

	def test_cross_tool_isolated(self):
		"""s1 按工具隔离：Grep 的旧内容不算 Read 的等价。"""
		led = LoopLedger()
		led.observe_tool("Grep", "same-content")
		led.observe_tool("Read", "same-content")
		assert led.s1 == 0
		assert led.s2 == 1  # 但 s2 跨工具计数

	def test_exempt_tools_skipped(self):
		led = LoopLedger(exempt_tools=frozenset({"AskUserQuestion"}))
		for _ in range(5):
			led.observe_tool("AskUserQuestion", "same")
		assert led.s1 == 0 and led.s2 == 0 and led.tool_calls == 0


# ====== s2 内容已见 ======

class TestS2Seen:
	def test_cross_tool_seen(self):
		led = LoopLedger()
		led.observe_tool("Read", "body")
		led.observe_tool("Grep", "body")
		assert led.s2 == 1

	def test_new_content_resets(self):
		led = LoopLedger()
		led.observe_tool("Read", "body")
		led.observe_tool("Read", "body")
		assert led.s2 == 1
		led.observe_tool("Read", "body-v2")
		assert led.s2 == 0

	def test_partial_read_new_content_not_seen(self):
		"""同文件不同 offset 返回不同内容 = 真增益，不计数（误报关键防护）。"""
		led = LoopLedger()
		led.observe_tool("Read", "   1→alpha\n   2→beta\n")
		led.observe_tool("Read", "  10→kappa\n  11→lambda\n")
		assert led.s2 == 0


# ====== s3 首句重复 ======

class TestS3HeadRepeat:
	def test_consecutive_same_head(self):
		led = LoopLedger()
		for i in range(4):
			# 前 30 字符相同、尾部细节不同（今晚事故开场白的真实形态）
			led.observe_assistant(
				f"基于我对代码的深入分析，我发现了 XEYO 中几个关键的统计问题。第{i}处细节"
			)
		assert led.s3 == 4

	def test_head_change_resets(self):
		led = LoopLedger()
		led.observe_assistant("AAAAAAAAAA")
		led.observe_assistant("AAAAAAAAAA")
		assert led.s3 == 2
		led.observe_assistant("BBBBBBBBBB")
		assert led.s3 == 1

	def test_empty_text_ignored(self):
		led = LoopLedger()
		led.observe_assistant("")
		led.observe_assistant("   ")
		assert led.s3 == 0


# ====== 渲染门控 ======

class TestRenderGate:
	def test_below_threshold_empty(self):
		led = LoopLedger()
		for _ in range(2):  # s1=1（1 次等价重复）< 3
			led.observe_tool("Grep", "same")
		assert led.render() == ""

	def test_reach_threshold_renders_lines(self):
		led = LoopLedger()
		for _ in range(4):  # 首次 + 3 次等价重复 → s1=3 达阈值
			led.observe_tool("Grep", "same")
		out = led.render()
		assert "与该工具既往结果完全一致的调用：3 次" in out
		assert "本回合工具调用累计：4 次" in out

	def test_reset(self):
		led = LoopLedger()
		for _ in range(5):
			led.observe_tool("Grep", "same")
		led.reset()
		assert led.render() == "" and led.tool_calls == 0


# ====== 开关 ======

class TestKillSwitch:
	def test_env_off_disables_all(self, monkeypatch):
		monkeypatch.setenv("XEYO_LOOP_LEDGER", "0")
		assert ledger_enabled() is False
		led = LoopLedger()
		for _ in range(10):
			led.observe_tool("Grep", "same")
			led.observe_assistant("同首句同首句同首句")
		assert led.render() == "" and led.tool_calls == 0

	def test_env_threshold_override(self, monkeypatch):
		monkeypatch.setenv("XEYO_LOOP_LEDGER_AT", "2,99,99")
		led = LoopLedger()
		for _ in range(3):  # s1=2（2 次等价重复）达覆盖阈值
			led.observe_tool("Grep", "same")
		out = led.render()
		assert "与该工具既往结果完全一致的调用：2 次" in out
		assert "已见内容" not in out


# ====== fold 等价档 ======

class TestFoldEquivalent:
	def _fold(self):
		from engine.repeat_fold import IdenticalResultFold

		return IdenticalResultFold()

	def test_same_content_different_args_folds_on_third(self, monkeypatch):
		"""默认档与 R2' 契约同底线：前两次原文保留，第 3 次出现才折叠。"""
		monkeypatch.delenv("XEYO_LOOP_LEDGER", raising=False)
		f = self._fold()
		t1, _ = f.process("Grep", {"pattern": "a"}, "Found 1 file\nx.py")
		assert t1 == "Found 1 file\nx.py"  # 首次完整
		t2, folded2 = f.process("Grep", {"pattern": "b"}, "Found 1 file\nx.py")
		assert not folded2 and t2 == "Found 1 file\nx.py"  # 第 2 次仍原文
		t3, folded3 = f.process("Grep", {"pattern": "c"}, "Found 1 file\nx.py")
		assert folded3 and "完全相同" in t3 and "[fold]" in t3

	def test_env_equiv_at_aggressive(self, monkeypatch):
		"""XEYO_FOLD_EQUIV_AT=2 → 第 2 次出现即折叠（激进档可配）。"""
		monkeypatch.delenv("XEYO_LOOP_LEDGER", raising=False)
		monkeypatch.setenv("XEYO_FOLD_EQUIV_AT", "2")
		f = self._fold()
		f.process("Grep", {"pattern": "a"}, "same-out")
		t2, folded = f.process("Grep", {"pattern": "b"}, "same-out")
		assert folded and "等价结果" in t2

	def test_new_content_never_folds(self, monkeypatch):
		monkeypatch.delenv("XEYO_LOOP_LEDGER", raising=False)
		f = self._fold()
		for i in range(5):
			t, folded = f.process("Grep", {"pattern": f"p{i}"}, f"out-{i}")
			assert not folded

	def test_kill_switch_restores_byte_level_only(self, monkeypatch):
		monkeypatch.setenv("XEYO_LOOP_LEDGER", "0")
		f = self._fold()
		f.process("Grep", {"pattern": "a"}, "same-out")
		t2, folded = f.process("Grep", {"pattern": "b"}, "same-out")
		assert not folded and t2 == "same-out"  # 等价档关闭，逐字节档未达 3 次

	def test_wording_compliance(self, monkeypatch):
		monkeypatch.delenv("XEYO_LOOP_LEDGER", raising=False)
		monkeypatch.setenv("XEYO_FOLD_EQUIV_AT", "2")
		f = self._fold()
		f.process("Grep", {"pattern": "a"}, "same-out")
		t2, _ = f.process("Grep", {"pattern": "b"}, "same-out")
		for w in _FORBIDDEN:
			assert w not in t2

	def test_byte_level_takes_priority(self, monkeypatch):
		monkeypatch.delenv("XEYO_LOOP_LEDGER", raising=False)
		f = self._fold()
		for _ in range(3):
			t, folded = f.process("Grep", {"pattern": "a"}, "same-out")
		assert folded and "同一签名" in t  # 逐字节档文案（更具体）


# ====== 管线装配（run_pre_llm_inject 全管线） ======

def _make_projected() -> list[dict]:
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


class TestInjectWiring:
	def _run(self, monkeypatch, ledger):
		from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject

		monkeypatch.setattr("engine.repeat_guard._CURRENT_ADVICE", "")
		ctx = InjectContext(working=None, cwd="", strategy="env_channel",
							loop_ledger=ledger)
		out = run_pre_llm_inject(_make_projected(), ctx)
		return "\n".join(str(m) for m in out)

	def test_ledger_reaches_model_when_hot(self, monkeypatch):
		monkeypatch.delenv("XEYO_LOOP_LEDGER", raising=False)
		led = LoopLedger()
		for _ in range(4):
			led.observe_tool("Grep", "same")
			led.observe_assistant("基于我对代码的深入分析，我发现了问题")
		text = self._run(monkeypatch, led)
		assert "与该工具既往结果完全一致的调用" in text
		assert "Repeat guard" in text

	def test_ledger_silent_when_cold(self, monkeypatch):
		monkeypatch.delenv("XEYO_LOOP_LEDGER", raising=False)
		led = LoopLedger()
		led.observe_tool("Grep", "same")
		text = self._run(monkeypatch, led)
		assert "与该工具既往结果完全一致的调用" not in text

	def test_ledger_none_no_crash(self, monkeypatch):
		monkeypatch.delenv("XEYO_LOOP_LEDGER", raising=False)
		text = self._run(monkeypatch, None)
		assert text  # 管线正常走完


# ====== 纯函数 ======

class TestPureFns:
	def test_digest_stable_and_empty(self):
		assert content_digest("abc") == content_digest("abc")
		assert content_digest("") == "" and content_digest("  \n") == ""
		assert content_digest(None) == ""

	def test_head_strip(self):
		assert assistant_head("  hello world  ") == "hello world"
		assert len(assistant_head("x" * 100)) == 30
		assert assistant_head(None) == ""
