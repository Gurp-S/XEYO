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
	"offload_read",  # hidden-but-registered：注册不进 schemas
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
	"Screenshot",
	"SendToWeChat",
	"Memory",
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
)


def test_enabled_tools_frozen():
	assert set(default_tool_names()) == set(_FROZEN_ENABLED)
	assert set(default_tool_names()) == ENABLED_META_NAMES


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
	assert registered == set(_FROZEN_ENABLED)
	# hidden-but-registered 工具（如 offload_read）注册但不进 schemas。
	from tools.meta import exposure_of

	hidden = {n for n in _FROZEN_ENABLED if exposure_of(reg.get(n)) == "hidden"}
	schema_names = {t["name"] for t in reg.schemas() if isinstance(t, dict)}
	assert schema_names == set(_FROZEN_ENABLED) - hidden


def test_meta_flags_match_instances():
	reg = build_default_registry(cwd=".")
	for name in _FROZEN_ENABLED:
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
