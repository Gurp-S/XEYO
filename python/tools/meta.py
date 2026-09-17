"""工具元数据单表 — policy / catalog / subagent / schema 短描述的唯一来源。

新增工具：在此登记一行，再在 catalog 挂工厂；勿再手抄 READONLY / 白名单。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

PolicyKind = Literal[
	"always_allow",
	"outbound_ask",
	"ui_ask",
	"read_path",
	"write_path",
	"agent_allow",
	"bash",
	"interactive",
]


@dataclass(frozen=True)
class ToolMeta:
	name: str
	read_only: bool
	concurrency_safe: bool
	policy: PolicyKind
	#: 可否出现在子 agent 注册表（False → 禁发）
	subagent_ok: bool = False
	#: 子 agent 默认基线白名单
	subagent_baseline: bool = False
	needs_write_store: bool = False
	needs_read_state: bool = False
	needs_runtime_provider: bool = False
	repeat_exempt: bool = False
	#: 发给模型的短 description（省 schema token）；空则保留工具自带全文
	short_description: str = ""
	#: False = 仅策略/测试用（如 echo），不进 ENABLED_TOOLS
	enabled: bool = True
	#: T1 per-tool 输出预算（字符）：None=默认 16000；0=豁免（自带截断或
	#: 防读回环，如 Bash 自带 spill、Read 防 read→spill→read）。
	output_budget: int | None = None
	#: F2（P0b）：normal=进 schemas；hidden=不进 schemas 但保留注册
	#: （模型幻觉调用仍走权限三态，fail-safe）。动态工具（无静态表项）
	#: 由实例同名属性携带（exposure_of 兜底解析）。
	exposure: Literal["normal", "hidden"] = "normal"


# ── 唯一登记表（按 name）──────────────────────────────────────────

TOOL_META: dict[str, ToolMeta] = {
	m.name: m
	for m in (
		ToolMeta(
			name="echo",
			read_only=True,
			concurrency_safe=True,
			policy="always_allow",
			short_description="Echo text back. Test/debug only.",
			enabled=False,
		),
		ToolMeta(
			name="getTime",
			read_only=True,
			concurrency_safe=True,
			policy="always_allow",
			short_description="Returns the current local date/time.",
		),
		ToolMeta(
			name="Glob",
			read_only=True,
			concurrency_safe=True,
			policy="read_path",
			subagent_ok=True,
			subagent_baseline=True,
			short_description=(
				"Finds files by glob. Optional path root; supports head_limit/offset "
				"pagination. Results contain file paths."
			),
		),
		ToolMeta(
			name="Grep",
			read_only=True,
			concurrency_safe=True,
			policy="read_path",
			subagent_ok=True,
			subagent_baseline=True,
			short_description=(
				"Searches file contents with rg. Supports path and glob filters. "
				"Results contain matching content locations."
			),
		),
		ToolMeta(
			name="Read",
			read_only=True,
			concurrency_safe=True,
			policy="read_path",
			subagent_ok=True,
			subagent_baseline=True,
			needs_read_state=True,
			# T1：Read 豁免 spill——防 read→spill→read 循环。
			output_budget=0,
			# 空：由 FileReadTool.schema() 按 vision 开关给出短描述（勿被静态短文覆盖）
			short_description="",
		),
		ToolMeta(
			name="Write",
			read_only=False,
			concurrency_safe=False,
			policy="write_path",
			subagent_ok=True,
			subagent_baseline=True,
			needs_write_store=True,
			needs_read_state=True,
			short_description="Creates or overwrites a file.",
		),
		ToolMeta(
			name="Edit",
			read_only=False,
			concurrency_safe=False,
			policy="write_path",
			subagent_ok=True,
			subagent_baseline=True,
			needs_write_store=True,
			needs_read_state=True,
			short_description="Replaces an exact string in a file.",
		),
		ToolMeta(
			name="Bash",
			read_only=False,
			concurrency_safe=False,
			policy="bash",
			# Phase 2：工人可下发；策略沙箱仅 bash_readonly_allow，其余 DENY（无 ASK）。
			subagent_ok=True,
			subagent_baseline=True,
			# T1：Bash 自带 raw→落盘→截断 seam（truncate_for_model），豁免
			# registry 级预算，避免双重截断/双重落盘。
			output_budget=0,
			short_description=(
				"Runs shell commands, including build/test/install/process/network "
				"and git operations. File listing, content search, file reads, "
				"file edits, and file writes are also exposed by dedicated tools."
			),
		),
	ToolMeta(
		name="TodoWrite",
		read_only=False,
		concurrency_safe=False,
		policy="always_allow",
		short_description="Replace the session todo list (full snapshot).",
	),
		ToolMeta(
			name="Screenshot",
			read_only=False,
			concurrency_safe=False,
			policy="outbound_ask",
			short_description="Capture the display (may send to WeChat when remote).",
		),
		ToolMeta(
			name="SendToWeChat",
			read_only=False,
			concurrency_safe=False,
			policy="outbound_ask",
			short_description="Send a workspace file to WeChat.",
		),
		ToolMeta(
			name="Memory",
			read_only=False,
			concurrency_safe=False,
			policy="write_path",
			subagent_ok=False,
			short_description="Read/write durable memory notes (main agent only).",
		),
		ToolMeta(
			name="AskUserQuestion",
			read_only=True,
			concurrency_safe=False,
			policy="interactive",
			repeat_exempt=True,
			short_description="Ask the user a question and wait for the answer.",
		),
		ToolMeta(
			name="JournalQuery",
			read_only=True,
			concurrency_safe=True,
			policy="always_allow",
			subagent_ok=True,
			subagent_baseline=True,
			short_description="Query rewind/journal entries (read-only).",
		),
		ToolMeta(
			name="Skill",
			read_only=True,
			concurrency_safe=True,
			policy="always_allow",
			subagent_ok=True,
			subagent_baseline=False,
			short_description="Load on-demand playbook from .xeyo/skills/<name>/SKILL.md.",
		),
		ToolMeta(
			name="Agent",
			read_only=False,
			concurrency_safe=True,
			policy="agent_allow",
			subagent_ok=False,
			needs_write_store=True,
			needs_runtime_provider=True,
			short_description=(
				"Spawns a short-lived sub-agent. Sub-agents have Git and a "
				"readonly Bash sandbox; Memory and nested Agents are unavailable."
			),
		),
		ToolMeta(
			name="Diagnostics",
			read_only=True,
			concurrency_safe=True,
			policy="read_path",
			subagent_ok=True,
			subagent_baseline=True,
			short_description=(
				"Diagnostics for a required path. Not a full LSP."
			),
		),
		ToolMeta(
			name="Git",
			read_only=True,
			concurrency_safe=True,
			policy="always_allow",
			subagent_ok=True,
			subagent_baseline=True,
			short_description="Read-only git: summary/status/log/branches/diff. No commit.",
		),
		ToolMeta(
			name="NotebookEdit",
			read_only=False,
			concurrency_safe=False,
			policy="write_path",
			subagent_ok=True,
			subagent_baseline=False,
			needs_write_store=True,
			needs_read_state=True,
			short_description="Edits .ipynb files by cell.",
		),
		ToolMeta(
			name="WebFetch",
			read_only=False,
			concurrency_safe=False,
			policy="outbound_ask",
			subagent_ok=False,
			short_description="Fetch public URL text (ASK). No private hosts.",
		),
		ToolMeta(
			name="WebSearch",
			read_only=False,
			concurrency_safe=False,
			policy="outbound_ask",
			subagent_ok=False,
			short_description="Web search (ASK). Returns titles/urls/snippets.",
		),
		ToolMeta(
			name="XeyoUI",
			read_only=False,
			concurrency_safe=False,
			policy="ui_ask",
			subagent_ok=False,
			short_description=(
				"Desktop UI: list_sessions | open_preview | open_panel | "
				"show_tool_flow | send_to_session (ASK except list)."
			),
		),
		# ── 42 号：后台任务三工具（恒注册；owner 即安全边界）──────────────
		ToolMeta(
			name="job_output",
			read_only=True,
			concurrency_safe=True,
			policy="always_allow",
			repeat_exempt=True,
			short_description=(
				"Read a background job's output (incremental; wait=true blocks "
				"until done). Ends with [status: ...]."
			),
		),
		ToolMeta(
			name="job_list",
			read_only=True,
			concurrency_safe=True,
			policy="always_allow",
			short_description="List this session's background jobs.",
		),
		ToolMeta(
			name="job_kill",
			read_only=False,
			concurrency_safe=False,
			policy="always_allow",
			subagent_ok=False,
			short_description=(
				"Request cancellation of one of this session's background jobs."
			),
		),
	)
}


def meta_for(name: str) -> ToolMeta | None:
	return TOOL_META.get((name or "").strip())


def exposure_of(tool: Any) -> str:
	"""F2 exposure 解析：静态表项优先；动态工具（MCP）读实例同名属性。

	返回 "normal" | "hidden"；异常/缺失一律按 "normal"（宁可见勿丢）。
	"""
	m = meta_for(str(getattr(tool, "name", "") or ""))
	if m is not None:
		return m.exposure
	return str(getattr(tool, "exposure", "") or "normal")


def short_description_for(name: str) -> str:
	m = meta_for(name)
	return (m.short_description if m else "") or ""


def schema_budget_enabled() -> bool:
	"""默认开短 description；``XEYO_TOOL_SCHEMA_FULL=1`` 保留工具全文。"""
	raw = os.environ.get("XEYO_TOOL_SCHEMA_FULL", "0").strip().lower()
	return raw not in ("1", "true", "yes", "on")


def apply_schema_budget(schema: dict) -> dict:
	"""浅拷贝并替换 description（若有短文案且预算开启）。"""
	name = str(schema.get("name") or "")
	short = short_description_for(name)
	if not short or not schema_budget_enabled():
		# 无短文案时保留工具 schema() 自带描述（如 Read vision 开关）
		out = dict(schema)
		desc = str(out.get("description") or "")
		# Read：仍压到一行短句，避免全文进 budget 路径时过长
		if name == "Read" and schema_budget_enabled() and len(desc) > 220:
			vision = "vision attachments" in desc.lower() or "rendered as image" in desc.lower() or (
				"png/jpg" in desc.lower()
			)
			out["description"] = (
				"Read text or image/PDF (vision on). offset=page for PDF."
				if vision
				else "Read a text file (offset/limit for long files)."
			)
		return out
	out = dict(schema)
	out["description"] = short
	return out


# ── 派生集合（供 policy / catalog / scheduler / repeat_guard）────────

ALWAYS_ALLOW_TOOLS = frozenset(
	m.name for m in TOOL_META.values() if m.policy == "always_allow"
)
OUTBOUND_ASK_TOOLS = frozenset(
	m.name for m in TOOL_META.values() if m.policy == "outbound_ask"
)
UI_ASK_TOOLS = frozenset(
	m.name for m in TOOL_META.values() if m.policy == "ui_ask"
)
READ_PATH_TOOLS = frozenset(
	m.name for m in TOOL_META.values() if m.policy == "read_path"
)
WRITE_PATH_TOOLS = frozenset(
	m.name for m in TOOL_META.values() if m.policy == "write_path"
)
# 无实例时 ask/plan 回退：只读且非交互/外发/UI
READONLY_ALLOW = frozenset(
	m.name
	for m in TOOL_META.values()
	if m.read_only and m.policy not in ("interactive", "outbound_ask", "ui_ask")
)
READONLY_ASK_ALLOW = frozenset(
	m.name for m in TOOL_META.values() if m.policy == "interactive"
)
SUBSET_TOOL_BASELINE = frozenset(
	m.name for m in TOOL_META.values() if m.subagent_baseline
)
FORBIDDEN_SUB_TOOLS = frozenset(
	m.name for m in TOOL_META.values() if m.enabled and not m.subagent_ok
)
REPEAT_EXEMPT_TOOLS = frozenset(
	m.name for m in TOOL_META.values() if m.repeat_exempt
)
WRITE_STORE_TOOL_NAMES = frozenset(
	m.name for m in TOOL_META.values() if m.needs_write_store
)
READ_STATE_TOOL_NAMES = frozenset(
	m.name for m in TOOL_META.values() if m.needs_read_state
)
RUNTIME_PROVIDER_TOOL_NAMES = frozenset(
	m.name for m in TOOL_META.values() if m.needs_runtime_provider
)
ENABLED_META_NAMES = frozenset(
	m.name for m in TOOL_META.values() if m.enabled
)

# 兼容旧名
SUBSET_TOOL_WHITELIST = SUBSET_TOOL_BASELINE
