"""Pre-LLM 注入：T_now 尾插、嵌套 XEYO.md、C2 清空、不改 JSONL/左段。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.query_loop import _attach_turn_context
from memory.working import WorkingSnapshot, note_c2
from permissions.policy import set_agent_mode
from prompt.pre_llm_inject import (
	InjectContext,
	_collect_successful_read_paths,
	_trim_blocks_to_budget,
	run_pre_llm_inject,
)


def _joined_user_texts(msgs: list[dict]) -> str:
	"""兼容两种声道的注入文本提取。

	legacy：末条 user 的 text 块；env_channel（方案A）：伪造对 tool_result 正文。
	遍历全部消息的 text / tool_result 块，负向断言依赖注入块不出现（而非
	依赖位置），对两种声道同样成立。
	"""
	parts: list[str] = []
	for m in msgs:
		if not isinstance(m, dict):
			continue
		content = m.get("content")
		if isinstance(content, str):
			parts.append(content)
		elif isinstance(content, list):
			for b in content:
				if not isinstance(b, dict):
					continue
				if b.get("type") == "text":
					parts.append(str(b.get("text") or ""))
				elif b.get("type") == "tool_result":
					parts.append(str(b.get("content") or ""))
	return "\n".join(parts)


def test_run_pre_llm_inject_does_not_mutate_input():
	projected = [{"role": "user", "content": "hi"}]
	snap = WorkingSnapshot(session_id="t")
	out = run_pre_llm_inject(
		projected,
		InjectContext(working=snap, cwd="", forced_wrap_up=True),
	)
	assert projected[0]["content"] == "hi"
	assert out is not projected
	assert "Wrap-up required" in _joined_user_texts(out)


def test_repeat_guard_block_injected_as_t_now(monkeypatch):
	"""T6：current_advice 非空时挂 Repeat guard（background only）块。"""
	from engine import repeat_guard

	monkeypatch.setattr(
		repeat_guard, "current_advice", lambda: "[repeat] 'Grep' 已连续调用 3 次。"
	)
	projected = [{"role": "user", "content": "hi"}]
	out = run_pre_llm_inject(
		projected, InjectContext(working=WorkingSnapshot(session_id="t"), cwd="")
	)
	blob = _joined_user_texts(out)
	assert "# Repeat guard（background only）" in blob
	assert "已连续调用 3 次" in blob

	monkeypatch.setattr(repeat_guard, "current_advice", lambda: "")
	out2 = run_pre_llm_inject(
		projected, InjectContext(working=WorkingSnapshot(session_id="t"), cwd="")
	)
	assert "Repeat guard" not in _joined_user_texts(out2)


def test_after_tools_hangs_new_nested_skips_memory(tmp_path, monkeypatch):
	"""工具续写轮：挂本轮新 Nested；不挂 Memory / Stale / Proposals。"""
	set_agent_mode("agent")
	root = tmp_path
	pkg = root / "pkg"
	pkg.mkdir()
	(pkg / "XEYO.md").write_text("用中文注释", encoding="utf-8")
	(pkg / "foo.py").write_text("x=1\n", encoding="utf-8")

	monkeypatch.setattr(
		"memory.runtime.memory_index_context_block",
		lambda: "# Memory index\nshould-not-appear",
	)
	monkeypatch.setattr(
		"memory.instruction_maintain.stale_instruction_notice",
		lambda _cwd, commit=True: "# XEYO.md 可能过时\nstale-should-not",
	)
	monkeypatch.setattr(
		"memory.instruction_maintain.format_proposals_digest",
		lambda _wsid: "# proposals\nprop-should-not",
	)

	snap = WorkingSnapshot(session_id="t")
	projected = [
		{"role": "user", "content": "task"},
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
			"name": "Read",
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
	]
	before = [dict(m) for m in projected]
	out = run_pre_llm_inject(
		projected,
		InjectContext(
			working=snap,
			cwd=str(root),
			include_memory_index=True,
			approved_plan="do it",
		),
	)
	joined = _joined_user_texts(out)
	assert "Continue" in joined
	assert "Approved plan" in joined
	assert "Memory index" not in joined
	assert "用中文注释" in joined  # 本轮新 Nested
	assert "可能过时" not in joined
	assert "prop-should-not" not in joined
	assert snap.loaded_nested_instruction_paths
	assert projected[0]["content"] == before[0]["content"]


def test_nested_hangs_on_non_tool_tail(tmp_path, monkeypatch):
	set_agent_mode("agent")
	root = tmp_path
	pkg = root / "pkg"
	pkg.mkdir()
	nested_md = pkg / "XEYO.md"
	nested_md.write_text("永远用中文回复子目录规则", encoding="utf-8")
	(pkg / "foo.py").write_text("x=1\n", encoding="utf-8")

	monkeypatch.setattr("memory.runtime.memory_index_context_block", lambda: "")
	monkeypatch.setattr(
		"memory.instruction_maintain.stale_instruction_notice",
		lambda _cwd, commit=True: "",
	)
	monkeypatch.setattr(
		"memory.instruction_maintain.format_proposals_digest",
		lambda _wsid: "",
	)

	snap = WorkingSnapshot(session_id="t")
	with_read = [
		{"role": "user", "content": "task"},
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
			"name": "Read",
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
	]
	run_pre_llm_inject(
		with_read,
		InjectContext(working=snap, cwd=str(root), include_memory_index=True),
	)
	assert any("XEYO.md" in p for p in snap.loaded_nested_instruction_paths)

	# 批次2 限窗：尾窗内触碰过 pkg → 其规则在 fresh-user 轮仍然挂载
	# （同一投影追加新 user 轮，Read 仍在 READ_SCAN_TAIL 窗内；
	#  末条带路径标记，避开 D1 模糊轮门控）
	projected_user = with_read + [{"role": "user", "content": "继续改 pkg/foo.py"}]
	out = run_pre_llm_inject(
		projected_user,
		InjectContext(working=snap, cwd=str(root), include_memory_index=True),
	)
	joined = _joined_user_texts(out[-1:])
	assert "Nested instructions" in joined
	assert "永远用中文回复子目录规则" in joined


def test_failed_read_does_not_discover_nested(tmp_path):
	set_agent_mode("agent")
	root = tmp_path
	pkg = root / "pkg"
	pkg.mkdir()
	(pkg / "XEYO.md").write_text("secret", encoding="utf-8")
	snap = WorkingSnapshot(session_id="t")
	projected = [
		{"role": "user", "content": "task"},
		{
			"role": "assistant",
			"content": [
				{
					"type": "tool_use",
					"id": "r1",
					"name": "Read",
					"input": {"file_path": str(pkg / "missing.py")},
				}
			],
		},
		{
			"role": "tool",
			"name": "Read",
			"tool_call_id": "r1",
			"content": [
				{
					"type": "tool_result",
					"tool_use_id": "r1",
					"content": "not found",
					"is_error": True,
				}
			],
		},
	]
	run_pre_llm_inject(
		projected,
		InjectContext(working=snap, cwd=str(root), include_memory_index=True),
	)
	assert snap.loaded_nested_instruction_paths == []


def test_subagent_skips_nested_via_inject_instructions(tmp_path, monkeypatch):
	set_agent_mode("agent")
	root = tmp_path
	pkg = root / "pkg"
	pkg.mkdir()
	(pkg / "XEYO.md").write_text("nested-rule", encoding="utf-8")
	snap = WorkingSnapshot(
		session_id="t",
		loaded_nested_instruction_paths=[str(pkg / "XEYO.md")],
	)
	monkeypatch.setattr("memory.runtime.memory_index_context_block", lambda: "# Memory")
	out = run_pre_llm_inject(
		[{"role": "user", "content": "work"}],
		InjectContext(
			working=snap,
			cwd=str(root),
			include_memory_index=False,
			inject_instructions=False,
		),
	)
	joined = _joined_user_texts(out)
	assert "nested-rule" not in joined
	assert "Memory" not in joined


def test_note_c2_clears_nested_paths():
	snap = WorkingSnapshot(
		session_id="t",
		loaded_nested_instruction_paths=["/tmp/pkg/XEYO.md"],
	)
	note_c2(snap, 3)
	assert snap.loaded_nested_instruction_paths == []
	assert snap.compact_cursor == 3


def test_try_extend_c2_clears_nested_paths():
	from memory.runtime import try_extend_c2
	from memory.simulator.params import load_params

	snap = WorkingSnapshot(
		session_id="t",
		compact_cursor=2,
		c2_summary_text="old summary",
		loaded_nested_instruction_paths=["/x/XEYO.md"],
	)
	msgs = [
		{"role": "user", "content": "a"},
		{"role": "assistant", "content": "b"},
		{"role": "user", "content": "c" * 5000},
		{"role": "assistant", "content": "d" * 5000},
		{"role": "user", "content": "e"},
	]
	ok = try_extend_c2(snap, msgs, 4, load_params(), remaining_turns=20, force=True)
	assert ok is True
	assert snap.loaded_nested_instruction_paths == []
	assert snap.compact_cursor == 4


def test_attach_turn_context_thin_wrapper_compat(monkeypatch):
	set_agent_mode("agent")
	monkeypatch.setattr("memory.runtime.memory_index_context_block", lambda: "")
	projected = [{"role": "user", "content": "hi"}]
	out = _attach_turn_context(
		projected,
		approved_plan=None,
		forced_wrap_up=True,
		runtime_notice="预算到了",
		include_memory_index=False,
	)
	joined = _joined_user_texts(out)
	assert "Wrap-up required" in joined
	assert "Runtime budget notice" in joined
	assert projected[0]["content"] == "hi"


def test_jsonl_store_untouched_by_inject():
	store_api = [
		{"role": "user", "content": "权威"},
		{"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
	]
	import copy

	frozen = copy.deepcopy(store_api)
	out = run_pre_llm_inject(
		store_api,
		InjectContext(forced_wrap_up=True, include_memory_index=False),
	)
	assert store_api == frozen
	assert out[-1]["role"] == "user"


def test_budget_keeps_continue_and_nested_before_notice():
	huge = "x" * 8_000
	nested = (
		"# Nested instructions（background only — 按需，读到该目录才加载）\n"
		+ "### nested:/pkg/XEYO.md\n"
		+ "rule-body-"
		+ ("y" * 500)
	)
	blocks = [
		"# Continue（续写原问题 — 不是新用户消息）\nok",
		nested,
		"# Runtime budget notice\n" + huge,
	]
	out = _trim_blocks_to_budget(blocks, budget=3_000, nested_reserve=2_000)
	joined = "\n".join(out)
	assert "Continue" in joined
	assert "Nested instructions" in joined or "nested:" in joined
	# notice 可能被截断或挤掉，但不应导致 Nested 完全消失
	assert "rule-body" in joined


def test_read_scan_tail_only():
	"""尾窗外的旧 Read 不应被扫到。"""
	old_path = "D:/old/pkg/foo.py"
	new_path = "D:/new/pkg/bar.py"
	msgs: list[dict] = []
	# 造很多噪音消息，把旧 Read 顶出尾窗
	for i in range(80):
		msgs.append({"role": "user", "content": f"u{i}"})
	msgs.extend(
		[
			{
				"role": "assistant",
				"content": [
					{
						"type": "tool_use",
						"id": "old",
						"name": "Read",
						"input": {"file_path": old_path},
					}
				],
			},
			{
				"role": "tool",
				"name": "Read",
				"tool_call_id": "old",
				"content": [
					{
						"type": "tool_result",
						"tool_use_id": "old",
						"content": "old",
						"is_error": False,
					}
				],
			},
		]
	)
	for i in range(70):
		msgs.append({"role": "assistant", "content": f"a{i}"})
	msgs.extend(
		[
			{
				"role": "assistant",
				"content": [
					{
						"type": "tool_use",
						"id": "new",
						"name": "Read",
						"input": {"file_path": new_path},
					}
				],
			},
			{
				"role": "tool",
				"name": "Read",
				"tool_call_id": "new",
				"content": [
					{
						"type": "tool_result",
						"tool_use_id": "new",
						"content": "new",
						"is_error": False,
					}
				],
			},
		]
	)
	paths = _collect_successful_read_paths(msgs, tail=64)
	assert new_path in paths
	assert old_path not in paths


def test_stale_commit_only_when_injected(tmp_path, monkeypatch):
	"""注入成功进 T_now 后才 refresh stamp。"""
	root = tmp_path / "proj"
	root.mkdir()
	snap = WorkingSnapshot(session_id="t")
	calls: list[str] = []

	def fake_stale(cwd, commit=True):
		if commit:
			return ""
		return "# XEYO.md 可能过时\n探测文件已变：package.json。"

	def fake_refresh(cwd):
		calls.append(cwd)
		return {}

	monkeypatch.setattr("memory.runtime.memory_index_context_block", lambda: "")
	monkeypatch.setattr(
		"memory.instruction_maintain.format_proposals_digest",
		lambda _wsid: "",
	)
	monkeypatch.setattr(
		"memory.instruction_maintain.stale_instruction_notice",
		fake_stale,
	)
	monkeypatch.setattr(
		"memory.instruction_maintain.refresh_instruction_stamp",
		fake_refresh,
	)
	out = run_pre_llm_inject(
		[{"role": "user", "content": "hi"}],
		InjectContext(working=snap, cwd=str(root), include_memory_index=True),
	)
	joined = _joined_user_texts(out)
	assert "可能过时" in joined
	assert len(calls) == 1
	assert Path(calls[0]).resolve() == root.resolve() or calls[0] == str(root)


def test_stale_peek_without_commit(tmp_path):
	from memory.instruction_maintain import stale_instruction_notice

	root = tmp_path / "proj"
	root.mkdir()
	(root / "package.json").write_text('{"dependencies":{"a":"1"}}', encoding="utf-8")
	assert stale_instruction_notice(str(root)) == ""
	(root / "package.json").write_text('{"dependencies":{"a":"2"}}', encoding="utf-8")
	peek = stale_instruction_notice(str(root), commit=False)
	assert "过时" in peek or "package.json" in peek
	assert stale_instruction_notice(str(root), commit=False)


def test_previous_reasoning_tail_is_injected():
	"""批次1：思考截选仅工具续写轮注入；fresh-user 轮不注入（旧任务残留）。"""
	from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject

	tail = "...想到这里，下一步该读配置文件"
	after_tools = [
		{"role": "user", "content": "task"},
		{
			"role": "assistant",
			"content": [{"type": "tool_use", "id": "1", "name": "Read"}],
		},
		{"role": "tool", "tool_call_id": "1", "content": "x"},
	]
	out = run_pre_llm_inject(
		after_tools, InjectContext(previous_reasoning_tail=tail)
	)
	blob = str(out)
	assert "上一轮思考回顾" in blob
	assert "下一步该读配置文件" in blob
	assert "不要逐字重复" in blob

	fresh = run_pre_llm_inject(
		[{"role": "user", "content": "新问题"}],
		InjectContext(previous_reasoning_tail=tail),
	)
	assert "上一轮思考回顾" not in str(fresh)


def test_browser_preview_block_injected():
	from permissions.policy import set_browser_preview_url
	from prompt.pre_llm_inject import browser_preview_block

	set_browser_preview_url("http://localhost:5173")
	try:
		block = browser_preview_block()
		assert "http://localhost:5173" in block
		assert "WebFetch" in block
		out = run_pre_llm_inject(
			[{"role": "user", "content": "hi"}],
			InjectContext(cwd="/proj", session_id="s1"),
		)
		assert "http://localhost:5173" in _joined_user_texts(out)
	finally:
		set_browser_preview_url(None)


def test_browser_preview_block_skips_invalid():
	from permissions.policy import set_browser_preview_url
	from prompt.pre_llm_inject import browser_preview_block

	set_browser_preview_url("javascript:alert(1)")
	try:
		assert browser_preview_block() == ""
	finally:
		set_browser_preview_url(None)


def test_runtime_mode_snapshot_turn_first_then_no_repeat_then_subagent_skip():
	from permissions.runtime_mode import get_runtime_mode_store
	from prompt.pre_llm_inject import InjectContext, run_pre_llm_inject

	sid = "rtmt-inject-test"
	store = get_runtime_mode_store()
	store.clear(sid)
	try:
		store.set(sid, "always")
		store.begin_turn(sid, "risk")  # 本轮首有活值 → armed，turn 首必发
		out = run_pre_llm_inject(
			[{"role": "user", "content": "hi"}],
			InjectContext(cwd="", session_id=sid, include_memory_index=False),
		)
		blob = _joined_user_texts(out)
		assert "supersedes" in blob
		assert "当前审批模式: always" in blob
		# #2：纯状态陈述，不含引导词。
		assert "继续" not in blob

		# #1：同 turn 轮内不再重复（即便轮中改活值）。
		store.set(sid, "never")
		out2 = run_pre_llm_inject(
			[{"role": "user", "content": "hi"}],
			InjectContext(cwd="", session_id=sid, include_memory_index=False),
		)
		assert "当前审批模式: always" not in _joined_user_texts(out2)

		# 子代理：净化清单跳过主会话 GUI 模式广播。
		out3 = run_pre_llm_inject(
			[{"role": "user", "content": "hi"}],
			InjectContext(
				cwd="", session_id=sid, include_memory_index=False, subagent=True
			),
		)
		assert "当前审批模式: always" not in _joined_user_texts(out3)
	finally:
		store.clear(sid)
