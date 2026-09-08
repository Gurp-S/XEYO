"""工具目录 — 为引擎启用工具的统一入口。

工作流：在 tools/<name>_tool/ 包内实现 execute() 与 prompt.py，在 ``tools.meta``
登记元数据，再把 ``(name, factory)`` 加入 ENABLED_TOOL_ENTRIES。
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Any

from tools.base_tool import (
	AgentIdAware,
	ReadStateAware,
	RuntimeProviderAware,
	Tool,
	WriteStoreAware,
	tool_flag,
)
from tools.fileio.read_state import ReadFileState
from tools.meta import (
	ENABLED_META_NAMES,
	FORBIDDEN_SUB_TOOLS,
	READ_STATE_TOOL_NAMES,
	RUNTIME_PROVIDER_TOOL_NAMES,
	SUBSET_TOOL_BASELINE,
	SUBSET_TOOL_WHITELIST,
	WRITE_STORE_TOOL_NAMES,
	meta_for,
)
from tools.tool_registry import ToolRegistry

# ---------------------------------------------------------------------------
# 工具类惰性解析(PEP 562 模块 __getattr__):工厂函数体引用的类名在
# **首次调用**时才真正 import。import tools.catalog 因此不拖 24 个工具模块
# (启动 import 329ms→数十 ms;registry 构建语义不变,仍逐个实例化)。
# 首次解析后写入模块全局缓存,后续访问零开销。
# ---------------------------------------------------------------------------
_LAZY_TOOL_IMPORTS: dict[str, str] = {
	"AskUserQuestionTool": "tools.ask_user_question_tool",
	"FileReadTool": "tools.file_read_tool.file_read_tool",
	"FileWriteTool": "tools.file_write_tool.file_write_tool",
	"GetTimeTool": "tools.get_time",
	"OffloadReadTool": "tools.offload_read_tool",
	"GlobTool": "tools.glob_tool.glob_tool",
	"GrepTool": "tools.grep_tool.grep_tool",
	"MemoryTool": "tools.memory_tool",
	"BashTool": "tools.bash_tool.bash_tool",
	"FileEditTool": "tools.file_edit_tool.file_edit_tool",
	"SkillTool": "tools.skill_tool",
	"ScreenshotTool": "tools.screenshot_tool",
	"SendToWeChatTool": "tools.send_to_wechat_tool",
	"TodoWriteTool": "tools.todo_write_tool.todo_write_tool",
	"AgentTool": "tools.agent_tool",
	"JournalQueryTool": "tools.journal_query_tool",
	"DiagnosticsTool": "tools.diagnostics_tool",
	"GitTool": "tools.git_tool",
	"NotebookEditTool": "tools.notebook_edit_tool",
	"WebFetchTool": "tools.web_fetch_tool",
	"WebSearchTool": "tools.web_search_tool",
	"XeyoUITool": "tools.xeyo_ui_tool",
	"JobKillTool": "tools.job_tools",
	"JobListTool": "tools.job_tools",
	"JobOutputTool": "tools.job_tools",
}


def __getattr__(name: str):
	"""惰性解析被移除的工具类 import;其余缺失属性正常抛 AttributeError。"""
	module_name = _LAZY_TOOL_IMPORTS.get(name)
	if module_name is None:
		raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
	import importlib

	value = getattr(importlib.import_module(module_name), name)
	globals()[name] = value  # 首次解析后缓存,热路径零开销
	return value


ToolFactory = Callable[[str], Tool]

# 再导出，供 scheduler / 旧 import 路径使用
__all__ = [
	"ENABLED_TOOL_ENTRIES",
	"ENABLED_TOOLS",
	"DEFAULT_TOOLS",
	"TOOL_FACTORY_BY_NAME",
	"SUBSET_TOOL_WHITELIST",
	"SUBSET_TOOL_BASELINE",
	"FORBIDDEN_SUB_TOOLS",
	"build_default_registry",
	"build_subagent_registry",
	"shared_read_state",
	"inject_write_store",
	"inject_subagent_runtime",
	"default_tool_names",
	"tools_system_hint",
	"factory_for",
]




def _get_time(_cwd: str) -> Tool:
	from tools.get_time import GetTimeTool

	return GetTimeTool()


def _offload_read(_cwd: str) -> Tool:
	from tools.offload_read_tool import OffloadReadTool

	return OffloadReadTool()


def _glob(cwd: str) -> Tool:
	from tools.glob_tool.glob_tool import GlobTool

	return GlobTool(cwd=cwd)


def _agent(cwd: str) -> Tool:
	from tools.agent_tool import AgentTool

	return AgentTool(cwd=cwd)


def _journal_query(cwd: str) -> Tool:
	from tools.journal_query_tool import JournalQueryTool

	return JournalQueryTool(cwd=cwd)


def _bash(cwd: str) -> Tool:
	from tools.bash_tool.bash_tool import BashTool

	return BashTool(cwd=cwd)


def _file_read(cwd: str) -> Tool:
	from tools.file_read_tool.file_read_tool import FileReadTool

	return FileReadTool(cwd=cwd)


def _file_edit(cwd: str) -> Tool:
	from tools.file_edit_tool.file_edit_tool import FileEditTool

	return FileEditTool(cwd=cwd)


def _file_write(cwd: str) -> Tool:
	from tools.file_write_tool.file_write_tool import FileWriteTool

	return FileWriteTool(cwd=cwd)


def _grep(cwd: str) -> Tool:
	from tools.grep_tool.grep_tool import GrepTool

	return GrepTool(cwd=cwd)


def _todo_write(_cwd: str) -> Tool:
	from tools.todo_write_tool.todo_write_tool import TodoWriteTool

	return TodoWriteTool()


def _memory(cwd: str) -> Tool:
	from tools.memory_tool import MemoryTool

	return MemoryTool(cwd=cwd)


def _ask_user(_cwd: str) -> Tool:
	from tools.ask_user_question_tool import AskUserQuestionTool

	return AskUserQuestionTool()


def _screenshot(_cwd: str) -> Tool:
	from tools.screenshot_tool import ScreenshotTool

	return ScreenshotTool()


def _send_to_wechat(cwd: str) -> Tool:
	from tools.send_to_wechat_tool import SendToWeChatTool

	return SendToWeChatTool(cwd=cwd)


def _skill(cwd: str) -> Tool:
	from tools.skill_tool import SkillTool

	return SkillTool(cwd=cwd)


def _diagnostics(cwd: str) -> Tool:
	from tools.diagnostics_tool import DiagnosticsTool

	return DiagnosticsTool(cwd=cwd)


def _git(cwd: str) -> Tool:
	from tools.git_tool import GitTool

	return GitTool(cwd=cwd)


def _notebook_edit(cwd: str) -> Tool:
	from tools.notebook_edit_tool import NotebookEditTool

	return NotebookEditTool(cwd=cwd)


def _web_fetch(_cwd: str) -> Tool:
	from tools.web_fetch_tool import WebFetchTool

	return WebFetchTool()


def _web_search(_cwd: str) -> Tool:
	from tools.web_search_tool import WebSearchTool

	return WebSearchTool()


def _xeyo_ui(cwd: str) -> Tool:
	from tools.xeyo_ui_tool import XeyoUITool

	return XeyoUITool(cwd=cwd)


def _job_output(_cwd: str) -> Tool:
	from tools.job_tools import JobOutputTool

	return JobOutputTool()


def _job_list(_cwd: str) -> Tool:
	from tools.job_tools import JobListTool

	return JobListTool()


def _job_kill(_cwd: str) -> Tool:
	from tools.job_tools import JobKillTool

	return JobKillTool()


# ==============================================================================
# 真实可用工具矩阵 (ENABLED_TOOL_ENTRIES)
# ==============================================================================
# 【契约】名须与 tools.meta.TOOL_META 且 tool.name 一致；副作用工具须有边界测。
ENABLED_TOOL_ENTRIES: Sequence[tuple[str, ToolFactory]] = (
	("getTime", _get_time),
	("offload_read", _offload_read),
	("Glob", _glob),
	("Grep", _grep),
	("Read", _file_read),
	("Write", _file_write),
	("Edit", _file_edit),
	("Bash", _bash),
	("TodoWrite", _todo_write),
	("job_output", _job_output),
	("job_list", _job_list),
	("job_kill", _job_kill),
	("Screenshot", _screenshot),
	("SendToWeChat", _send_to_wechat),
	("Memory", _memory),
	("AskUserQuestion", _ask_user),
	("JournalQuery", _journal_query),
	("Skill", _skill),
	("Agent", _agent),
	("Diagnostics", _diagnostics),
	("Git", _git),
	("NotebookEdit", _notebook_edit),
	("WebFetch", _web_fetch),
	("WebSearch", _web_search),
	("XeyoUI", _xeyo_ui),
)

TOOL_FACTORY_BY_NAME: dict[str, ToolFactory] = {
	name: factory for name, factory in ENABLED_TOOL_ENTRIES
}

# 兼容旧调用：仅工厂序列
ENABLED_TOOLS: Sequence[ToolFactory] = tuple(
	factory for _, factory in ENABLED_TOOL_ENTRIES
)
DEFAULT_TOOLS: Sequence[ToolFactory] = ENABLED_TOOLS

# 兼容旧私有名
_FORBIDDEN_SUB_TOOLS = FORBIDDEN_SUB_TOOLS


def factory_for(name: str) -> ToolFactory | None:
	"""O(1) 按名取工厂；未启用则 None。"""
	return TOOL_FACTORY_BY_NAME.get((name or "").strip())


def _register_factories(
	reg: ToolRegistry,
	entries: Sequence[tuple[str, ToolFactory]],
	*,
	cwd: str,
	read_state: ReadFileState,
) -> None:
	"""注册工具，并向 ReadStateAware 注入共享 ReadFileState。"""
	for declared, factory in entries:
		tool = factory(cwd)
		if tool.name != declared:
			raise RuntimeError(
				f"tool factory name mismatch: catalog={declared!r} "
				f"instance={tool.name!r}"
			)
		meta = meta_for(declared)
		if meta is None or not meta.enabled:
			raise RuntimeError(f"enabled tool missing from tools.meta: {declared}")
		if declared in READ_STATE_TOOL_NAMES:
			if not isinstance(tool, ReadStateAware) and not hasattr(
				tool, "set_read_file_state"
			):
				raise RuntimeError(
					f"{declared} is marked needs_read_state but has no "
					"set_read_file_state"
				)
			tool.set_read_file_state(read_state)  # type: ignore[attr-defined]
		else:
			setter = getattr(tool, "set_read_file_state", None)
			if callable(setter):
				setter(read_state)
		# 实例 flags 与 meta 对齐（注册时失败，避免静默漂移）
		if tool_flag(tool, "is_read_only", default=False) != meta.read_only:
			raise RuntimeError(
				f"{declared}: is_read_only()={tool_flag(tool, 'is_read_only')} "
				f"!= meta.read_only={meta.read_only}"
			)
		if (
			tool_flag(tool, "is_concurrency_safe", default=False)
			!= meta.concurrency_safe
		):
			raise RuntimeError(
				f"{declared}: is_concurrency_safe() mismatch vs tools.meta"
			)
		reg.register(tool)


def build_default_registry(*, cwd: str = ".") -> ToolRegistry:
	work = os.path.abspath(os.path.expanduser(cwd or "."))
	reg = ToolRegistry(cwd=work)
	entries = ENABLED_TOOL_ENTRIES
	if os.environ.get("XEYO_BENCH_MINIMAL") == "1":
		# 基准评测最小档案：排除 Skill/Agent（skills、slash、subagent/live_agents 面）
		# 与文件工具（Read/Write/Edit/Glob/Grep）及 Memory/AskUserQuestion/Screenshot/
		# SendToWeChat/XeyoUI/JournalQuery——基准任务采用 bash-only 工作方式（同尺对比）；
		# 容器路由下文件 I/O 走 bash。预算/abort/记忆开关不受影响。
		excluded = {
			"Skill", "Agent", "Memory", "AskUserQuestion",
			"Read", "Write", "Edit", "Glob", "Grep", "NotebookEdit",
			"Screenshot", "SendToWeChat", "XeyoUI", "JournalQuery",
			"Diagnostics", "Git", "WebFetch", "WebSearch",
		}
		entries = [e for e in entries if e[0] not in excluded]
	_register_factories(
		reg, entries, cwd=work, read_state=ReadFileState()
	)
	return reg


def inject_write_store(reg: ToolRegistry, store: Any, agent_id: str) -> None:
	"""注入 WriteStore / agent_id；meta.needs_write_store 缺方法则硬失败。"""
	missing: list[str] = []
	for name in WRITE_STORE_TOOL_NAMES:
		tool = reg.get(name)
		if tool is None:
			continue
		if isinstance(tool, WriteStoreAware) or hasattr(tool, "set_write_store"):
			tool.set_write_store(store)  # type: ignore[attr-defined]
		else:
			missing.append(name)
		if isinstance(tool, AgentIdAware) or hasattr(tool, "set_agent_id"):
			tool.set_agent_id(agent_id)  # type: ignore[attr-defined]
	if missing:
		raise RuntimeError(
			"write-store tools missing set_write_store: " + ", ".join(missing)
		)
	# 其余仅需 agent_id 的工具（Memory / TodoWrite）
	for tool in list(getattr(reg, "_tools", {}).values()):
		if tool.name in WRITE_STORE_TOOL_NAMES:
			continue
		if isinstance(tool, AgentIdAware) or hasattr(tool, "set_agent_id"):
			tool.set_agent_id(agent_id)  # type: ignore[attr-defined]


def inject_subagent_runtime(reg: ToolRegistry, provider: Any) -> None:
	"""给 AgentTool 注入子 agent 运行时；缺方法则硬失败。"""
	for name in RUNTIME_PROVIDER_TOOL_NAMES:
		tool = reg.get(name)
		if tool is None:
			continue
		if isinstance(tool, RuntimeProviderAware) or hasattr(
			tool, "set_runtime_provider"
		):
			tool.set_runtime_provider(provider)  # type: ignore[attr-defined]
			return
		raise RuntimeError(f"{name} missing set_runtime_provider")


def apply_read_vision(reg: ToolRegistry, *, enabled: bool) -> None:
	"""按厂商/模型能力开关 Read 的图片/PDF；须在会话 registry 构建时调用一次。"""
	tool = reg.get("Read")
	setter = getattr(tool, "set_vision_enabled", None) if tool is not None else None
	if callable(setter):
		setter(bool(enabled))
		# schemas 缓存含 description，能力变化后必须失效
		reg._schemas_cache = None  # type: ignore[attr-defined]


def shared_read_state(reg: ToolRegistry) -> ReadFileState:
	"""取 registry 内注入的共享 ReadFileState（父子 agent 须同册）。

	子 agent 若持有独立实例，它写的文件在主会话 read_state 里时间戳过期，
	主会话随后 Edit 同一文件会误报 "File has been modified since read"。
	"""
	for tool in list(getattr(reg, "_tools", {}).values()):
		state = getattr(tool, "_read_state", None)
		if isinstance(state, ReadFileState):
			return state
	return ReadFileState()


def build_subagent_registry(
	*,
	cwd: str = ".",
	tool_names: Sequence[str] | None = None,
	read_state: ReadFileState | None = None,
	write_store: Any | None = None,
	agent_id: str = "main",
) -> ToolRegistry:
	"""构建子 agent 受限注册表：按名 O(1) 取工厂，禁发 FORBIDDEN_SUB_TOOLS。"""
	work = os.path.abspath(os.path.expanduser(cwd or "."))
	reg = ToolRegistry(cwd=work)
	from memory.agent_scope import filter_tool_names_for_scope

	names_in = list(tool_names) if tool_names else []
	allowed = set(filter_tool_names_for_scope(names_in, agent_id)) if names_in else set()
	shared = read_state or ReadFileState()
	entries: list[tuple[str, ToolFactory]] = []
	for name in sorted(allowed) if allowed else [n for n, _ in ENABLED_TOOL_ENTRIES]:
		if name in FORBIDDEN_SUB_TOOLS:
			continue
		factory = TOOL_FACTORY_BY_NAME.get(name)
		if factory is None:
			continue
		entries.append((name, factory))
	_register_factories(reg, entries, cwd=work, read_state=shared)
	if write_store is not None:
		inject_write_store(reg, write_store, agent_id)
	else:
		for tool in list(getattr(reg, "_tools", {}).values()):
			if isinstance(tool, AgentIdAware) or hasattr(tool, "set_agent_id"):
				tool.set_agent_id(agent_id)  # type: ignore[attr-defined]
	return reg


def default_tool_names(*, cwd: str = ".") -> list[str]:
	_ = cwd
	return [name for name, _ in ENABLED_TOOL_ENTRIES]


def tools_system_hint(*, cwd: str = ".") -> str:
	"""兼容旧调用：恒空串（TOOL_POLICY 已随理念裁决 A1 从左段删除）。"""
	_ = cwd
	return ""


# 启动自检：ENABLED 名集 == meta.enabled
_assert_names = {name for name, _ in ENABLED_TOOL_ENTRIES}
if _assert_names != ENABLED_META_NAMES:
	_missing = ENABLED_META_NAMES - _assert_names
	_extra = _assert_names - ENABLED_META_NAMES
	raise RuntimeError(
		f"ENABLED_TOOL_ENTRIES drift vs tools.meta: "
		f"missing_factories={sorted(_missing)} extra={sorted(_extra)}"
	)
