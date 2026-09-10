"""P1：T_now 结构根治契约回归（A1 分仓 / D1 轮型门控 / F1 真硬顶 / F3 标签）。

本模块以 **legacy 声道**（块文本尾插末条 user）为被测合同——legacy 是
env_channel 的回退档，其摆放语义仍被冻结。env_channel（方案A 伪造 tool 对）
的对应语义（D1 门控 / 事件不门控 / Nested 限窗 / 预算）见
``test_t_now_env_channel.py``。

冻结口径：
- A1 分仓：fresh-user 轮 INVENTORY 类前插到用户文本之前（生成点紧邻用户请求），
  DIRECTIVE/EVENT 尾插贴近生成点；after_tools 轮维持原尾插合同（Continue 在前）。
- D1 门控：模糊指代型短追问（有上文 + 短 + 无路径/代码标记 + 含指代/确认词）
  静默全部 INVENTORY；事件类（含 drain 语义）绝不静默；首轮不门控。
- F1 真硬顶：全部块入预算，directive/event 全保，inventory 限配额、超限截断。
- F3：块以 (KLASS_*, text) 装配，类别决定放置/门控/预算。
- 批次3：Memory index 不再推送 T_now（能力宣告住 Memory 工具 description）。

inventory 替身统一用浏览器预览块（monkeypatch
``prompt.pre_llm_inject.browser_preview_block``）——Memory index 已退役。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prompt.pre_llm_inject import (
	KLASS_DIRECTIVE,
	KLASS_INVENTORY,
	InjectContext,
	_is_vague_referent_turn,
	_trim_tagged_blocks,
	run_pre_llm_inject,
)
from prompt.t_now_strategy import STRATEGY_LEGACY, set_t_now_strategy
from prompt.turn_context import prepend_text_blocks_to_last_user


@pytest.fixture(autouse=True)
def _pin_legacy_channel():
	"""本模块冻结 legacy 尾插合同；显式钉住策略，不受全局默认影响。"""
	set_t_now_strategy(STRATEGY_LEGACY)
	yield
	set_t_now_strategy(None)


def _text_blocks(msg: dict) -> list[str]:
	content = msg.get("content")
	if isinstance(content, str):
		return [content]
	if isinstance(content, list):
		return [
			str(b.get("text") or "")
			for b in content
			if isinstance(b, dict) and b.get("type") == "text"
		]
	return []


def _fake_preview() -> str:
	return "# 浏览器预览（background only）\n当前预览页: http://localhost:5173"


def _patch_preview(monkeypatch, text: str = "") -> None:
	monkeypatch.setattr(
		"prompt.pre_llm_inject.browser_preview_block",
		lambda: text or _fake_preview(),
	)


def _prior_conversation(user_text: str) -> list[dict]:
	return [
		{"role": "user", "content": "帮我看看这个项目的记忆结构"},
		{"role": "assistant", "content": "好的，项目记忆分为 L4 与会话级。"},
		{"role": "user", "content": user_text},
	]


def test_inventory_head_directive_tail_on_fresh_user_turn(monkeypatch):
	_patch_preview(monkeypatch)
	from engine import repeat_guard

	monkeypatch.setattr(repeat_guard, "current_advice", lambda: "[repeat] x3")
	projected = _prior_conversation("看看当前预览页上有什么内容")
	out = run_pre_llm_inject(
		projected, InjectContext(working=None, include_memory_index=True)
	)
	texts = _text_blocks(out[-1])
	assert texts, "应有注入块"
	# A1：inventory 在用户原文之前，directive 在其后
	assert "浏览器预览" in texts[0]
	assert texts[1] == "看看当前预览页上有什么内容"
	assert any("Repeat guard" in t for t in texts[2:])


def test_vague_turn_drops_inventory_keeps_directives(monkeypatch):
	_patch_preview(monkeypatch)
	from engine import repeat_guard

	monkeypatch.setattr(repeat_guard, "current_advice", lambda: "[repeat] x3")
	projected = _prior_conversation("帮我修改")
	out = run_pre_llm_inject(
		projected, InjectContext(working=None, include_memory_index=True)
	)
	texts = _text_blocks(out[-1])
	joined = "\n".join(texts)
	# D1：模糊指代轮 → inventory 静默；批次3：index 永不在场
	assert "浏览器预览" not in joined
	assert "Memory index" not in joined
	# 指令类不受影响；用户原文完好
	assert "Repeat guard" in joined
	assert "帮我修改" in texts


def test_vague_gate_requires_antecedent(monkeypatch):
	_patch_preview(monkeypatch)
	# 首轮（无 assistant 上文）不门控：discovery 块仍应送达
	projected = [{"role": "user", "content": "帮我修改"}]
	out = run_pre_llm_inject(
		projected, InjectContext(working=None, include_memory_index=True)
	)
	assert "浏览器预览" in "\n".join(_text_blocks(out[-1]))


def test_vague_detector_boundaries():
	assert _is_vague_referent_turn(_prior_conversation("帮我修改"))
	assert _is_vague_referent_turn(_prior_conversation("继续"))
	assert _is_vague_referent_turn(_prior_conversation("可以"))
	# 带路径/代码标记 → 对象自明，不算模糊
	assert not _is_vague_referent_turn(
		_prior_conversation("修改 runtime.py 的这个函数")
	)
	# 超长 / 末条非 user / 无上文 → 不门控
	assert not _is_vague_referent_turn(
		_prior_conversation("请帮我把刚才讨论的分仓方案完整实现出来再告诉我结果")
	)
	assert not _is_vague_referent_turn([{"role": "user", "content": "帮我修改"}])
	after_tools = [
		{"role": "user", "content": "任务"},
		{"role": "assistant", "content": [{"type": "tool_use", "id": "1", "name": "Read"}]},
		{"role": "tool", "tool_call_id": "1", "content": "x"},
	]
	assert not _is_vague_referent_turn(after_tools)


def test_after_tools_keeps_legacy_contract(monkeypatch):
	_patch_preview(monkeypatch)
	projected = [
		{"role": "user", "content": "task"},
		{"role": "assistant", "content": [{"type": "tool_use", "id": "1", "name": "Read"}]},
		{"role": "tool", "tool_call_id": "1", "content": "x"},
	]
	out = run_pre_llm_inject(
		projected, InjectContext(working=None, include_memory_index=True)
	)
	texts = _text_blocks(out[-1])
	joined = "\n".join(texts)
	# after_tools：单插合成 user，Continue 在前；inventory 垫在指令之后
	assert texts[0].startswith("# Continue")
	assert "浏览器预览" in joined
	# 批次3：Memory index 永不进入 T_now（含 after_tools 轮）
	assert "Memory index" not in joined


def test_memory_index_no_longer_pushed(monkeypatch):
	"""批次3：事故源头块退役——索引块构造仍在（脚本/评测用），但永不入 T_now。"""
	monkeypatch.setattr(
		"memory.runtime.memory_index_context_block",
		lambda: (
			"# Memory index (background only — NOT the user request)\n"
			'<memory_index readonly="true">\n'
			"Memory index: 5 entries (feedback 3, user 2)\n"
			"</memory_index>"
		),
	)
	projected = _prior_conversation("看看记忆索引里有哪些类别")
	out = run_pre_llm_inject(
		projected, InjectContext(working=None, include_memory_index=True)
	)
	joined = "\n".join(_text_blocks(out[-1]))
	assert "<memory_index" not in joined
	assert "Memory index" not in joined


def test_trim_inventory_bounded_and_directive_survives():
	huge_notice = "# Runtime budget notice\n" + "d" * 5_500
	huge_index = "# Memory index\n" + "i" * 4_000
	kept = _trim_tagged_blocks(
		[
			(KLASS_DIRECTIVE, huge_notice),
			(KLASS_INVENTORY, huge_index),
		],
		total=6_000,
		inventory_max=2_500,
	)
	directive_total = sum(
		len(t) for k, t in kept if k == KLASS_DIRECTIVE
	)
	inventory_total = sum(len(t) for k, t in kept if k == KLASS_INVENTORY)
	# F1：directive 全保；inventory 被双闸裁剪
	assert directive_total == len(huge_notice)
	assert inventory_total <= 2_500
	assert any(t.endswith("…") for _k, t in kept if "Memory index" in t)


def test_wrap_up_survives_and_single(monkeypatch):
	_patch_preview(monkeypatch, "# 浏览器预览\n" + "z" * 4_000)
	projected = _prior_conversation("继续")
	out = run_pre_llm_inject(
		projected,
		InjectContext(working=None, include_memory_index=True, forced_wrap_up=True),
	)
	joined = "\n".join(_text_blocks(out[-1]))
	assert joined.count("Wrap-up(预算已尽)") == 1
	assert "浏览器预览" not in joined  # 模糊轮已静默


def test_prepend_helper_copy_on_write():
	original = [{"role": "user", "content": "帮我看看"}]
	frozen = [dict(original[0])]
	out = prepend_text_blocks_to_last_user(original, ["# 背景块\n数据"])
	assert original[0]["content"] == frozen[0]["content"]
	texts = _text_blocks(out[-1])
	assert texts[0] == "# 背景块\n数据"
	assert texts[-1] == "帮我看看"
	# 空块 → 原样返回
	assert prepend_text_blocks_to_last_user(original, ["", "  "]) is original


def test_reconcile_and_events_never_gated(monkeypatch):
	_patch_preview(monkeypatch)
	import extension.reconcile as reconcile_mod

	monkeypatch.setattr(
		reconcile_mod,
		"consume_reconcile_blocks",
		lambda: ["# 工具面变更（background only）\n新增工具 Foo"],
	)
	projected = _prior_conversation("帮我修改")
	out = run_pre_llm_inject(
		projected, InjectContext(working=None, include_memory_index=True)
	)
	joined = "\n".join(_text_blocks(out[-1]))
	# D1 只静默 inventory；事件类（reconcile）必须存活
	assert "浏览器预览" not in joined
	assert "Memory index" not in joined
	assert "工具面变更" in joined


# ---------------------------------------------------------------------------
# 批次1：Proposals 下线推送 / 思考回顾限 after_tools
# ---------------------------------------------------------------------------


def test_proposals_digest_no_longer_pushed(tmp_path, monkeypatch):
	"""批次1：Proposals 下线推送——模型对候选晋升无可执行动作。

	拉取通道：/proposals slash 命令 + Memory(action=search) 候选计数
	（memory_tool._proposals_notice_line）。
	"""
	from memory.working import WorkingSnapshot

	monkeypatch.setattr(
		"memory.instruction_maintain.format_proposals_digest",
		lambda _wsid: "# XEYO.md 写入提案（未自动应用）\n- (×3) 评测偏好用中文",
	)
	projected = _prior_conversation("看看有没有待处理的写入提案")
	out = run_pre_llm_inject(
		projected,
		InjectContext(
			working=WorkingSnapshot(session_id="t"),
			cwd=str(tmp_path),
			include_memory_index=True,
		),
	)
	# 注意断言特征串取自假 digest 专有文案（用户原文含「写入提案」字样）
	assert "未自动应用" not in "\n".join(_text_blocks(out[-1]))


# ---------------------------------------------------------------------------
# 批次2：Nested 限窗（只注入尾窗触碰目录的规则；滚出尾窗静默，回触恢复）
# ---------------------------------------------------------------------------


def _read_turn(pkg: Path, user_text: str) -> list[dict]:
	return [
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
		{"role": "user", "content": user_text},
	]


def test_nested_tail_window_filters_stale_dirs(tmp_path, monkeypatch):
	"""批次2：fresh-user 轮只挂尾窗触碰目录的规则；其他已加载目录静默。"""
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
	# 尾窗只触碰 pkg；末条带路径标记（非模糊轮）
	projected = _read_turn(pkg, "继续改 pkg/foo.py 的校验逻辑")
	out = run_pre_llm_inject(
		projected, InjectContext(working=snap, cwd=str(tmp_path))
	)
	joined = "\n".join(_text_blocks(out[-1]))
	assert "pkg-rule" in joined
	assert "other-rule" not in joined


def test_nested_tail_window_silent_when_no_recent_touch(tmp_path, monkeypatch):
	"""批次2：尾窗无触碰 → 嵌套规则整体静默；挂载集合不淘汰（回触即恢复）。"""
	from memory.working import WorkingSnapshot

	pkg = tmp_path / "pkg"
	pkg.mkdir()
	(pkg / "XEYO.md").write_text("pkg-rule", encoding="utf-8")
	snap = WorkingSnapshot(
		session_id="t",
		loaded_nested_instruction_paths=[str(pkg / "XEYO.md")],
	)
	out = run_pre_llm_inject(
		[{"role": "user", "content": "聊点别的吧，说说你今天遇到的有趣事情"}],
		InjectContext(working=snap, cwd=str(tmp_path)),
	)
	assert "pkg-rule" not in "\n".join(_text_blocks(out[-1]))
	# 挂载集合不淘汰
	assert str(pkg / "XEYO.md") in (snap.loaded_nested_instruction_paths or [])


def test_nested_tail_window_subtree_touch_remounts(tmp_path, monkeypatch):
	"""批次2：触碰规则目录的子树（pkg/sub/x.py）也恢复 pkg 规则。"""
	from memory.working import WorkingSnapshot

	pkg = tmp_path / "pkg"
	sub = pkg / "sub"
	sub.mkdir(parents=True)
	(pkg / "XEYO.md").write_text("pkg-rule", encoding="utf-8")
	snap = WorkingSnapshot(
		session_id="t",
		loaded_nested_instruction_paths=[str(pkg / "XEYO.md")],
	)
	projected = [
		{"role": "user", "content": "先看子目录"},
		{
			"role": "assistant",
			"content": [
				{
					"type": "tool_use",
					"id": "r2",
					"name": "Read",
					"input": {"file_path": str(sub / "x.py")},
				}
			],
		},
		{
			"role": "tool",
			"tool_call_id": "r2",
			"content": [
				{
					"type": "tool_result",
					"tool_use_id": "r2",
					"content": "ok",
					"is_error": False,
				}
			],
		},
		{"role": "user", "content": "继续改 pkg/sub/x.py 的实现"},
	]
	out = run_pre_llm_inject(
		projected, InjectContext(working=snap, cwd=str(tmp_path))
	)
	assert "pkg-rule" in "\n".join(_text_blocks(out[-1]))


# ---------------------------------------------------------------------------
# 批次4：Approved plan 首写收敛
# ---------------------------------------------------------------------------


def test_approved_plan_decays_on_first_successful_write():
	"""批次4：首写收敛判定——成功 Write/Edit 触发；失败与读工具不触发。"""
	from prompt.pre_llm_inject import approved_plan_decays_on as decays

	assert decays("Write", False)
	assert decays("Edit", False)
	assert decays("NotebookEdit", False)
	assert not decays("Write", True)  # 写失败不收敛
	assert not decays("Read", False)
	assert not decays("Grep", False)
	assert not decays("", False)


def test_query_loop_wires_plan_decay():
	"""批次4 源码契约：query_loop 工具落库后必须调用首写收敛判定，
	且首写后切换为"实施中"指针块（非彻底静默）。"""
	src = (
		Path(__file__).resolve().parents[1] / "engine" / "query_loop.py"
	).read_text(encoding="utf-8")
	assert "approved_plan_decays_on" in src
	assert "approved_plan = None" in src
	assert "plan_pointer = True" in src
	# 裁决 4：指针块只留指针事实，无引擎引导条款。
	from prompt.turn_context import PLAN_POINTER_BLOCK

	assert "已开始按已批准计划实施" in PLAN_POINTER_BLOCK
	assert "以证据为准" not in PLAN_POINTER_BLOCK
