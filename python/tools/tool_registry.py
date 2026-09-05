from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from audit.log import default_audit_log
from engine.abort import AbortController
from msgtypes.message import ToolUse
from permissions.ask_store import default_ask_store
from permissions.filesystem import (
	PermissionDecision,
	expand_to_abs,
	mark_permission_preapproved,
	path_in_allowed_working_path,
)
from permissions.policy import agent_mode, evaluate_policy, readonly_gate
from permissions.workspace_policy import load_workspace_policy
from tools.ask_user_question_tool import ASK_REQUEST_ID_KEY, ASK_USER_TOOL_NAME
from tools.base_tool import Tool, ToolResult
from tools.bash_tool.dup_redirect import BashRoutePlan, plan_bash_route

if TYPE_CHECKING:
	from engine.permission_coordinator import PermissionCoordinator


def _observe_bash_route(
	tool_use: ToolUse, raw_input: dict[str, Any], coordinator: "PermissionCoordinator | None"
) -> None:
	"""Phase 0/1 观测（docs/设计/43）：Bash 纯文件读命令命中即记审计，不拦截。

	记录 ``tool.routed_observed``（tier/routed_to/摘要），用于决策与效果基线；
	无论后续是否真路由都会记录（单元：plan 命中）。
	"""
	try:
		plan = plan_bash_route(str(raw_input.get("command") or ""))
		if plan is None:
			return
		default_audit_log().record(
			"tool.routed_observed",
			session_id=coordinator.session_id if coordinator else "",
			turn_id=coordinator.turn_id if coordinator else "",
			request_id=tool_use.id,
			tool_name="Bash",
			tier=plan.tier,
			routed_to=plan.tool_name,
			command=plan.brief,
		)
	except Exception:  # noqa: BLE001 — 观测失败绝不挡执行
		pass


def _routed_target_in_workspace(
	plan: BashRoutePlan, *, cwd: str, allowed_paths: list[str] | None
) -> bool:
	"""43 号成员前置：目标工具主路径是否落在工作区内。

	- 无显式 path（`rg pat`、`cat 相对路径`）→ 按 cwd=工作区 → 区内（True）；
	- 有显式 path（Read.file_path / Glob.path / Grep.path）→ 复用路径狱同一判定。
	"""
	path = plan.tool_input.get("file_path") or plan.tool_input.get("path")
	if not path:
		return True
	return path_in_allowed_working_path(
		str(path), cwd=cwd, allowed_working_paths=allowed_paths
	)


def _bash_shape_key(plan: BashRoutePlan) -> str:
	"""Phase 2 渐进强制的命令形状签名：tier + 目标工具 + 主参数。"""
	arg = (
		plan.tool_input.get("file_path")
		or plan.tool_input.get("path")
		or plan.tool_input.get("pattern")
	)
	return f"{plan.tier}|{plan.tool_name}|{str(arg) if arg is not None else ''}"


class ToolRegistry:
	"""工具注册表；run 前统一走权限 gate，run 后统一走输出预算 seam。"""

	#: T1：默认输出预算（字符）；per-tool 覆盖见 ToolMeta.output_budget。
	DEFAULT_OUTPUT_BUDGET = 16_000
	#: 预览头/尾长度（预算截断后模型可见部分）。
	PREVIEW_HEAD = 6_000
	PREVIEW_TAIL = 2_000

	def __init__(self, *, cwd: str | None = None) -> None:
		self._tools: dict[str, Tool] = {}
		self._cwd = os.path.abspath(os.path.expanduser(cwd)) if cwd else ""
		self._schemas_cache: list[dict] | None = None
		#: 43 号 Phase 2：会话内（registry 生命周期）同命令形状重复命中计数，用于渐进强制。
		self._bash_repeats: dict[str, int] = {}

	@property
	def cwd(self) -> str:
		return self._cwd

	def set_cwd(self, cwd: str) -> None:
		self._cwd = os.path.abspath(os.path.expanduser(cwd or "."))

	def register(self, tool: Tool) -> None:
		self._tools[tool.name] = tool
		self._schemas_cache = None

	def get(self, name: str) -> Tool | None:
		return self._tools.get(name)

	def schemas(self) -> list[dict]:
		"""返回工具 schema 浅拷贝；默认套用短 description（schema 预算）。

		F2（P0b）：``exposure=="hidden"`` 的工具不进 schemas，但**保留注册**
		—— 模型幻觉调用仍经 run() 权限三态（fail-safe），可用性由网关/管理面
		按需描述。注意：hidden 集合在会话内不变（tools 数组冻结红线）。
		"""
		from tools.meta import apply_schema_budget, exposure_of

		if self._schemas_cache is None:
			self._schemas_cache = [
				apply_schema_budget(t.schema())
				for t in self._tools.values()
				if exposure_of(t) != "hidden"
			]
		return list(self._schemas_cache)

	async def _execute_audited(
		self,
		tool: Tool,
		tool_use: ToolUse,
		abort: AbortController,
		*,
		session_id: str = "",
		turn_id: str = "",
	) -> ToolResult:
		"""真实执行并写入 tool.started / tool.finished 审计事件。"""
		audit = default_audit_log()
		started = time.monotonic()
		audit.record(
			"tool.started",
			session_id=session_id,
			turn_id=turn_id,
			request_id=tool_use.id,
			tool_name=tool.name,
		)
		try:
			# 策略层已 ALLOW / skip_ask：工具内 check_permissions 不得再把 ASK 降成 DENY。
			with mark_permission_preapproved(True):
				result = await tool.execute(tool_use.input, abort)
		except BaseException as exc:
			audit.record(
				"tool.finished",
				session_id=session_id,
				turn_id=turn_id,
				request_id=tool_use.id,
				tool_name=tool.name,
				duration_ms=int((time.monotonic() - started) * 1000),
				is_error=True,
				error=str(exc)[:500],
			)
			raise
		# T1：原始输出先落盘（raw → spill），再替换为「预览 + 全文路径」。
		result = self._apply_output_budget(tool, result, session_id=session_id)

		# PostToolUse 观测钩子：只注入上下文，绝不改结果（hooks 开才执行）。
		await self._post_tool_hooks(self._cwd, tool.name, result)

		audit.record(
			"tool.finished",
			session_id=session_id,
			turn_id=turn_id,
			request_id=tool_use.id,
			tool_name=tool.name,
			duration_ms=int((time.monotonic() - started) * 1000),
			is_error=bool(result.is_error),
		)
		return result

	def _apply_output_budget(
		self, tool: Tool, result: ToolResult, *, session_id: str = ""
	) -> ToolResult:
		"""超预算输出 → spill 原文 + 预览替换（T1/T27 顺序：raw 先落盘）。

		- is_error 结果不 spill（错误本就应完整可见且通常很短）；
		- spill 失败原样返回（不 isError、不丢内容）；
		- 截断元数据标注「预算截断」，与工具失败区分。
		"""
		if result.is_error or not isinstance(result.content, str) or not result.content:
			return result
		from tools.meta import meta_for

		meta = meta_for(tool.name)
		# 实例级覆盖优先（F6a per-tool output_token_limits → McpTool.output_budget）；
		# 静态 ToolMeta 次之；最后默认预算。
		budget = getattr(tool, "output_budget", None)
		if budget is None:
			budget = (
				meta.output_budget
				if meta is not None and meta.output_budget is not None
				else self.DEFAULT_OUTPUT_BUDGET
			)
		if budget <= 0 or len(result.content) <= budget:
			return result
		try:
			from tools.spill import save_text

			ref = save_text(session_id or "session", result.content)
		except Exception:  # noqa: BLE001 — spill 失败：原样返回，不 isError
			return result
		head = result.content[: self.PREVIEW_HEAD]
		tail = result.content[-self.PREVIEW_TAIL :]
		preview = (
			f"{head}\n\n…[middle truncated by output budget]…\n\n{tail}\n\n"
			f"[output truncated: 预算截断（非错误），原始 {len(result.content)} 字符；"
			f"full output: {ref.path}]"
		)
		default_audit_log().record(
			"tool.spill",
			session_id=session_id,
			tool_name=tool.name,
			path=ref.path,
			original_chars=len(result.content),
			spill_bytes=ref.bytes,
		)
		metadata = dict(result.metadata or {})
		metadata.update(
			{
				"spilled": True,
				"spill_path": ref.path,
				"original_chars": len(result.content),
				"truncation": "output_budget",
			}
		)
		return ToolResult(content=preview, is_error=False, metadata=metadata)

	async def _hook_blocker(
		self,
		event: str,
		cwd: str | None,
		tool_name: str,
		tool_input: dict,
		abort_label: str,
	) -> "ToolResult | None":
		"""运行事件钩子；若钩子 abort（或 PermissionRequest 未批准 fail-closed）→ 返回短路结果。

		开关未开 / 钩子故障一律返回 None（除 abort 已在 hooks 层归类）。
		"""
		if not cwd:
			return None
		try:
			from extension.config import load_ext_config
			from extension.hooks import run_event_hooks_async

			cfg = load_ext_config(cwd)
			if not cfg.hooks_enabled():
				return None
			out = await run_event_hooks_async(
				event, cwd, {"tool_name": tool_name, "tool_input": tool_input}, config=cfg
			)
			if out.should_abort:
				return ToolResult(
					content=f"aborted by plugin hook on {abort_label}",
					is_error=True,
					metadata={"hook_abort": True, "event": event},
				)
		except Exception:  # noqa: BLE001 — 钩子故障不阻断主路径（fail-open 观测侧）。
			import logging

			logging.getLogger(__name__).debug("plugin hook %s failed", event, exc_info=True)
		return None

	async def _post_tool_hooks(
		self, cwd: str | None, tool_name: str, result: "ToolResult"
	) -> None:
		"""PostToolUse 观测钩子：只注入上下文，绝不改结果。"""
		if not cwd:
			return
		try:
			from extension.config import load_ext_config
			from extension.hooks import run_event_hooks_async

			cfg = load_ext_config(cwd)
			if not cfg.hooks_enabled():
				return
			await run_event_hooks_async(
				"PostToolUse",
				cwd,
				{"tool_name": tool_name, "is_error": bool(result.is_error)},
				config=cfg,
			)
		except Exception:  # noqa: BLE001
			import logging

			logging.getLogger(__name__).debug("plugin post-tool hook failed", exc_info=True)

	async def run(
		self,
		tool_use: ToolUse,
		abort: AbortController,
		*,
		coordinator: "PermissionCoordinator | None" = None,
		skip_ask: bool = False,
	) -> ToolResult:
		tool = self._tools.get(tool_use.name)
		if tool is None:
			return ToolResult(
				content=f"unknown tool: {tool_use.name}", is_error=True
			)

		readonly_reason = readonly_gate(tool_use.name, tool=tool)
		if readonly_reason:
			default_audit_log().record(
				"permission.denied",
				session_id=coordinator.session_id if coordinator else "",
				turn_id=coordinator.turn_id if coordinator else "",
				request_id=tool_use.id,
				tool_name=tool_use.name,
				reason=readonly_reason,
				agent_mode=agent_mode(),
				agent_id=str(getattr(tool, "_agent_id", "") or ""),
			)
			return ToolResult(
				content=f"{tool_use.name} is not available in read-only mode",
				is_error=True,
				metadata={"permission_reason": readonly_reason},
			)

		# 优先使用工具绑定的 cwd（与会话工作区一致）。
		tool_cwd = getattr(tool, "_cwd", None)
		cwd = (
			os.path.abspath(tool_cwd)
			if isinstance(tool_cwd, str) and tool_cwd.strip()
			else self._cwd
		)
		try:
			from engine.workspace_context import (
				WorkspaceContext,
				get_workspace_context,
				set_workspace_context,
			)

			if get_workspace_context() is None and cwd:
				set_workspace_context(
					WorkspaceContext(
						session_id=coordinator.session_id if coordinator else "",
						cwd=cwd,
					)
				)
		except Exception:
			pass
		allowed_paths: list[str] | None = None
		try:
			from engine.workspace_context import get_workspace_context

			ws = get_workspace_context()
			if ws is not None and ws.allowed_paths:
				allowed_paths = list(ws.allowed_paths)
		except Exception:
			allowed_paths = None
		raw_input = tool_use.input if isinstance(tool_use.input, dict) else {}
		# AskUserQuestion：结构化提问挂起（同构于权限 ASK）。resume 后由 query_loop
		# 把答案作为 ToolResult 交回模型，无需再执行这里。
		if tool_use.name == ASK_USER_TOOL_NAME:
			if skip_ask:
				# 直接调用（脚手架/测试）：返回需要作答的提示，避免二次挂起。
				return await self._execute_audited(
					tool,
					tool_use,
					abort,
					session_id=coordinator.session_id if coordinator else "",
					turn_id=coordinator.turn_id if coordinator else "",
				)
			if coordinator is None:
				return ToolResult(
					content="AskUserQuestion requires a session to suspend into",
					is_error=True,
				)
			from tools.ask_user_question_tool.ask_user_question_tool import (
				format_questions_payload,
			)

			payload = format_questions_payload(raw_input)
			question = str(payload.get("question") or "").strip()
			options = list(payload.get("options") or [])
			default = payload.get("default")
			if not question:
				return ToolResult(
					content="AskUserQuestion requires a question", is_error=True
				)
			store = default_ask_store()
			item = store.create(
				session_id=coordinator.session_id,
				turn_id=coordinator.turn_id,
				question=question,
				options=options,
				default=str(default) if default is not None else None,
			)
			return ToolResult(
				content="",
				is_error=False,
				metadata={
					"ask_pending": item.request_id,
					"question": question,
					"options": options,
					"default": str(default) if default is not None else None,
					"expires_at": item.expires_at,
				},
			)

		# PreToolUse 钩子门（hooks 开关开才执行；abort → 短路，不进入权限/执行）。
		_pre_blocker = await self._hook_blocker(
			"PreToolUse", cwd, tool_use.name, raw_input, abort_label=tool_use.name
		)
		if _pre_blocker is not None:
			return _pre_blocker

		decision = evaluate_policy(
			tool_use.name, raw_input, cwd=cwd, allowed_paths=allowed_paths, tool=tool
		)
		if decision.decision == PermissionDecision.ALLOW:
			if tool_use.name == "Bash":
				handled = await self._bash_routing(
					tool_use,
					raw_input,
					tool,
					abort,
					coordinator,
					cwd=cwd,
					allowed_paths=allowed_paths,
				)
				if handled is not None:
					return handled
			return await self._execute_audited(
				tool,
				tool_use,
				abort,
				session_id=coordinator.session_id if coordinator else "",
				turn_id=coordinator.turn_id if coordinator else "",
			)
		if decision.decision == PermissionDecision.DENY:
			default_audit_log().record(
				"permission.denied",
				session_id=coordinator.session_id if coordinator else "",
				turn_id=coordinator.turn_id if coordinator else "",
				request_id=tool_use.id,
				tool_name=tool_use.name,
				reason=decision.reason,
				agent_id=str(getattr(tool, "_agent_id", "") or ""),
				matched_rule=str(getattr(decision, "matched_rule", "") or ""),
			)
			return ToolResult(
				content=(
					decision.prompt
					or f"Permission denied: {decision.reason}"
				),
				is_error=True,
				metadata={"permission_reason": decision.reason},
			)
		# ASK
		if skip_ask:
			return await self._execute_audited(
				tool,
				tool_use,
				abort,
				session_id=coordinator.session_id if coordinator else "",
				turn_id=coordinator.turn_id if coordinator else "",
			)
		if coordinator is None:
			# 子 Agent / 无 UI：ASK 一律 DENY（不再静默放行工作区写入）。
			from permissions.pending_ttl import UNAVAILABLE_COPY

			return ToolResult(
				content=f"{UNAVAILABLE_COPY} (no resolver: {decision.reason})",
				is_error=True,
				metadata={"permission_reason": decision.reason or "needs_confirmation"},
			)
		prompt = decision.prompt or f"Allow {tool_use.name}?"
		cmd_summary = ""
		if tool_use.name == "Bash" and isinstance(raw_input, dict):
			from audit.redact import command_summary

			raw_cmd = raw_input.get("command")
			if isinstance(raw_cmd, str):
				cmd_summary = command_summary(raw_cmd)
		choices = tuple(getattr(decision, "choices", ()) or ())
		peer_summary = str(getattr(decision, "peer_summary", "") or "")
		# PermissionRequest 钩子门（fail-closed）：abort/未批准 → 直接 DENY，不入挂起。
		_perm_blocker = await self._hook_blocker(
			"PermissionRequest", cwd, tool_use.name, raw_input, abort_label=tool_use.name
		)
		if _perm_blocker is not None:
			return _perm_blocker
		request_id = coordinator.request(
			tool_name=tool_use.name,
			tool_input=raw_input,
			reason=decision.reason,
			prompt=prompt,
			matched_rule=str(getattr(decision, "matched_rule", "") or ""),
			mcp_target=str(getattr(decision, "mcp_target", "") or ""),
			command_summary=cmd_summary,
			choices=choices,
			peer_summary=peer_summary,
		)
		return ToolResult(
			content="",
			is_error=False,
			metadata={
				"permission_pending": request_id,
				"tool_name": tool_use.name,
				"input": raw_input,
				"reason": decision.reason,
				"prompt": prompt,
				"matched_rule": str(getattr(decision, "matched_rule", "") or ""),
				"choices": list(choices),
				"peer_summary": peer_summary,
				"path": decision.path,
			},
		)

	async def _bash_routing(
		self,
		tool_use: ToolUse,
		raw_input: dict[str, Any],
		tool: Tool,
		abort: AbortController,
		coordinator: "PermissionCoordinator | None",
		*,
		cwd: str,
		allowed_paths: list[str] | None,
	) -> ToolResult | None:
		"""Phase 1（docs/设计/43）：Bash→专用工具 的路由 / L2 决策。

		返回 ToolResult → 调用方直接返回；返回 None → 走正常 Bash 执行。
		决策表（在 Bash 已 ALLOW 之后）：
		  - plan 未命中              → None（原样执行 Bash，构建/测试/进程等）
		  - ``bash_routing`` 非 auto（主会话）→ L2 错误提示（保留现行为）
		  - ``bash_routing`` 非 auto（worker）→ None（SUBAGENT_APPEND 允许短只读）
		  - auto + 目标路径区外       → None（直行 bash，避免 路由→DENY→回退 白跑）
		  - auto + 目标路径区内       → 透明路由（_route_bash）
		"""
		plan = plan_bash_route(str(raw_input.get("command") or ""))
		if plan is None:
			return None
		_observe_bash_route(tool_use, raw_input, coordinator)
		pol = load_workspace_policy(cwd)
		if pol.bash_routing != "auto":
			from tools.bash_tool.bash_tool import _worker_bash_active

			if _worker_bash_active():
				return None
			# Phase 2 渐进强制（仅作用于 L2 报错路径，防拉锯循环）：同会话同命令形状
			# 重复命中 ≥ bash_escalate 次后，本次及后续放行 bash（不再报错）。默认 0=关。
			if self._bash_escalate_conceded(plan, pol.bash_escalate):
				return None
			return ToolResult(content=plan.hint, is_error=True)
		if not _routed_target_in_workspace(plan, cwd=cwd, allowed_paths=allowed_paths):
			return None
		return await self._route_bash(
			tool_use, plan, tool, abort, coordinator, cwd=cwd
		)

	def _bash_escalate_conceded(self, plan: BashRoutePlan, escalate: int) -> bool:
		"""Phase 2：同命令形状重复命中计数；达到阈值则本次放行 bash（返回 True）。"""
		if escalate <= 0:
			return False
		key = _bash_shape_key(plan)
		repeats = self._bash_repeats.get(key, 0) + 1
		self._bash_repeats[key] = repeats
		return repeats >= escalate

	async def _route_bash(
		self,
		tool_use: ToolUse,
		routed: BashRoutePlan,
		tool: Tool,
		abort: AbortController,
		coordinator: "PermissionCoordinator | None",
		*,
		cwd: str,
	) -> ToolResult:
		"""Bash→专用工具透明路由：零额外往返，结果附一行 [routed] 纠正提示。

		安全不变式：Bash 策略已先完整裁决（deny/密钥读/写防护/peer），此处只把
		**已 ALLOW** 的命令换成等价专用工具执行；目标工具再走一次自身三态权限+审计+
		输出预算（含共享 ReadFileState，不破坏 "file unchanged" 缓存与 Edit 检查）。
		成员前置已保证目标在工作区内，但会话 allowed_paths 变化等仍可能 DENY——此时
		回退执行原 Bash（已 ALLOW），绝不把 DENY 当结果交给模型。
		"""
		target_input = dict(routed.tool_input)
		if routed.tool_name == "Read":
			try:
				target_input["file_path"] = expand_to_abs(
					str(target_input.get("file_path") or ""), cwd=cwd
				)
			except Exception:  # noqa: BLE001 — 解析失败按原样交给 Read 报错
				pass
		target_use = ToolUse(id=tool_use.id, name=routed.tool_name, input=target_input)
		result = await self.run(target_use, abort, coordinator=coordinator)
		if (result.metadata or {}).get("permission_reason"):
			# 目标工具路径狱拒绝（异常/会话 allowed_paths 变化）：回退原 Bash（已 ALLOW）。
			return await self._execute_audited(
				tool,
				tool_use,
				abort,
				session_id=coordinator.session_id if coordinator else "",
				turn_id=coordinator.turn_id if coordinator else "",
			)
		try:
			default_audit_log().record(
				"tool.routed",
				session_id=coordinator.session_id if coordinator else "",
				turn_id=coordinator.turn_id if coordinator else "",
				request_id=tool_use.id,
				tool_name="Bash",
				routed_to=routed.tool_name,
				command=routed.brief,
			)
		except Exception:  # noqa: BLE001 — 审计失败不挡执行
			pass
		metadata = dict(result.metadata or {})
		metadata.update(
			{
				"routed_from_bash": True,
				"routed_tool": routed.tool_name,
				"routed_command": routed.brief,
			}
		)
		return ToolResult(
			content=f"{routed.note}\n{result.content or ''}".rstrip("\n"),
			is_error=bool(result.is_error),
			metadata=metadata,
		)
