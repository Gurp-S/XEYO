"""工具目录冻结守卫：能力矩阵、meta 契约、schema 预算、未知工具不透传。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.base_tool import tool_flag
from tools.catalog import (
	ENABLED_TOOL_ENTRIES,
	TOOL_FACTORY_BY_NAME,
	build_default_registry,
	build_subagent_registry,
	default_tool_names,
	factory_for,
	tools_system_hint,
)
from tools.fileio.read_state import ReadFileState
from tools.meta import (
	ENABLED_META_NAMES,
	FORBIDDEN_SUB_TOOLS,
	READ_PATH_TOOLS,
	READONLY_ALLOW,
	REPEAT_EXEMPT_TOOLS,
	SUBSET_TOOL_BASELINE,
	TOOL_META,
	WRITE_STORE_TOOL_NAMES,
	apply_schema_budget,
	meta_for,
	short_description_for,
)
from permissions.filesystem import PermissionDecision
from permissions.policy import (
	READONLY_ALLOW as POLICY_READONLY,
	READONLY_ASK_ALLOW as POLICY_ASK,
	evaluate_policy,
)


_FROZEN_ENABLED = (
	"getTime",
	# `offload_read` 已于 2026-09-16 删除（用户裁定：expand/offload/Read 是同一功能，
	# 只保留 Read；取回引用统一成 `Read(file_path=…, offset=…, limit=…)`）。
	"Glob",
	"Grep",
	"Read",
	"Write",
	"Edit",
	"Bash",
	"TodoWrite",
	# 42 号：后台任务三工具（恒注册，schema 不随状态抖动）。
	"job_output",
	"job_list",
	"job_kill",
	"agent_send",
	"Screenshot",
	"SendToWeChat",
	"Memory",
	"Compact",
	"AskUserQuestion",
	"JournalQuery",
	"Skill",
	"Agent",
	"Diagnostics",
	"Git",
	"NotebookEdit",
	"WebFetch",
	"WebSearch",
	"XeyoUI",
	# 旁路能力（2026-10-14）：登记在矩阵里但**默认不在工作面**——由
	# tools/catalog.py 的 GATED_TOOL_FLAGS 按 feature flag 过滤。
	# 见下方 _GATED_DEFAULT_OFF。
	"Workflow",
	"Lsp",
)

#: 默认关的旁路工具（flag 打开后才进 schemas 与子 agent 注册表）。
_GATED_DEFAULT_OFF = frozenset({"Workflow", "Lsp"})


def test_enabled_tools_frozen():
	assert set(default_tool_names()) == set(_FROZEN_ENABLED)
	assert set(default_tool_names()) == ENABLED_META_NAMES


def test_gated_tools_absent_unless_flag_on(monkeypatch):
	"""默认（flag 未设）旁路工具不在工作面；置 1 后进工作面。"""
	from tools.catalog import GATED_TOOL_FLAGS

	for name, flag in GATED_TOOL_FLAGS.items():
		monkeypatch.delenv(flag, raising=False)
	reg = build_default_registry(cwd=".")
	assert _GATED_DEFAULT_OFF.isdisjoint(set(reg._tools))  # type: ignore[attr-defined]
	for flag in GATED_TOOL_FLAGS.values():
		monkeypatch.setenv(flag, "1")
	reg_on = build_default_registry(cwd=".")
	for name in _GATED_DEFAULT_OFF:
		assert reg_on.get(name) is not None
		assert any(s.get("name") == name for s in reg_on.schemas())


def test_system_hint_is_thin_policy():
	hint = tools_system_hint()
	assert hint == ""
	assert "Available tools:" not in hint


def test_tool_descriptions_have_no_migrate_prefix():
	reg = build_default_registry(cwd=".")
	for schema in reg.schemas():
		desc = str(schema.get("description") or "")
		assert not desc.startswith("description"), schema.get("name")
		assert "descriptionAsk" not in desc
		assert "descriptionCapture" not in desc
		assert "descriptionSend" not in desc


def test_unknown_tool_not_passthrough():
	decision = evaluate_policy("__no_such_tool__", {}, cwd=".")
	assert decision.decision == PermissionDecision.ASK


def test_default_registry_matches_frozen_names():
	reg = build_default_registry(cwd=".")
	registered = set(reg._tools)  # type: ignore[attr-defined]
	# 旁路工具默认关 ⇒ 不在默认注册表里（见 _GATED_DEFAULT_OFF）。
	expected = set(_FROZEN_ENABLED) - _GATED_DEFAULT_OFF
	assert registered == expected
	# exposure 过滤语义：hidden 的工具注册但不进 schemas。
	# 当前 hidden = {"Git"}（2026-10-13 旁路：Git 从模型可见面摘除、保留注册，
	# 理由见 tools/meta.py 的 Git 条目）。hidden 集合变化时请连同本条一起更新。
	from tools.meta import exposure_of

	hidden = {n for n in expected if exposure_of(reg.get(n)) == "hidden"}
	schema_names = {t["name"] for t in reg.schemas() if isinstance(t, dict)}
	assert hidden == {"Git"}, "hidden 集合变化时请连同本条注释一起更新"
	assert schema_names == expected - hidden


def test_meta_flags_match_instances():
	reg = build_default_registry(cwd=".")
	for name in set(_FROZEN_ENABLED) - _GATED_DEFAULT_OFF:
		m = meta_for(name)
		assert m is not None
		tool = reg.get(name)
		assert tool is not None
		assert tool_flag(tool, "is_read_only") is m.read_only
		assert tool_flag(tool, "is_concurrency_safe") is m.concurrency_safe
		# Read 的短描述由 schema() 按 vision 动态给出；meta.short 可为空
		if name != "Read":
			assert short_description_for(name)
		assert name in TOOL_FACTORY_BY_NAME
		assert factory_for(name) is TOOL_FACTORY_BY_NAME[name]


def test_policy_sets_derived_from_meta():
	assert POLICY_READONLY == READONLY_ALLOW
	assert "AskUserQuestion" in POLICY_ASK
	assert "Read" in READ_PATH_TOOLS
	assert "Agent" in FORBIDDEN_SUB_TOOLS
	assert "Bash" not in FORBIDDEN_SUB_TOOLS
	assert "Memory" in FORBIDDEN_SUB_TOOLS
	assert "_agent" not in FORBIDDEN_SUB_TOOLS
	assert SUBSET_TOOL_BASELINE == frozenset(
		{
			"Read",
			"Write",
			"Edit",
			"JournalQuery",
			"Grep",
			"Glob",
			"Diagnostics",
			"Bash",
			"Git",
		}
	)
	# TodoWrite 已改为"相同快照才计重复"（见 test_repeat_guard）；
	# 整体豁免只剩交互工具。
	assert "TodoWrite" not in REPEAT_EXEMPT_TOOLS
	assert "AskUserQuestion" in REPEAT_EXEMPT_TOOLS
	assert WRITE_STORE_TOOL_NAMES >= frozenset({"Write", "Edit", "Agent", "NotebookEdit"})


def test_schema_budget_shortens_descriptions(monkeypatch):
	monkeypatch.delenv("XEYO_TOOL_SCHEMA_FULL", raising=False)
	reg = build_default_registry(cwd=".")
	for schema in reg.schemas():
		name = schema["name"]
		short = short_description_for(name)
		desc = schema["description"]
		if short:
			assert desc == short
			assert len(short) < 200
		else:
			# Read 等动态描述：预算仍压到合理长度
			assert len(desc) < 400
	# 全文模式
	monkeypatch.setenv("XEYO_TOOL_SCHEMA_FULL", "1")
	full = apply_schema_budget({"name": "Agent", "description": "LONG" * 50})
	assert full["description"] == "LONG" * 50


def test_entries_align_with_meta():
	assert {n for n, _ in ENABLED_TOOL_ENTRIES} == ENABLED_META_NAMES
	assert set(TOOL_META) >= ENABLED_META_NAMES


def test_shared_read_state_and_subagent_reuse():
	"""子 agent registry 应复用主 registry 的 ReadFileState 实例（同册）。"""
	from tools.catalog import shared_read_state

	reg = build_default_registry(cwd=".")
	state = shared_read_state(reg)
	assert isinstance(state, ReadFileState)
	# 注入同一实例 → 子 agent 写文件主会话可见（时间戳新鲜）。
	sub = build_subagent_registry(
		cwd=".", tool_names=["Read", "Edit"], read_state=state, agent_id="main"
	)
	assert shared_read_state(sub) is state
