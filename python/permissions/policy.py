"""统一权限规则评估。

把历史 gate.py 硬编码判断收敛为规则评估，返回 allow/ask/deny 三态：
- ask 表示需要挂起等待用户确认（不再降级为 deny）。
- deny 表示确定性拒绝；allow 表示显式规则命中。
- 未知工具默认 ask，不再宽松透传。

已接入 ToolRegistry.run；``permissions.gate.can_use_tool`` 为兼容薄包装
（ASK→DENY 的二元 API，供旧测试 / 外部调用）。
"""

from __future__ import annotations

import os
import re
import contextvars
from dataclasses import dataclass

from permissions.bash_policy import (
	bash_deny_extra,
	bash_deny_reason,
	bash_readonly_allow,
	bash_rule_ask_deny,
	bash_secret_read_reason,
	is_remote_session,
)
from permissions.filesystem import (
	PermissionDecision,
	check_read_permission_for_path,
	default_permission_context,
	expand_to_abs,
	is_dangerous_path,
	is_secret_path,
	path_in_allowed_working_path,
	protected_metadata_reason,
)
from permissions.workspace_policy import (
	is_policy_file,
	load_workspace_policy,
	resolve_allowed_roots,
)
from permissions.write_scope import write_scope_deny_reason
from tools.meta import (
	ALWAYS_ALLOW_TOOLS as _ALWAYS_ALLOW,
	OUTBOUND_ASK_TOOLS as _OUTBOUND_ASK_TOOLS,
	UI_ASK_TOOLS as _UI_ASK_TOOLS,
	READ_PATH_TOOLS as _READ_PATH_TOOLS,
	READONLY_ALLOW,
	READONLY_ASK_ALLOW,
	WRITE_PATH_TOOLS as _WRITE_PATH_TOOLS,
)


@dataclass(frozen=True)
class PolicyDecision:
	"""规则评估结果。ask/deny 附带可读 prompt，供弹窗展示。"""

	decision: PermissionDecision
	reason: str
	path: str | None = None
	prompt: str | None = None
	matched_rule: str | None = None
	#: 三选 ASK：("deny", "remind", "allow")；空则普通二元确认。
	choices: tuple[str, ...] = ()
	peer_summary: str = ""
	#: P0b 指纹 v2：网关调用解析出的目标注册名（原生 mcp__ 工具留空，
	#: grant_fingerprint 自行从 tool_name 识别）。
	mcp_target: str = ""

	@property
	def allowed(self) -> bool:
		return self.decision == PermissionDecision.ALLOW


_PERMISSION_MODES = ("always", "risk", "never", "allow")
_AGENT_MODES = ("agent", "plan", "ask")
_OUTPUT_MODES = ("lite", "full", "ultra")
# never / allow：工作区内常规写免确认（密钥/策略/危险路径仍硬拦）。
_AUTO_WRITE_MODES = frozenset({"never", "allow"})
_permission_mode_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
	"xeyo_permission_mode", default=None
)
_agent_mode_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
	"xeyo_agent_mode", default="agent"
)
_output_compact_ctx: contextvars.ContextVar[bool] = contextvars.ContextVar(
	"xeyo_output_compact", default=False
)
# 42 号：job 完成通知 T_now 补投摘要（人类下一轮开工时由 chat.py 注入；
# 「一次性待领信息」——_trim 之后强挂的破例，见 42 号设计 §6.4/开放 #2）。
_pending_jobs_digest_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
	"xeyo_pending_jobs_digest", default=""
)
_output_mode_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
	"xeyo_output_mode", default=None
)
_code_compact_ctx: contextvars.ContextVar[bool] = contextvars.ContextVar(
	"xeyo_code_compact", default=False
)
_code_mode_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
	"xeyo_code_mode", default=None
)
# 侧聊（side chat）：只读工具白名单 + 不注入 workspace 内容；
# 与 agent_mode 无关的请求级开关，由 chat.py 在请求入口 set、finally 复位。
_side_mode_ctx: contextvars.ContextVar[bool] = contextvars.ContextVar(
	"xeyo_side_mode", default=False
)
# T14：子代理（侧链）运行标记——T_now 净化清单据此跳过易变块
# （peer presence / 文件冲突 / 浏览器预览 / repeat guard 等）。
_subagent_ctx: contextvars.ContextVar[bool] = contextvars.ContextVar(
	"xeyo_in_subagent", default=False
)
# T35：入口面标识（gui / cli / tui / remote，见 slash.SURFACES）。
# 高阶工具（XeyoUI）据此诚实降级：非 GUI 面不再假成功。缺省 gui（主桌面面）。
_surface_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
	"xeyo_surface", default="gui"
)

# ExitPlanMode 非 ENABLED 工具，模式特例仍留在 policy。
PLAN_ONLY_ALLOW = frozenset({"ExitPlanMode"})
_MODE_TOOL_ALLOW = {
	"agent": None,
	"ask": READONLY_ALLOW | READONLY_ASK_ALLOW,
	"plan": READONLY_ALLOW | READONLY_ASK_ALLOW | PLAN_ONLY_ALLOW,
}


def set_side_mode(enabled: bool | None) -> None:
	"""按请求开关侧聊只读模式；None 视为关。"""
	_side_mode_ctx.set(bool(enabled))


def side_mode() -> bool:
	"""当前回合是否为侧聊只读模式。"""
	return bool(_side_mode_ctx.get())


# 入口面标识（与 slash.SURFACES 对齐）：gui / cli / tui / remote。
_NON_GUI_SURFACES = frozenset({"cli", "tui", "remote"})


def set_surface(surface: str | None) -> None:
	"""设置当前入口面；None/空按 gui 处理。"""
	_surface_ctx.set((surface or "gui").strip() or "gui")


def current_surface() -> str:
	"""当前入口面；缺省 gui。"""
	return _surface_ctx.get() or "gui"


def is_gui_surface() -> bool:
	"""当前是否为 GUI 面（桌面/浏览器）。"""
	return current_surface() not in _NON_GUI_SURFACES



def set_in_subagent(enabled: bool | None) -> None:
	"""T14：标记当前 async 上下文是否为子代理（侧链）运行；None 视为关。"""
	_subagent_ctx.set(bool(enabled))


def in_subagent() -> bool:
	"""当前是否处于子代理（侧链）上下文——T_now 易变块按净化清单跳过。"""
	return bool(_subagent_ctx.get())


def set_permission_mode(mode: str | None) -> None:
	"""按请求覆盖审批模式（前端弹窗/请求传入）；None 表示回退 env。"""
	_permission_mode_ctx.set(mode)




def _default_permission_mode() -> str:
	"""config 默认（env → preset → risk），不含 store / body。"""
	mode = os.environ.get("XEYO_PERMISSION_MODE", "").strip().lower()
	if mode == "allow":
		return "never"
	if mode in _PERMISSION_MODES:
		return mode
	# T10 preset：full bundle —— 请求/环境都没显式给 mode 时放宽写确认。
	if session_permission_profile() == "full":
		return "never"
	return "risk"


def _runtime_mode_effective() -> str | None:
	"""读 RuntimeModeStore 的轮内实效模式（无活值/无会话 → None）。"""
	try:
		from permissions.runtime_mode import get_runtime_mode_store

		sid = _session_id()
		if not sid:
			return None
		return get_runtime_mode_store().effective(sid)
	except Exception:
		return None


def permission_mode() -> str:
	"""返回当前编辑审批模式：always / risk / never，默认 risk。

	优先级：**RuntimeModeStore 活值 > 请求 body 显式 > config 默认**。
	- store 活值：GUI 轮中切换写的"你刚点的"，覆盖本轮 body 快照（立即生效）。
	- body 显式：脚本/CLI 逐请求钉死（store 为空时即种子载波，兼容旧语义）。
	- config 默认：env(`XEYO_PERMISSION_MODE`) → T10 preset → risk。
	``never`` 与 ``allow`` 同义：工作区安全写自动放行（历史 UI 名 never）。
	"""
	eff = _runtime_mode_effective()
	if eff is not None:
		return eff
	mode = _permission_mode_ctx.get()
	if mode in _PERMISSION_MODES:
		return "never" if mode == "allow" else mode
	return _default_permission_mode()


def is_max_permission_mode() -> bool:
	"""当前是否处于最高（免确认）审批档：never/allow。

	用于「工作区外」这一类**权限级**边界的放宽——max 档下允许代理访问
	工作区外（如跨目录找日志），但仍受密钥/策略文件/受保护元数据/危险路径
	等**硬边界**约束（它们在 policy 更早的硬拦分支裁决，不在此放宽）。
	"""
	return permission_mode() in _AUTO_WRITE_MODES


def begin_permission_turn(session_id: str) -> None:
	"""turn 边界：拍定本轮审批基线并复位广播位（下次模型调用发全量快照）。

	由 query_loop 在每轮（会话开始/每次 resume 的首个模型调用前）调用。
	基线 = 活值 or body/config 默认；轮内 permission_mode 取「基线与活值较严」，
	故收紧即时、放宽延后到下一 turn。无活值时基线仅作占位（effective 返回 None，
	permission_mode 回落 body/config 默认）。
	"""
	try:
		from permissions.runtime_mode import get_runtime_mode_store

		mode = _permission_mode_ctx.get()
		default = (
			("never" if mode == "allow" else mode)
			if mode in _PERMISSION_MODES
			else _default_permission_mode()
		)
		get_runtime_mode_store().begin_turn(session_id, default)
	except Exception:
		# 若 store 不可用则降级为旧行为（纯 body/config 判定），不阻塞回合。
		pass


def normalize_agent_mode(value: object) -> str:
	"""归一化会话 Agent 模式；未知值回退 agent。"""
	mode = str(value or "agent").strip().lower()
	return mode if mode in _AGENT_MODES else "agent"


def set_agent_mode(mode: str | None) -> None:
	"""按请求覆盖会话 Agent 模式；None/未知回退 agent。"""
	_agent_mode_ctx.set(normalize_agent_mode(mode))


def agent_mode() -> str:
	"""返回当前会话的 Agent 模式。"""
	return normalize_agent_mode(_agent_mode_ctx.get())


def session_permission_profile() -> str:
	"""T10：当前会话的权限 preset（readonly / workspace-write / full）。

	来自 WorkspaceContext.permission_profile（会话创建时由 SessionPool pin）；
	无上下文回退 ""（视为 workspace-write 现状行为）。
	smoke-test #6：用户显式切换的运行时 preset（/v1/sessions/{sid}/runtime-preset）
	优先于 pin —— 实时变更只影响后续判定，未切换的会话沿用 pin。
	"""
	try:
		from engine.workspace_context import get_workspace_context

		ctx = get_workspace_context()
		sid = (ctx.session_id if ctx else "") or ""
		if sid:
			from permissions.runtime_preset import get_runtime_preset_store

			live = get_runtime_preset_store().live(sid)
			if live:
				return live
		return (ctx.permission_profile if ctx else "") or ""
	except Exception:
		return ""


def set_output_compact(enabled: bool | None) -> None:
	"""按请求开关输出精简（设置里的「输出精简」）；None 视为关。"""
	_output_compact_ctx.set(bool(enabled))


def output_compact_enabled() -> bool:
	"""本轮是否注入输出精简块。"""
	return bool(_output_compact_ctx.get())


def normalize_output_mode(value: object) -> str:
	"""归一化输出精简模式；未知值回退 lite。"""
	mode = str(value or "lite").strip().lower()
	return mode if mode in _OUTPUT_MODES else "lite"


def set_output_mode(mode: str | None) -> None:
	"""按请求覆盖输出精简模式；None/未知回退 lite。"""
	_output_mode_ctx.set(normalize_output_mode(mode))


def output_mode() -> str:
	"""返回当前输出精简模式：lite / full / ultra。"""
	mode = _output_mode_ctx.get()
	return normalize_output_mode(mode) if mode else "lite"


def set_pending_jobs_digest(digest: str) -> None:
	"""42 号：人类请求入口 set 本轮待领 job 完成通知摘要；空串 = 无待领。"""
	_pending_jobs_digest_ctx.set(digest or "")


def pending_jobs_digest() -> str:
	"""返回本轮待领 job 完成通知摘要（pre_llm_inject 强挂块消费）。"""
	return _pending_jobs_digest_ctx.get() or ""


def set_code_compact(enabled: bool | None) -> None:
	"""按请求开关写代码精简（设置里的「写代码精简」）；None 视为关。"""
	_code_compact_ctx.set(bool(enabled))


def code_compact_enabled() -> bool:
	"""本轮是否注入写代码精简块。"""
	return bool(_code_compact_ctx.get())


def normalize_code_mode(value: object) -> str:
	"""归一化写代码精简模式；未知值回退 lite。"""
	return normalize_output_mode(value)


def set_code_mode(mode: str | None) -> None:
	"""按请求覆盖写代码精简模式；None/未知回退 lite。"""
	_code_mode_ctx.set(normalize_code_mode(mode))


def code_mode() -> str:
	"""返回当前写代码精简模式：lite / full / ultra。"""
	mode = _code_mode_ctx.get()
	return normalize_code_mode(mode) if mode else "lite"


# 上一轮思考回顾（T_now 注入）开关：会话/请求显式设置 > 环境变量兜底。
_reasoning_tail_ctx: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
	"xeyo_reasoning_tail", default=None
)


def set_reasoning_tail_enabled(enabled: bool | None) -> None:
	"""按会话/请求设置「上一轮思考回顾」；None = 清除显式值（回落进程默认）。"""
	_reasoning_tail_ctx.set(bool(enabled) if enabled is not None else None)


def _reasoning_tail_env_default() -> bool:
	"""进程级默认：XEYO_REASONING_TAIL=1/true/on 开启。"""
	return os.environ.get("XEYO_REASONING_TAIL", "").strip().lower() in (
		"1",
		"true",
		"on",
	)


def reasoning_tail_enabled() -> bool:
	"""上一轮思考回顾 T_now 注入开关（默认**关**）。

	优先级：会话/请求显式设置（``set_reasoning_tail_enabled``，GUI 设置
	经 T31 模式链路）> 环境变量 ``XEYO_REASONING_TAIL``（进程级默认，
	覆盖无 GUI/未接线入口的脚本与评测路径）。默认移除：强模型收益≈0、
	弱模型存在"旧结论指令化"的锚定/续写压力；仅在显式开启时恢复。
	"""
	v = _reasoning_tail_ctx.get()
	if v is not None:
		return v
	return _reasoning_tail_env_default()


_browser_preview_url_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
	"xeyo_browser_preview_url", default=None
)


def _normalize_browser_preview_url(value: object) -> str | None:
	"""归一化 GUI 预览浏览器 URL；非法 scheme 返回 None。"""
	if value is None:
		return None
	url = str(value).strip()
	if not url or len(url) > 2048:
		return None
	lower = url.lower()
	if lower.startswith(("javascript:", "data:", "file:", "vbscript:")):
		return None
	if "://" in lower:
		if not (lower.startswith("http://") or lower.startswith("https://")):
			return None
	return url


def set_browser_preview_url(url: str | None) -> None:
	"""按请求设置用户当前预览页 URL；None/非法视为无。"""
	_browser_preview_url_ctx.set(_normalize_browser_preview_url(url))


def browser_preview_url() -> str | None:
	"""本轮用户打开的预览浏览器 URL（http/https）。"""
	return _normalize_browser_preview_url(_browser_preview_url_ctx.get())


def tool_allowed_in_mode(name: str, *, tool: object | None = None) -> bool:
	"""当前 Agent 模式是否允许该工具出现在 schema/执行阶段。

	侧聊（side）模式优先：只允许真只读工具（``is_read_only``）。
	优先读工具实例的 ``is_read_only()``（与实现同源）；无实例时回退名字表。
	AskUserQuestion / ExitPlanMode 为模式特例，不依赖只读标记。
	"""
	n = (name or "").strip()
	if side_mode():
		if tool is not None:
			from tools.base_tool import tool_flag

			return tool_flag(tool, "is_read_only", default=False)
		return n in READONLY_ALLOW
	mode = agent_mode()
	allowed = _MODE_TOOL_ALLOW.get(mode)
	if allowed is None:
		return True
	if n in READONLY_ASK_ALLOW:
		return True
	if mode == "plan" and n in PLAN_ONLY_ALLOW:
		return True
	if tool is not None:
		from tools.base_tool import tool_flag

		return tool_flag(tool, "is_read_only", default=False)
	return n in allowed




def readonly_gate(name: str, *, tool: object | None = None) -> str | None:
	"""只读模式 gate。返回拒绝原因；agent 模式始终放行。"""
	profile = session_permission_profile()
	if profile == "readonly":
		# T10 preset：readonly 会话只放只读白名单（等价侧聊只读语义）。
		if name in READONLY_ALLOW or name in READONLY_ASK_ALLOW:
			return None
		if tool is not None:
			from tools.base_tool import tool_flag

			if tool_flag(tool, "is_read_only", default=False):
				return None
		return "readonly_mode_deny"
	if not side_mode() and agent_mode() == "agent":
		return None
	if tool_allowed_in_mode(name, tool=tool):
		return None
	return "readonly_mode_deny"


def _pick_path(tool_input: dict | None, *keys: str) -> str | None:
	if not isinstance(tool_input, dict):
		return None
	for key in keys:
		val = tool_input.get(key)
		if isinstance(val, str) and val.strip():
			return val.strip()
	return None


def _prompt_for_read(name: str, path: str) -> str:
	return f"Read permission needed for {name} on {path}"


def _prompt_for_write(name: str, path: str) -> str:
	return f"Allow {name} to write to {path}?"


def _prompt_for_bash(command: str) -> str:
	from audit.redact import command_summary

	return f"Allow executing: {command_summary(command)}"


def _prompt_for_outbound(name: str, path: str | None = None) -> str:
	if name == "Screenshot":
		return (
			"Allow Screenshot? This captures the display and may send a copy "
			"to WeChat when remote is connected."
		)
	if name == "WebFetch":
		return f"Allow WebFetch of {path}?" if path else "Allow WebFetch of a URL?"
	if name == "WebSearch":
		return (
			f"Allow WebSearch for query: {path}?"
			if path
			else "Allow WebSearch?"
		)
	if path:
		return f"Allow SendToWeChat to deliver {path} to WeChat?"
	return "Allow SendToWeChat to deliver a file to WeChat?"


def _prompt_for_agent() -> str:
	return "Allow spawning a sub-agent for this task?"


_UI_PANELS = frozenset({"git", "terminal", "history", "map", "commits", "browser"})
_BROWSER_OPS = frozenset({"reload", "back", "fwd", "ext", "close"})


def _prompt_for_ui(action: str, *, detail: str = "") -> str:
	if action == "open_preview":
		return f"允许打开文件预览：{detail}？" if detail else "允许打开文件预览？"
	if action == "open_panel":
		return f"允许打开工作区面板：{detail}？" if detail else "允许打开工作区面板？"
	if action == "browser":
		return f"允许浏览器预览：{detail}？" if detail else "允许打开浏览器预览？"
	if action == "show_tool_flow":
		if detail == "show":
			return "允许展示本轮工具流程地图？"
		if detail == "hide":
			return "允许关闭工具流程地图？"
		return "允许切换工具流程地图？"
	if action == "send_to_session":
		return detail or "允许向另一对话发送消息？"
	return f"允许执行 XeyoUI（{action}）？"


def _evaluate_ui_ask(
	tool_input: dict | None,
	*,
	cwd: str,
	roots: list[str],
) -> PolicyDecision:
	"""XeyoUI：按 action 分流 — list 放行，其余 ASK；非法参数 DENY。"""
	raw = tool_input if isinstance(tool_input, dict) else {}
	action = str(raw.get("action") or "").strip()
	if not action:
		return PolicyDecision(
			decision=PermissionDecision.DENY,
			reason="ui_missing_action",
			matched_rule="ui_missing_action",
			prompt="XeyoUI requires action",
		)
	if action == "list_sessions":
		return PolicyDecision(
			decision=PermissionDecision.ALLOW,
			reason="ui_list_allow",
			matched_rule="ui_list_allow",
		)
	if action == "open_preview":
		path_raw = _pick_path(raw, "path", "file_path", "filePath")
		if not path_raw:
			return PolicyDecision(
				decision=PermissionDecision.DENY,
				reason="ui_missing_path",
				matched_rule="ui_missing_path",
				prompt="open_preview requires path",
			)
		path = expand_to_abs(path_raw, cwd=cwd)
		if not path_in_allowed_working_path(
			path, cwd=cwd, allowed_working_paths=roots
		):
			return PolicyDecision(
				decision=PermissionDecision.DENY,
				reason="path_outside_working_directory",
				matched_rule="ui_preview_outside_deny",
				path=path,
			)
		return PolicyDecision(
			decision=PermissionDecision.ASK,
			reason="needs_confirmation",
			matched_rule="ui_preview_ask",
			path=path,
			prompt=_prompt_for_ui("open_preview", detail=path),
		)
	if action == "open_panel":
		panel = str(raw.get("panel") or "").strip()
		if panel not in _UI_PANELS:
			return PolicyDecision(
				decision=PermissionDecision.DENY,
				reason="ui_invalid_panel",
				matched_rule="ui_invalid_panel",
				prompt=(
					"open_panel requires panel in "
					"git|terminal|history|map|commits|browser"
				),
			)
		return PolicyDecision(
			decision=PermissionDecision.ALLOW,
			reason="ui_panel_allow",
			matched_rule="ui_panel_allow",
			path=panel,
		)
	if action == "browser":
		url = str(raw.get("url") or "").strip()
		op = str(raw.get("op") or "").strip()
		if url:
			lower = url.lower()
			if len(url) > 2048:
				return PolicyDecision(
					decision=PermissionDecision.DENY,
					reason="ui_browser_bad_url",
					matched_rule="ui_browser_bad_url",
					prompt="browser url too long",
				)
			if "://" in lower:
				if not (
					lower.startswith("http://") or lower.startswith("https://")
				):
					return PolicyDecision(
						decision=PermissionDecision.DENY,
						reason="ui_browser_bad_url",
						matched_rule="ui_browser_bad_url",
						prompt="browser url must be http/https",
					)
			elif lower.startswith(
				("javascript:", "data:", "file:", "vbscript:")
			):
				return PolicyDecision(
					decision=PermissionDecision.DENY,
					reason="ui_browser_bad_url",
					matched_rule="ui_browser_bad_url",
					prompt="browser url must be http/https",
				)
			detail = url if len(url) <= 120 else url[:117] + "..."
			return PolicyDecision(
				decision=PermissionDecision.ASK,
				reason="needs_confirmation",
				matched_rule="ui_browser_ask",
				path=url,
				prompt=_prompt_for_ui("browser", detail=detail),
			)
		if op:
			if op not in _BROWSER_OPS:
				return PolicyDecision(
					decision=PermissionDecision.DENY,
					reason="ui_browser_bad_op",
					matched_rule="ui_browser_bad_op",
					prompt="browser op must be reload|back|fwd|ext|close",
				)
			# 浏览器纯导航（reload/back/fwd/ext/close）无副作用——免确认；
			# 打开/导航到新 URL 仍走下方 url 分支 ASK。
			return PolicyDecision(
				decision=PermissionDecision.ALLOW,
				reason="ui_browser_nav_allow",
				matched_rule="ui_browser_nav_allow",
				path=op,
			)
		return PolicyDecision(
			decision=PermissionDecision.ASK,
			reason="needs_confirmation",
			matched_rule="ui_browser_ask",
			path="open",
			prompt=_prompt_for_ui("browser"),
		)
	if action == "show_tool_flow":
		if "show" not in raw:
			return PolicyDecision(
				decision=PermissionDecision.DENY,
				reason="ui_missing_show",
				matched_rule="ui_missing_show",
				prompt="show_tool_flow requires show (boolean)",
			)
		show_raw = raw.get("show")
		if isinstance(show_raw, bool):
			show = show_raw
		elif isinstance(show_raw, (int, float)) and show_raw in (0, 1):
			show = bool(show_raw)
		elif isinstance(show_raw, str) and show_raw.strip().lower() in (
			"true",
			"false",
			"1",
			"0",
			"yes",
			"no",
			"on",
			"off",
		):
			show = show_raw.strip().lower() in ("true", "1", "yes", "on")
		else:
			return PolicyDecision(
				decision=PermissionDecision.DENY,
				reason="ui_invalid_show",
				matched_rule="ui_invalid_show",
				prompt="show_tool_flow requires show to be a boolean",
			)
		return PolicyDecision(
			decision=PermissionDecision.ALLOW,
			reason="ui_tool_flow_allow",
			matched_rule="ui_tool_flow_allow",
			path="show" if show else "hide",
		)
	if action == "send_to_session":
		target = str(raw.get("session_id") or "").strip()
		text = str(raw.get("text") or "").strip()
		if not target or not text:
			return PolicyDecision(
				decision=PermissionDecision.DENY,
				reason="ui_send_missing_fields",
				matched_rule="ui_send_missing_fields",
				prompt="send_to_session requires session_id and text",
			)
		if target.startswith("side-"):
			return PolicyDecision(
				decision=PermissionDecision.DENY,
				reason="ui_send_side_deny",
				matched_rule="ui_send_side_deny",
				prompt="Cannot send to side-chat sessions via XeyoUI",
			)
		current = _session_id()
		if current and target == current:
			return PolicyDecision(
				decision=PermissionDecision.DENY,
				reason="ui_send_self_deny",
				matched_rule="ui_send_self_deny",
				prompt="Cannot send_to_session to the current session",
			)
		try:
			from server.deps import _pool

			if _pool.is_busy(target):
				return PolicyDecision(
					decision=PermissionDecision.DENY,
					reason="ui_send_busy",
					matched_rule="ui_send_busy",
					prompt=f"Target session is busy: {target}",
				)
		except Exception:
			pass
		preview = text if len(text) <= 120 else text[:117] + "..."
		detail = f"向对话 {target} 发送：{preview}"
		return PolicyDecision(
			decision=PermissionDecision.ASK,
			reason="needs_confirmation",
			matched_rule="ui_send_ask",
			path=target,
			prompt=_prompt_for_ui("send_to_session", detail=detail),
		)
	return PolicyDecision(
		decision=PermissionDecision.DENY,
		reason="ui_unknown_action",
		matched_rule="ui_unknown_action",
		prompt=f"Unknown XeyoUI action: {action}",
	)


def _memdir_write_schema_ok(path: str, tool_input: dict | None) -> bool:
	"""Write 落 memdir 时校验 frontmatter；失败则拒绝。"""
	_ = path
	content = ""
	if isinstance(tool_input, dict):
		content = str(tool_input.get("content") or "")
	try:
		from memory.governance import parse_and_validate
		from memory.memdir import split_frontmatter

		fm, body = split_frontmatter(content)
		parse_and_validate(fm, body)
		return True
	except Exception:
		return False

# ── Bash 写文件检测（双重防护：除危险命令黑名单外，会写/改文件的命令也走写入审批）──
_BASH_REDIRECT_RX = re.compile(
	r"(?:>>?|2>>?|&>>?)\s*[\"']?([^\s;|&\"']+)[\"']?", re.I
)
_BASH_WRITE_CMD_RX = re.compile(
	r"\b(?:tee|dd)\b|\bsed\s+-i\b|\bperl\s+-pi\w*\b|"
	r"\b(?:cp|mv|touch|mkdir|rmdir|rm)\s+|\bcurl\s+(?:-[^\s]*o|-o)\b|"
	r"\bwget\s+(?:-O|--output-document)\b",
	re.I,
)
_BASH_INTERP_RX = re.compile(
	r"\b(?:python\w*|python3|py(?:\.exe)?|powershell|pwsh)\b", re.I
)
_BASH_WRITE_MARK_RX = re.compile(
	r"open\s*\([^)]*(?:[\"']w|[\"']a|[\"']r\+|[\"']wb|[\"']ab)|"
	r"\.write\s*\(|write_text|write_bytes|Set-Content|Add-Content|Out-File|"
	r"shutil\.(?:copy|move|rmtree|copyfile)|os\.(?:remove|rename|unlink|makedirs|rmdir|rmtree)",
	re.I,
)
_BASH_PY_OPEN_RX = re.compile(
	r"open\s*\(\s*(?:r|u|b)?[\"']([^\"')]+)[\"']", re.I,
)


def _bash_write_target(command: str) -> str | None:
	"""尽力提取 Bash 写命令的目标文件路径。"""
	m = _BASH_REDIRECT_RX.search(command)
	if m:
		return m.group(1).strip()
	m = _BASH_PY_OPEN_RX.search(command)
	if m and re.search(r"[\"']w|[\"']a|[\"']r\+|[\"']wb|[\"']ab", command, re.I):
		return m.group(1).strip()
	toks = re.split(r"\s+", command.strip())
	cands = [
		t for t in toks
		if t and t not in ("&&", "||", "|", ";", "&", ">", ">>", "2>", "2>>")
	]
	if cands:
		last = cands[-1].strip("\"'")
		if last and not last.startswith("-"):
			return last
	return None


def _bash_writes_file(command: str) -> bool:
	"""判定该 Bash 命令是否可能写/改文件（保守：仅明确的写操作判 True）。"""
	if not command:
		return False
	if _BASH_REDIRECT_RX.search(command):
		return True
	if _BASH_WRITE_CMD_RX.search(command):
		return True
	if _BASH_INTERP_RX.search(command) and _BASH_WRITE_MARK_RX.search(command):
		return True
	return False


def bash_write_target(command: str) -> str | None:
	"""尽力提取 Bash 写命令的目标文件路径。（公开 API，供工具层深度防御使用）"""
	return _bash_write_target(command)


def bash_writes_file(command: str) -> bool:
	"""判定该 Bash 命令是否可能写/改文件（公开 API，供工具层深度防御使用）。"""
	return _bash_writes_file(command)


def _session_id() -> str:
	try:
		from engine.workspace_context import get_workspace_context

		ctx = get_workspace_context()
		return (ctx.session_id if ctx is not None else "") or ""
	except Exception:
		return ""


def _effective_roots(cwd: str, allowed_paths: list[str] | None) -> list[str]:
	return resolve_allowed_roots(cwd, load_workspace_policy(cwd), extra=allowed_paths)


def _evaluate_bash(
	command: str,
	*,
	cwd: str,
	roots: list[str],
) -> PolicyDecision:
	"""Bash：黑名单 DENY → 密钥 DENY → 规则 DENY(T7) → 策略文件 DENY → 仓库/远程策略 → peer git → 只读白名单(规则驱动) → 规则 ASK(T7) → 写目标证明 → 默认 ASK。"""
	pol = load_workspace_policy(cwd)
	denied = bash_deny_reason(command) or bash_deny_extra(command, list(pol.deny_commands))
	if denied:
		return PolicyDecision(
			decision=PermissionDecision.DENY,
			reason=denied,
			matched_rule="bash_deny",
			prompt=_prompt_for_bash(command),
		)

	secret = bash_secret_read_reason(command)
	if secret:
		return PolicyDecision(
			decision=PermissionDecision.DENY,
			reason=secret,
			matched_rule="bash_secret_deny",
			prompt=_prompt_for_bash(command),
		)

	# T7 前缀规则：deny 收紧（先于 peer/policy-file 判定；多规则命中最严胜出）。
	rule_ask_deny = bash_rule_ask_deny(command, cwd=cwd)
	if rule_ask_deny == "deny":
		return PolicyDecision(
			decision=PermissionDecision.DENY,
			reason="bash_rule_deny",
			matched_rule="bash_rule_deny",
			prompt=_prompt_for_bash(command),
		)

	# 策略文件：Bash 不得改写（与 Write/Edit 同硬门禁）。
	if _bash_touches_policy_file(command, cwd=cwd):
		return PolicyDecision(
			decision=PermissionDecision.DENY,
			reason="policy_file_immutable",
			matched_rule="policy_file_deny",
			prompt="Cannot modify .xeyo-policy.json via Bash",
		)

	# 多会话 peer git / 热文件交叉：即使 auto-allow 也强制三选 ASK。
	peer = _peer_bash_conflict(command, cwd=cwd)
	if peer is not None:
		return peer

	remote = is_remote_session(_session_id())
	bash_mode = pol.bash
	# 无 OS jail 时不允许 bash:allow 自动放行一切；需显式 XEYO_BASH_UNSAFE_ALLOW=1
	# 或会话 preset=full（T10：full bundle 显式放宽确认频率，黑名单/硬保护仍生效）。
	if (
		bash_mode == "allow"
		and os.environ.get("XEYO_BASH_UNSAFE_ALLOW", "").strip() != "1"
		and session_permission_profile() != "full"
	):
		bash_mode = "default"
	if remote:
		# 远程会话更严：ask 或 deny，不允许 default/allow 自动放行。
		bash_mode = pol.remote_bash if pol.remote_bash in ("ask", "deny") else "ask"

	if bash_mode == "deny" or (remote and pol.remote_bash == "deny"):
		return PolicyDecision(
			decision=PermissionDecision.DENY,
			reason="policy_bash_deny",
			matched_rule="policy_bash_deny",
			prompt=_prompt_for_bash(command),
		)

	# Phase 2 工人 Bash 策略沙箱：仅只读白名单 ALLOW；其余 DENY；永不 ASK。
	# 远程工人无法弹窗确认 → 一律 DENY（与 Doc 34「远程不得静默放行」一致）。
	from permissions.write_scope import get_write_scope

	if get_write_scope() is not None:
		if remote:
			return PolicyDecision(
				decision=PermissionDecision.DENY,
				reason="worker_bash_remote_deny",
				matched_rule="worker_bash_deny",
				prompt=_prompt_for_bash(command),
			)
		if bash_readonly_allow(command, cwd=cwd):
			return PolicyDecision(
				decision=PermissionDecision.ALLOW,
				reason="worker_bash_readonly",
				matched_rule="worker_bash_readonly",
			)
		return PolicyDecision(
			decision=PermissionDecision.DENY,
			reason="worker_bash_deny",
			matched_rule="worker_bash_deny",
			prompt=_prompt_for_bash(command),
		)

	if bash_mode == "ask" or remote:
		# 远程 / 策略 ask：一律确认（黑名单已拦）——T26 出厂决策：含只读命令，
		# 默认全确认；白名单仅在 bash_mode=default / worker 只读沙箱生效。
		return PolicyDecision(
			decision=PermissionDecision.ASK,
			reason="needs_confirmation",
			matched_rule="bash_policy_ask" if not remote else "bash_remote_ask",
			prompt=_prompt_for_bash(command),
		)

	# T7 前缀规则：ask 收紧 default/allow 模式（含只读白名单与写区内放行）；
	# worker 分支在上面已经因 readonly 判定失败而 DENY（worker 永不 ASK）。
	if rule_ask_deny == "ask":
		return PolicyDecision(
			decision=PermissionDecision.ASK,
			reason="bash_rule_ask",
			matched_rule="bash_rule_ask",
			prompt=_prompt_for_bash(command),
		)

	# default：短只读白名单自动放行；写必须证明目标在工作区内，否则 DENY；其余 ASK。
	if bash_readonly_allow(command, cwd=cwd):
		return PolicyDecision(
			decision=PermissionDecision.ALLOW,
			reason="bash_readonly_allow",
			matched_rule="bash_readonly_allow",
		)

	if bash_mode == "allow":
		# 仅 XEYO_BASH_UNSAFE_ALLOW=1 时到达：黑名单 + 写区外/策略/密钥校验后 ALLOW。
		if _bash_writes_file(command):
			target = _bash_write_target(command)
			if not target:
				return PolicyDecision(
					decision=PermissionDecision.DENY,
					reason="bash_write_target_unproven",
					matched_rule="bash_write_unproven_deny",
					prompt=_prompt_for_bash(command),
				)
			path = expand_to_abs(target, cwd=cwd)
			write_block = _bash_write_path_block(path, cwd=cwd, roots=roots)
			if write_block is not None:
				return write_block
		return PolicyDecision(
			decision=PermissionDecision.ALLOW,
			reason="bash_policy_allow",
			matched_rule="bash_policy_allow",
		)

	# default：写必须证明目标在工作区内，否则 DENY；其余 ASK。
	if _bash_writes_file(command):
		target = _bash_write_target(command)
		if not target:
			return PolicyDecision(
				decision=PermissionDecision.DENY,
				reason="bash_write_target_unproven",
				matched_rule="bash_write_unproven_deny",
				prompt=_prompt_for_bash(command),
			)
		path = expand_to_abs(target, cwd=cwd)
		write_block = _bash_write_path_block(path, cwd=cwd, roots=roots)
		if write_block is not None:
			return write_block
		mode = permission_mode()
		if mode == "always" or is_dangerous_path(path, cwd=cwd):
			return PolicyDecision(
				decision=PermissionDecision.ASK,
				reason="needs_confirmation",
				matched_rule="bash_write_confirm_ask",
				path=path,
				prompt=_prompt_for_bash(command),
			)
		return PolicyDecision(
			decision=PermissionDecision.ALLOW,
			reason="bash_write_allow",
			matched_rule="bash_write_allow",
			path=path,
		)

	# max 档（never/allow=免确认）：既非只读白名单、又非已识别写文件的命令
	# （git push / npm install / pip install / 跑脚本 / curl 等）也自动放行。
	# 硬边界（黑名单/密钥/策略文件/远程/工人沙箱）已在上方裁决；本地非远程才可到此。
	if is_max_permission_mode():
		return PolicyDecision(
			decision=PermissionDecision.ALLOW,
			reason="bash_max_allow",
			matched_rule="bash_max_allow",
		)

	return PolicyDecision(
		decision=PermissionDecision.ASK,
		reason="needs_confirmation",
		matched_rule="bash_default_ask",
		prompt=_prompt_for_bash(command),
	)


def _peer_bash_conflict(command: str, *, cwd: str) -> PolicyDecision | None:
	"""多会话交叉：git 写或 Bash 写目标被他会话 busy 持有 → 三选 ASK。"""
	from engine.session_presence import (
		PEER_CHOICES,
		default_session_presence,
		format_peer_file_prompt,
	)

	sid = _session_id()
	if not sid:
		return None
	reg = default_session_presence()

	git_hit = reg.peer_git_conflict(cwd, sid, command)
	if git_hit is not None:
		summary, paths = git_hit
		prompt = (
			f"{summary}\n"
			f"命令: {command[:240]}\n"
			"请选择：硬拦 / 提醒双方后取消 / 继续执行原文。"
		)
		return PolicyDecision(
			decision=PermissionDecision.ASK,
			reason="peer_session_git",
			matched_rule="peer_session_git",
			path=paths[0] if paths else None,
			prompt=prompt,
			choices=PEER_CHOICES,
			peer_summary=summary,
		)

	if _bash_writes_file(command):
		target = _bash_write_target(command)
		if target:
			path = expand_to_abs(target, cwd=cwd)
			owner = reg.owner_of(cwd, path, exclude_session=sid)
			if owner is not None and owner.busy:
				prompt = format_peer_file_prompt(owner, path)
				return PolicyDecision(
					decision=PermissionDecision.ASK,
					reason="peer_file_busy",
					matched_rule="peer_file_busy",
					path=path,
					prompt=prompt,
					choices=PEER_CHOICES,
					peer_summary=prompt,
				)
	return None


def _peer_write_conflict(path: str, *, cwd: str) -> PolicyDecision | None:
	"""Write/Edit 热文件：他会话 busy 且拥有该路径 → 三选 ASK。"""
	from engine.session_presence import (
		PEER_CHOICES,
		default_session_presence,
		format_peer_file_prompt,
	)

	sid = _session_id()
	if not sid:
		return None
	owner = default_session_presence().owner_of(cwd, path, exclude_session=sid)
	if owner is None or not owner.busy:
		return None
	prompt = format_peer_file_prompt(owner, path)
	return PolicyDecision(
		decision=PermissionDecision.ASK,
		reason="peer_file_busy",
		matched_rule="peer_file_busy",
		path=path,
		prompt=prompt,
		choices=PEER_CHOICES,
		peer_summary=prompt,
	)


def _bash_touches_policy_file(command: str, *, cwd: str) -> bool:
	"""命令是否可能改写 .xeyo-policy.json。"""
	text = (command or "").replace("\\", "/")
	mentioned = ".xeyo-policy.json" in text.lower()
	if mentioned and (
		_bash_writes_file(command)
		or re.search(r"(>|>>|tee\b|set-content|out-file|sed\s+-i)", command or "", re.I)
	):
		return True
	if not _bash_writes_file(command):
		return False
	target = _bash_write_target(command)
	if not target:
		return False
	return is_policy_file(expand_to_abs(target, cwd=cwd), cwd=cwd)


def _bash_write_path_block(
	path: str, *, cwd: str, roots: list[str]
) -> PolicyDecision | None:
	"""写目标路径硬拦：策略文件 / 密钥 / 受保护元数据 / 工作区外。"""
	if is_policy_file(path, cwd=cwd):
		return PolicyDecision(
			decision=PermissionDecision.DENY,
			reason="policy_file_immutable",
			matched_rule="policy_file_deny",
			path=path,
			prompt="Cannot modify .xeyo-policy.json via Bash",
		)
	if is_secret_path(path, cwd=cwd):
		return PolicyDecision(
			decision=PermissionDecision.DENY,
			reason="secret_path",
			matched_rule="bash_secret_path_deny",
			path=path,
		)
	# T12：受保护元数据（.git/.xeyo/.agents）workspace 内默认只读。
	protected = protected_metadata_reason(path, cwd=cwd)
	if protected is not None:
		return PolicyDecision(
			decision=PermissionDecision.DENY,
			reason="protected_metadata",
			matched_rule="bash_protected_metadata_deny",
			path=path,
			prompt=protected,
		)
	if not path_in_allowed_working_path(
		path, cwd=cwd, allowed_working_paths=roots
	) and not is_max_permission_mode():
		return PolicyDecision(
			decision=PermissionDecision.DENY,
			reason="bash_write_outside_working_directory",
			matched_rule="bash_write_outside_deny",
			path=path,
		)
	return None


def _evaluate_mcp(
	name: str,
	tool_input: dict | None,
	*,
	cwd: str,
	tool: object | None,
) -> PolicyDecision:
	"""F3 MCP 动态工具权限：企业 deny → tool_policies（always_allow/outbound_ask）。

	优先级（最严胜出）：①企业 deny（``~/.xeyo/policy.json`` 一票否决）→ DENY；
	②``tool_policies``/``tools_policy``（实例携带）→ ALLOW/ASK；③未知兜底 → ASK。
	"""
	from extension.mcp_client import mcp_policy_decision

	raw_name = (name or "").strip()
	# 实例优先（server_id/raw_nam/policy 权威面）；无实例回退解析。
	server_id: str = ""
	raw_tool: str = ""
	policy: str = ""
	if tool is not None:
		server_id = str(getattr(tool, "server_id", "") or "")
		raw_tool = str(getattr(tool, "raw_name", "") or "")
		policy = str(getattr(tool, "policy", "") or "")
	if not server_id:
		parts = raw_name.split("__")
		server_id = parts[1] if len(parts) > 1 else ""
	if not raw_tool:
		parts = raw_name.split("__")
		raw_tool = parts[2] if len(parts) > 2 else ""
	if not policy:
		policy = "outbound_ask"

	# ① 企业 deny：最严胜出，下级不可覆盖。
	try:
		from extension import mcp_scopes as _scopes

		pol = _scopes.load_enterprise_policy()
		if _scopes.mcp_server_denied(server_id, policy=pol) or _scopes.mcp_tool_denied(
			server_id, raw_tool, policy=pol
		):
			return PolicyDecision(
				decision=PermissionDecision.DENY,
				reason="mcp_enterprise_deny",
				matched_rule="mcp_enterprise_deny",
				prompt=f"MCP tool {raw_name} is denied by enterprise policy",
			)
	except Exception:  # noqa: BLE001 — deny 读取失败不放松权限：仍走 tool_policies。
		pass

	# ①.5 F2.5 移除→DENY 门：会话内停用（server 关停/取消勾选）→ 拒绝。
	# 先于 grant 匹配（impl 返回即终局），用户停用不可被授权穿越。
	probe = getattr(tool, "enabled_probe", None) if tool is not None else None
	if callable(probe):
		try:
			if not probe():
				return PolicyDecision(
					decision=PermissionDecision.DENY,
					reason="mcp_disabled",
					matched_rule="mcp_disabled",
					prompt=f"MCP tool {raw_tool} 已被用户停用（原生目录下个会话重塑）",
				)
		except Exception:  # noqa: BLE001 — 探针故障不误伤
			pass

	return mcp_policy_decision(raw_name, policy)


def _evaluate_mcp_gateway(
	name: str,
	tool_input: dict | None,
	*,
	tool: object | None,
) -> PolicyDecision:
	"""F2 网关策略：元动作只读放行；call 身份解析后按目标工具三态。

	- 身份**只在已知工具集内解析**（网关 resolve_tool）→ 不可能从 args 伪装
	  出未知身份（fail-closed DENY）；
	- 企业 deny 一票否决按**目标** (server, raw) 判定；
	- ASK 决策携带 ``mcp_target``（目标注册名）→ grant 指纹 v2 / 挂起项 /
	  always-allow 落库全部以目标工具为身份（原生与网关路径同一身份）。
	"""
	from extension.mcp_client import mcp_policy_decision

	data = tool_input if isinstance(tool_input, dict) else {}
	action = str(data.get("action") or "").strip().lower()
	if action in ("list", "describe", "resources"):
		return PolicyDecision(
			decision=PermissionDecision.ALLOW,
			reason="mcp_gateway_meta",
			matched_rule="mcp_gateway_meta",
		)
	if action == "read_resource":
		# F6b：resources 网关化 —— read_path 级只读（按 uri 读 server 声明内容）。
		return PolicyDecision(
			decision=PermissionDecision.ALLOW,
			reason="mcp_gateway_read",
			matched_rule="mcp_gateway_read",
		)
	if action != "call":
		return PolicyDecision(
			decision=PermissionDecision.DENY,
			reason="mcp_gateway_bad_action",
			matched_rule="mcp_gateway_bad_action",
			prompt=f"Mcp gateway: unknown action {action!r}",
		)

	server = str(data.get("server") or "").strip()
	raw = str(data.get("tool") or "").strip()
	target = None
	resolve = getattr(tool, "resolve_target", None)
	if callable(resolve):
		target = resolve(server, raw)
	if target is None:
		return PolicyDecision(
			decision=PermissionDecision.DENY,
			reason="mcp_gateway_unknown_tool",
			matched_rule="mcp_gateway_unknown_tool",
			prompt=f"Mcp gateway: unknown tool {server}/{raw} (fail-closed)",
		)

	# 企业 deny 一票否决（按目标身份；与原生 mcp__ 分支同源）。
	try:
		from extension import mcp_scopes as _scopes

		pol = _scopes.load_enterprise_policy()
		if _scopes.mcp_server_denied(server, policy=pol) or _scopes.mcp_tool_denied(
			server, raw, policy=pol
		):
			return PolicyDecision(
				decision=PermissionDecision.DENY,
				reason="mcp_enterprise_deny",
				matched_rule="mcp_enterprise_deny",
				prompt=f"MCP tool {target.name} is denied by enterprise policy",
				mcp_target=target.name,
			)
	except Exception:  # noqa: BLE001 — deny 读取失败不放松权限
		pass

	# F2.5 移除→DENY 门：会话内停用（server 关停/取消勾选）→ 拒绝。
	# 该 DENY 先于 grant 匹配（impl 返回即终局），用户停用不可被授权穿越。
	probe = getattr(target, "enabled_probe", None)
	if callable(probe):
		try:
			if not probe():
				return PolicyDecision(
					decision=PermissionDecision.DENY,
					reason="mcp_disabled",
					matched_rule="mcp_disabled",
					prompt=f"MCP tool {target.raw_name} 已被用户停用（原生目录下个会话重塑）",
					mcp_target=target.name,
				)
		except Exception:  # noqa: BLE001 — 探针故障不误伤
			pass

	decision = mcp_policy_decision(
		target.name, str(getattr(target, "policy", "") or "outbound_ask")
	)
	return PolicyDecision(
		decision=decision.decision,
		reason=decision.reason,
		path=decision.path,
		prompt=decision.prompt,
		matched_rule=decision.matched_rule,
		choices=decision.choices,
		peer_summary=decision.peer_summary,
		mcp_target=target.name,
	)


def evaluate_policy(
	name: str,
	tool_input: dict | None,
	*,
	cwd: str,
	allowed_paths: list[str] | None = None,
	tool: object | None = None,
) -> PolicyDecision:
	"""评估工具是否允许 / 需要确认 / 拒绝（T10：外层叠加 grant store）。

	ASK 先查 always-allow 授权（"don't ask again"）：命中 → ALLOW(matched_rule=
	"grant_store")。守卫：DENY 不可被 grant 触碰（impl 已终态返回）；worker
	写作用域 / 远程会话 / permission_mode=always（显式逐条确认意图）一律跳过。
	"""
	decision = evaluate_policy_impl(
		name, tool_input, cwd=cwd, allowed_paths=allowed_paths, tool=tool
	)
	if decision.decision != PermissionDecision.ASK:
		return decision
	try:
		from permissions.store import default_grant_store, grant_fingerprint
		from permissions.write_scope import get_write_scope

		if get_write_scope() is not None:
			return decision  # worker 沙箱：grant 不得放宽
		if is_remote_session(_session_id()):
			return decision  # 远程会话不得静默放行（§34 不变量）
		if permission_mode() == "always":
			return decision  # 用户显式要求逐条确认
		# G29: Bash 组合/多语句/写重定向命令不得吃「前缀 token」grant——
		# `git status && curl x|sh` 不能命中 `git status` 的 always-allow。
		if (name or "").strip().lower() == "bash":
			try:
				from permissions.bash_policy import bash_command_is_composite

				cmd = ""
				if isinstance(tool_input, dict):
					_c = tool_input.get("command")
					if isinstance(_c, str):
						cmd = _c
				if bash_command_is_composite(cmd):
					return decision
			except Exception:
				return decision
		fp = grant_fingerprint(
			name,
			tool_input,
			matched_rule=str(getattr(decision, "matched_rule", "") or ""),
			mcp_target=str(getattr(decision, "mcp_target", "") or ""),
		)
		if not fp:
			return decision
		# 存取同一身份：网关调用按解析后的目标注册名匹配（control.py 落库同源）。
		identity_name = (
			str(getattr(decision, "mcp_target", "") or "").strip() or name
		)
		grant = default_grant_store().match(
			tool_name=identity_name, fingerprint=fp, scope=cwd or ""
		)
		if grant is None:
			return decision
		return PolicyDecision(
			decision=PermissionDecision.ALLOW,
			reason="always_allow_grant",
			matched_rule="grant_store",
			prompt=f"Auto-allowed by saved grant: {grant.fingerprint}",
			mcp_target=str(getattr(decision, "mcp_target", "") or ""),
		)
	except Exception:
		return decision


def evaluate_policy_impl(
	name: str,
	tool_input: dict | None,
	*,
	cwd: str,
	allowed_paths: list[str] | None = None,
	tool: object | None = None,
) -> PolicyDecision:
	"""评估工具是否允许 / 需要确认 / 拒绝。"""
	raw_name = (name or "").strip()
	roots = _effective_roots(cwd, allowed_paths)
	pol = load_workspace_policy(cwd)

	if raw_name and raw_name in pol.deny_tools:
		return PolicyDecision(
			decision=PermissionDecision.DENY,
			reason="policy_deny_tool",
			matched_rule="policy_deny_tool",
			prompt=f"Tool {raw_name} is denied by .xeyo-policy.json",
		)

	# F3：MCP 动态工具分支 —— 企业 deny 最严胜出 → tool_policies → 未知兜底。
	if raw_name.startswith("mcp__"):
		return _evaluate_mcp(raw_name, tool_input, cwd=cwd, tool=tool)

	# F2（P0b）：网关工具 Mcp —— list/describe 元动作放行；
	# call 解析目标身份后按目标工具策略三态（指纹 v2 携带目标注册名）。
	if raw_name == "Mcp":
		return _evaluate_mcp_gateway(raw_name, tool_input, tool=tool)

	if raw_name in _ALWAYS_ALLOW:
		return PolicyDecision(
			decision=PermissionDecision.ALLOW,
			reason="tool_unrestricted_p0",
			matched_rule="always_allow",
		)

	# 外发工具：工作区路径校验后一律 ASK（不再当读路径 / 恒放行）。
	if raw_name in _OUTBOUND_ASK_TOOLS:
		path: str | None = None
		if raw_name == "SendToWeChat":
			raw = _pick_path(tool_input, "path", "file_path", "filePath")
			if not raw:
				return PolicyDecision(
					decision=PermissionDecision.DENY,
					reason="missing_file_path",
					matched_rule="outbound_missing_path",
				)
			path = expand_to_abs(raw, cwd=cwd)
			if not path_in_allowed_working_path(
				path, cwd=cwd, allowed_working_paths=roots
			):
				return PolicyDecision(
					decision=PermissionDecision.DENY,
					reason="path_outside_working_directory",
					matched_rule="outbound_outside_deny",
					path=path,
				)
		elif raw_name == "WebFetch":
			url = ""
			if isinstance(tool_input, dict):
				url = str(tool_input.get("url") or "").strip()
			path = url or None
		elif raw_name == "WebSearch":
			q = ""
			if isinstance(tool_input, dict):
				q = str(tool_input.get("query") or "").strip()
			path = q or None
		# 外发工具：max 档（never/allow=免确认）自动放行，但 SendToWeChat 工作区外
		# 文件在路径校验分支已 DENY（数据外发边界仍保留）；risk/always 一律 ASK。
		if is_max_permission_mode():
			return PolicyDecision(
				decision=PermissionDecision.ALLOW,
				reason="allowed",
				matched_rule="outbound_max_allow",
				path=path,
			)
		return PolicyDecision(
			decision=PermissionDecision.ASK,
			reason="needs_confirmation",
			matched_rule="outbound_ask",
			path=path,
			prompt=_prompt_for_outbound(raw_name, path),
		)

	# 桌面 UI 工具：按 action 分流（list 放行；预览/面板/跨会话发送一律 ASK）。
	if raw_name in _UI_ASK_TOOLS:
		return _evaluate_ui_ask(tool_input, cwd=cwd, roots=roots)

	# 子 Agent spawn：默认允许；always 模式需确认。深度/白名单/写锁/并发由 AgentTool 强制。
	if raw_name == "Agent":
		if permission_mode() == "always":
			return PolicyDecision(
				decision=PermissionDecision.ASK,
				reason="needs_confirmation",
				matched_rule="agent_confirm_ask",
				prompt=_prompt_for_agent(),
			)
		return PolicyDecision(
			decision=PermissionDecision.ALLOW,
			reason="allowed",
			matched_rule="agent_allow",
		)

	if raw_name == "Bash":
		command = ""
		if isinstance(tool_input, dict):
			raw_cmd = tool_input.get("command")
			command = raw_cmd.strip() if isinstance(raw_cmd, str) else ""
		return _evaluate_bash(command, cwd=cwd, roots=roots)

	if raw_name in _READ_PATH_TOOLS:
		raw = _pick_path(tool_input, "file_path", "path", "filePath", "notebook_path")
		path = expand_to_abs(raw, cwd=cwd) if raw else os.path.abspath(cwd)
		ctx = default_permission_context(cwd)
		ctx.allowed_working_paths = list(roots)
		decision = check_read_permission_for_path(path, context=ctx)
		if decision == PermissionDecision.ALLOW:
			return PolicyDecision(
				decision=PermissionDecision.ALLOW,
				reason="allowed",
				matched_rule="read_allow",
				path=path,
			)
		if decision == PermissionDecision.ASK:
			return PolicyDecision(
				decision=PermissionDecision.ASK,
				reason="needs_confirmation",
				matched_rule="read_ask",
				path=path,
				prompt=_prompt_for_read(name, path),
			)
		# DENY：给出具体原因，与旧 gate 契约一致。
		if not path_in_allowed_working_path(
			path, cwd=cwd, allowed_working_paths=ctx.allowed_working_paths or [cwd]
		):
			reason = "path_outside_working_directory"
			rule = "read_deny"
		elif is_secret_path(path, cwd=cwd):
			reason = "secret_path"
			rule = "secret_path_deny"
		elif is_dangerous_path(path, cwd=cwd):
			reason = "dangerous_path"
			rule = "read_deny"
		else:
			reason = "denied"
			rule = "read_deny"
		return PolicyDecision(
			decision=PermissionDecision.DENY,
			reason=reason,
			matched_rule=rule,
			path=path,
		)

	if raw_name in _WRITE_PATH_TOOLS:
		raw = _pick_path(tool_input, "file_path", "path", "filePath", "notebook_path")
		if raw_name in {"Memory"}:
			return PolicyDecision(
				decision=PermissionDecision.ALLOW,
				reason="memory_tool_confined",
				matched_rule="memory_allow",
			)
		if not raw:
			return PolicyDecision(
				decision=PermissionDecision.DENY,
				reason="missing_file_path",
				matched_rule="missing_path",
			)
		path = expand_to_abs(raw, cwd=cwd)
		# 策略文件本身：Agent 不可写（防自我提权）。
		if is_policy_file(path, cwd=cwd):
			return PolicyDecision(
				decision=PermissionDecision.DENY,
				reason="policy_file_immutable",
				matched_rule="policy_file_deny",
				path=path,
				prompt="Cannot modify .xeyo-policy.json via Agent tools",
			)
		# 密钥/凭据：硬 DENY。
		if is_secret_path(path, cwd=cwd):
			return PolicyDecision(
				decision=PermissionDecision.DENY,
				reason="secret_path",
				matched_rule="secret_path_deny",
				path=path,
				prompt=f"Cannot access secret path: {path}",
			)
		# 子 Agent 写 scope 硬门禁。
		scope_reason = write_scope_deny_reason(path, cwd=cwd)
		if scope_reason:
			return PolicyDecision(
				decision=PermissionDecision.DENY,
				reason=scope_reason,
				matched_rule="write_scope_deny",
				path=path,
				prompt=f"Write outside sub-agent scope: {path}",
			)
		from memory.memdir import is_under_memdir, workspace_id

		wsid = workspace_id(os.path.abspath(cwd))
		if is_under_memdir(path, wsid=wsid):
			if raw_name == "Write" and not _memdir_write_schema_ok(path, tool_input):
				return PolicyDecision(
					decision=PermissionDecision.DENY,
					reason="memdir_schema_rejected",
					matched_rule="memdir_schema",
					path=path,
				)
			return PolicyDecision(
				decision=PermissionDecision.ALLOW,
				reason="memdir_allow",
				matched_rule="memdir_allow",
				path=path,
			)
		# T12：受保护元数据（.git/.xeyo/.agents）——workspace 内默认只读。
		# 放在 memdir 分支之前会导致 Memory 工具误伤，故置于 memdir allow 之后。
		protected = protected_metadata_reason(path, cwd=cwd)
		if protected is not None:
			return PolicyDecision(
				decision=PermissionDecision.DENY,
				reason="protected_metadata",
				matched_rule="protected_metadata_deny",
				path=path,
				prompt=protected,
			)
		# 按审批模式决定（XEYO_PERMISSION_MODE）。工作区外默认拒绝；
		# max 档（never/allow）允许越出工作区（写日志/临时文件等），
		# 但密钥/危险路径仍由上方/下方的硬拦分支裁决。
		if not path_in_allowed_working_path(
			path, cwd=cwd, allowed_working_paths=roots
		) and not is_max_permission_mode():
			return PolicyDecision(
				decision=PermissionDecision.DENY,
				reason="path_outside_working_directory",
				matched_rule="write_outside_deny",
				path=path,
			)
		# 审批模式合成（T26 权限单向性）：仓库策略只能收紧，不能放宽用户审批。
		mode = permission_mode()
		if mode in _AUTO_WRITE_MODES:
			# 最高审批模式（never/allow = 完全访问/免确认）：用户显式授予
			# 工作区常规写自动放行。仓库默认 write=ask 收紧若在此处反向 override
			# 成 always（每写必问），会让最高权限仍弹「允许写入」确认（smoke-test #1）。
			# 故最高权限跳过该收紧；安全边界（密钥/策略/受保护元数据/工作区外/
			# 危险路径）仍由上方硬拦截分支守护，不受此豁免。
			pass
		elif pol.write in ("ask", "always"):
			# 收紧：非最高权限下，无论用户/请求模式如何，强制每写确认。
			mode = "always"
		elif pol.write in ("never", "allow") or pol.write == "risk":
			# risk / never / allow 均为「仓库愿意放宽」的表达；单向性规定不得把
			# 用户更严的选择（always=每写必问）放宽为自动放行，故保持用户模式
			# （no-op）。仓库要放宽只能走用户侧 grant store / preset（T10）。
			pass
		dangerous = is_dangerous_path(path, cwd=cwd)
		from permissions.write_scope import get_write_scope

		# 子 Agent（write_scope 已激活）：无 ASK 挂起——危险 DENY，其余在 scope 内 ALLOW。
		worker_scope = get_write_scope()
		if worker_scope is not None:
			if dangerous:
				return PolicyDecision(
					decision=PermissionDecision.DENY,
					reason="worker_dangerous_deny",
					matched_rule="worker_no_ask",
					path=path,
					prompt=f"Sub-agent cannot write dangerous path: {path}",
				)
			return PolicyDecision(
				decision=PermissionDecision.ALLOW,
				reason="worker_scope_auto",
				matched_rule="worker_no_ask",
				path=path,
			)
		# 多会话热文件：他会话 busy 持有时强制三选 ASK（auto-allow 也不能跳过）。
		peer = _peer_write_conflict(path, cwd=cwd)
		if peer is not None:
			return peer
		# never/allow：仅安全路径自动放行；危险路径仍 ASK（无 resolver 时 DENY）。
		if mode in _AUTO_WRITE_MODES and not dangerous:
			return PolicyDecision(
				decision=PermissionDecision.ALLOW,
				reason="auto_approve",
				matched_rule="write_auto_allow",
				path=path,
			)
		if mode == "always" or dangerous:
			return PolicyDecision(
				decision=PermissionDecision.ASK,
				reason="needs_confirmation",
				matched_rule=(
					"write_confirm_ask" if mode == "always" else "write_risk_ask"
				),
				path=path,
				prompt=_prompt_for_write(raw_name, path),
			)
		return PolicyDecision(
			decision=PermissionDecision.ALLOW,
			reason="allowed",
			matched_rule="write_risk_allow",
			path=path,
		)

	# 未知工具：默认 ask，不再宽松透传。
	return PolicyDecision(
		decision=PermissionDecision.ASK,
		reason="unknown_tool_default_ask",
		matched_rule="unknown_tool_ask",
		prompt=f"Allow using unknown tool {raw_name}?",
	)
