from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections import OrderedDict
from datetime import datetime
from typing import Any, AsyncIterator

from engine.abort import AbortController, Aborted
from engine.budget import BudgetTracker
from engine.compact import build_tool_use_names, project_incremental
from engine.permission_coordinator import PermissionCoordinator
from permissions.pending_ttl import (
	CANCELLED_COPY,
	REJECTED_COPY,
	UNAVAILABLE_COPY,
	intent_for,
)
from engine.plan import default_plan_engine
from engine.process_narration import StreamNarrationGate
from engine.repeat_guard import (
	EXEMPT_TOOLS,
	RepeatCallGuard,
	ZeroHitTracker,
	ZERO_HIT_ADVICE_AT,
	clear_advice,
)
from engine.repeat_fold import IdenticalResultFold
from engine.loop_breaker import LoopBreaker
from engine.loop_ledger import LoopLedger, params_digest
from engine.observe_safety import safe_observe
from memory.l5_flag import c2_gate, l5_mode
from memory.runtime import (
	c2_llm_summary_enabled,
	maybe_force_compact_on_pressure,
	prefetch_c2_summary,
	project_for_model,
)
from memory.working import WorkingSnapshot, note_shot
from model.client import ModelClient
from prompt.assembler import PromptAssembler
from permissions.filesystem import PermissionDecision
from permissions.policy import (
	agent_mode as current_agent_mode,
	begin_permission_turn,
	evaluate_policy,
	in_subagent,
	set_agent_mode,
	tool_allowed_in_mode,
)
from session.message_store import MessageStore
from tools.base_tool import ToolResult, tool_flag
from tools.orchestration import (
	_run_one_tool,
	is_concurrency_safe,
	run_tools_partitioned,
)
from tools.tool_registry import ToolRegistry

from msgtypes.events import (
    AskUserPendingEvent,
    AskUserResolvedEvent,
    AssistantDelta,
    ReasoningDelta,
    ContextCompressionEvent,
    EngineEvent,
    FinalEvent,
    LlmRetryEvent,
    LlmRetryStartedEvent,
    PermissionPendingEvent,
    PermissionResolvedEvent,
    PlanPendingEvent,
    PlanResolvedEvent,
    StoppedEvent,
    ToolCallEvent,
    ToolProgressEvent,
    ToolResultEvent,
    UsageEvent,
)
from usage.pricing import split_usage
from memory.token import token_len
from msgtypes.message import Message, ToolUse, assistant_text_message, tool_result_message
from common.errors import (
    EmptyResponseError,
    ProviderError,
    classify_llm_failure,
    empty_response_failure,
    friendly_error,
)

# 交互 / 计划 / 子代理：有会话级副作用，绝不投机提前跑。
_EARLY_BLOCKLIST = frozenset({"ExitPlanMode", "AskUserQuestion", "AskUser", "Agent"})

# T8：C2 LLM 摘要旁路预取的最小会话长度（消息数）。低于该长度即便开启了旁路
# 也不预取（避免短会话也无谓打一次模型）；由 decide/压测路径决定是否真正压缩。
_C2_LLM_PREFETCH_MIN_MESSAGES = 24


def _tool_input_summary(input: dict[str, Any]) -> str:
	"""tool_call.begin 参数摘要：压成单行 json，截断到 200 字符（T13）。"""
	try:
		raw = json.dumps(input, ensure_ascii=False, separators=(",", ":"))
	except (TypeError, ValueError):
		raw = str(input)
	raw = raw.replace("\n", " ")
	if len(raw) <= 200:
		return raw
	return raw[:200] + "…"


def early_readonly_tools_enabled() -> bool:
	"""默认开；``XEYO_EARLY_READONLY_TOOLS=0`` 关闭。"""
	raw = os.environ.get("XEYO_EARLY_READONLY_TOOLS", "1").strip().lower()
	return raw in ("1", "true", "yes", "on")


def wrap_quota_from_env(default: int = 3) -> int:
	"""收尾窗（forced_wrap_up）的剩余工具配额默认值。

	``XEYO_WRAP_QUOTA`` 逗号无关整数覆盖；0 = 维持旧"一开闸全禁"语义。
	"""
	raw = os.environ.get("XEYO_WRAP_QUOTA", "").strip()
	if raw:
		try:
			return max(0, int(raw))
		except (TypeError, ValueError):
			return default
	return default


def _publish_wrap_guide(tools: Any, cwd: str, quota: int) -> None:
	"""进入收尾窗时发布缺口清单 + 配额（wrap_gap 模块级，pre_llm_inject 消费）。

	从 TodoWrite 工具的当前清单读 output 声明,stat 磁盘缺口;失败 fail-open
	为空(不挡 wrap 主路径)。纯事实呈现,不裁决不拦截。
	"""
	try:
		from engine.wrap_gap import build_gap_lines, compose_guide_text, publish_gap

		todo_tool = tools.get("TodoWrite") if tools is not None else None
		todos = todo_tool.current_todos() if todo_tool is not None else None
		lines = build_gap_lines(todos, cwd)
		text = compose_guide_text(quota, lines)
		publish_gap(text if text.strip() else "")
	except Exception:  # noqa: BLE001 — 缺口清单只是引导增强，失败静默
		try:
			from engine.wrap_gap import publish_gap

			publish_gap("")
		except Exception:  # noqa: BLE001
			pass


def _eligible_for_early(
	registry: ToolRegistry,
	tu: ToolUse,
	*,
	forced_wrap_up: bool,
) -> bool:
	"""只读 + 并发安全 + policy ALLOW；ASK/写/外发/交互一律不提前。"""
	if forced_wrap_up:
		return False
	name = (tu.name or "").strip()
	if not name or name in _EARLY_BLOCKLIST:
		return False
	tool = registry.get(name)
	if tool is None:
		return False
	if not tool_flag(tool, "is_concurrency_safe", default=False):
		return False
	if not tool_flag(tool, "is_read_only", default=False):
		return False
	raw_input = tu.input if isinstance(tu.input, dict) else {}
	decision = evaluate_policy(name, raw_input, cwd=registry.cwd, tool=tool)
	return decision.decision == PermissionDecision.ALLOW


async def _cancel_early_tasks(
	early: dict[str, asyncio.Task[ToolResult]],
) -> None:
	for task in early.values():
		if not task.done():
			task.cancel()
	for task in early.values():
		try:
			await task
		except (asyncio.CancelledError, Aborted, Exception):
			pass


def _assistant_tool_uses(content: object) -> list[tuple[str, str]]:
    if not isinstance(content, list):
        return []
    out: list[tuple[str, str]] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        uid = str(block.get("id") or "")
        if uid:
            out.append((uid, str(block.get("name") or "tool")))
    return out


def _message_tool_call_id(m: Message) -> str:
    if m.tool_call_id:
        return m.tool_call_id
    content = m.content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                uid = str(block.get("tool_use_id") or "")
                if uid:
                    return uid
    return ""


def _repair_unpaired_tool_calls(store: MessageStore, reason: str = "aborted") -> None:
    """Insert missing tool rows immediately after their assistant tool calls."""
    items = store.items
    i = 0
    while i < len(items):
        msg = items[i]
        uses = _assistant_tool_uses(msg.content) if msg.role == "assistant" else []
        if not uses:
            i += 1
            continue
        j = i + 1
        have: set[str] = set()
        while j < len(items) and items[j].role == "tool":
            tid = _message_tool_call_id(items[j])
            if tid:
                have.add(tid)
            j += 1
        inserted = 0
        for uid, name in uses:
            if uid in have:
                continue
            store.insert(j + inserted, tool_result_message(uid, name, f"[tool {reason}]", is_error=True))
            inserted += 1
        i = j + inserted


def _fill_missing_tool_results(store: MessageStore, tool_uses: list[ToolUse], reason: str = "aborted") -> None:
    del tool_uses
    _repair_unpaired_tool_calls(store, reason)


def _safe_flush_transcript() -> None:
    """T4：强制刷 transcript 缓冲；失败静默（fail-closed 由 hydrate 合成兜底）。"""
    try:
        from session.record_transcript import flush_transcript

        flush_transcript()
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).debug(
            "transcript flush failed (T4 skip)", exc_info=True
        )


# --- 44 号：LLM 重试策略（错误码分类见 common.errors.classify_llm_failure） ---

def _llm_max_attempts() -> int:
    """单次模型请求（流）的最大尝试次数；``XEYO_LLM_MAX_ATTEMPTS`` 可覆盖，钳制 [1,5]。"""
    raw = os.environ.get("XEYO_LLM_MAX_ATTEMPTS", "3").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 3
    return max(1, min(n, 5))


def _llm_retry_delay_ms(attempt: int, retry_after_ms: int | None) -> int:
    """本地退避 500ms→10s（10% jitter）；厂商 Retry-After 有效时取其较大者。"""
    import random

    base = min(0.5 * (2 ** max(0, attempt - 1)), 10.0)
    delay_ms = int(round((base + base * random.uniform(0, 0.1)) * 1000))
    if retry_after_ms and retry_after_ms > 0:
        delay_ms = max(delay_ms, int(retry_after_ms))
    return delay_ms


def _llm_provider_name(model: object) -> str:
    return str(getattr(model, "provider", "") or "")


def _llm_model_name(model: object) -> str:
    return str(getattr(model, "_model", None) or getattr(model, "model", None) or "")


def _audit_llm_failure(
    code: str, *, attempt: int, status: int | None, provider: str, model_name: str
) -> None:
    """44 号：LLM 失败审计（best-effort，审计故障不挡主路径）。"""
    try:
        from audit.log import default_audit_log

        default_audit_log().record(
            "llm.failure",
            code=code,
            attempt=attempt,
            status=status,
            provider=provider,
            model=model_name,
        )
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).debug("llm failure audit failed", exc_info=True)


def _persist_interrupted_anchor(
    store: MessageStore, narration_gate: Any, tool_uses: list[ToolUse]
) -> bool:
    """44 号：abort 时把已产出（但未落盘）的部分输出写成 interrupted 锚消息。

    返回是否真的写了锚（GUI 已看到非空前缀）。注意：本函数只做「入史」，
    不 yield 任何增量（流已死）；失败静默——宁可缺锚也不挡 abort 主路径。
    """
    try:
        partial, _flush = narration_gate.finish(has_tools=bool(tool_uses))
    except Exception:  # noqa: BLE001
        partial = ""
    partial = (partial or "").strip()
    if not partial and not tool_uses:
        return False
    try:
        store.append(
            assistant_text_message(partial, tool_uses or None, interrupted=True)
        )
    except Exception:  # noqa: BLE001
        return False
    return True


def _positive_int(value: object) -> int | None:
	try:
		number = int(value)  # type: ignore[arg-type]
	except (TypeError, ValueError):
		return None
	return number if number > 0 else None


# 上下文构成的稳定类别顺序（与前端预览一致）。
_CONTEXT_CATEGORIES: list[tuple[str, str]] = [
	("system", "System prompt"),
	("rules", "Rules"),
	("memory_behavior", "Memory behavior"),
	("tool_definitions", "Tool definitions"),
	("memory_index", "Memory index"),
	("summary", "Summarized conversation"),
	("conversation", "Conversation"),
]


def _memory_index_live_enabled() -> bool:
	"""Memory 索引常驻注入开关：**恒关**（2026-09-09 用户裁决维持下线）。

	事故 sess_mtiche8l（弱模型把索引条目当任务对象）后已退役，AGENTS「已下线」
	与此对齐。注入走 project_for_model 的 _append_memory_index 仍供脚本/评测用，
	生产投影层不推送；settings/env 残留一律忽略（同其他固化恒关项）。受控重开
	须源码级改此函数 + A1（200+ 轮 live）/ A3 过门证据。
	"""
	return False


def _content_chars(content: object) -> int:
	"""消息 content 的字符数（str 或 [{type,text}]）。"""
	if isinstance(content, str):
		return len(content)
	if isinstance(content, list):
		total = 0
		for block in content:
			if not isinstance(block, dict):
				continue
			txt = block.get("text") or block.get("content")
			if isinstance(txt, str):
				total += len(txt)
		return total
	return 0


def _projected_tokens(projected: list[dict]) -> int:
	"""投影 token 数。

	口径：``projectedTokens`` = 「下一个请求的提示词要花多少」，
	在提供方样本之上，加上自样本以来表层增减的启发式重计价，**压缩会立刻反映**。
	XEYO 用消息投影本身（已含 C0 截断 / C1 占位 / C2 摘要折叠）作为当前表层，逐消息
	按 token_len（≈4 字符/token）+ 每消息结构开销估算——即当前送模型投影的真实长度，
	任何压缩/截断都立即反映在分子里（不再像厂商 prompt_tokens 那样延迟一轮）。
	"""
	total = 0
	for msg in projected:
		# 结构开销（role / 块 envelope）
		total += 2
		if isinstance(msg, dict):
			role = str(msg.get("role") or "")
			if role:
				total += token_len(role) + 2
			total += token_len(json.dumps(msg.get("content"), ensure_ascii=False, default=str))
		else:
			total += token_len(str(getattr(msg, "content", "")))
	return max(0, total)


def _content_parts(content: object) -> tuple[int, int]:
	"""返回 (memory_index 字符数, 其余 conversation 字符数) 的粗略拆分。

	识别记忆索引块（以 ``# Memory index`` 开头的内容段）；其余算对话。
	"""
	if not isinstance(content, list):
		return 0, _content_chars(content)
	mem_chars = 0
	conv_chars = 0
	for block in content:
		if not isinstance(block, dict):
			continue
		txt = block.get("text") or block.get("content")
		if not isinstance(txt, str):
			continue
		if txt.lstrip().startswith("# Memory index"):
			mem_chars += len(txt)
		else:
			conv_chars += len(txt)
	return mem_chars, conv_chars


def _compute_category_chars(
	*,
	system_breakdown: list[dict] | None,
	system_text: str,
	tool_schemas_json: str | None,
	projected: list[dict],
) -> OrderedDict[str, int]:
	"""把本轮发送给模型的内容按类别统计字符数（仅用于相对占比，总量用厂商 usage）。
	"""
	chars: OrderedDict[str, int] = OrderedDict(
		(cat, 0) for cat, _label in _CONTEXT_CATEGORIES
	)
	# system 左段（来自 PromptAssembler 的逐段构成）
	if system_breakdown:
		assigned = 0
		for row in system_breakdown:
			cat = str(row.get("category") or "")
			if cat in chars:
				chars[cat] += int(row.get("chars") or 0)
				assigned += int(row.get("chars") or 0)
		# runtime budget notice 等额外追加内容归入 system
		extra = max(0, len(system_text) - assigned)
		chars["system"] += extra
	else:
		chars["system"] += len(system_text)
	# tool schemas（作为 tools 字段独立发送，不并入 system 文本）
	if tool_schemas_json:
		chars["tool_definitions"] += len(tool_schemas_json)
	# 消息历史：摘要块 / 记忆索引 / 对话
	for msg in projected:
		if not isinstance(msg, dict):
			continue
		if str(msg.get("name") or "") == "session_summary":
			chars["summary"] += _content_chars(msg.get("content"))
			continue
		mem_chars, conv_chars = _content_parts(msg.get("content"))
		chars["memory_index"] += mem_chars
		chars["conversation"] += conv_chars
	return chars


def _scale_breakdown(chars: OrderedDict[str, int], total_tokens: int) -> list[dict]:
	"""按厂商权威 prompt_tokens 作为总量，把各类别字符占比折成 token 数。

	最后一个非零类别吃下余数，保证 ``sum(tokens) == total_tokens``。
	"""
	denom = sum(chars.values())
	if total_tokens <= 0 or denom <= 0:
		return []
	lines = [(cat, label, chars.get(cat) or 0) for cat, label in _CONTEXT_CATEGORIES]
	lines = [(cat, label, c) for cat, label, c in lines if c > 0]
	if not lines:
		return []
	out: list[dict] = []
	remaining = total_tokens
	for idx, (cat, label, c) in enumerate(lines):
		if idx == len(lines) - 1:
			tok = remaining
		else:
			tok = round(total_tokens * c / denom)
		tok = max(0, tok)
		remaining -= tok
		out.append({"category": cat, "label": label, "tokens": tok, "chars": c})
	return out


_EXIT_PLAN_MODE_SCHEMA = {
	"name": "ExitPlanMode",
	"description": "退出 Plan 模式并开始按批准的计划实现",
	"input_schema": {
		"type": "object",
		"properties": {
			"plan": {"type": "string"},
		},
		"required": ["plan"],
	},
}

def _plan_tool_schemas(tools: "ToolRegistry", tool_schemas: list[dict]) -> list[dict]:
	out = [
		schema
		for schema in tool_schemas
		if tool_allowed_in_mode(
			str(schema.get("name") or ""),
			tool=tools.get(str(schema.get("name") or "")),
		)
	]
	if current_agent_mode() == "plan":
		out.append(_EXIT_PLAN_MODE_SCHEMA)
	return out

def _workspace_cwd_for_turn(tools: "ToolRegistry | None" = None) -> str:
	"""优先用会话工具 registry 的 cwd，其次模块级 get_cwd。"""
	if tools is not None:
		cwd = getattr(tools, "cwd", None)
		if isinstance(cwd, str) and cwd.strip():
			return cwd.strip()
	try:
		from engine.workspace_context import get_cwd

		return get_cwd() or ""
	except Exception:
		return ""


def _self_session_id() -> str:
	try:
		from engine.workspace_context import get_workspace_context

		ctx = get_workspace_context()
		if ctx is not None and ctx.session_id:
			return str(ctx.session_id).strip()
	except Exception:
		pass
	return ""


def _peer_remind_tool_message(tu: ToolUse) -> str:
	"""提醒：不执行工具，给模型可操作建议。"""
	name = (tu.name or "").strip() or "tool"
	inp = tu.input if isinstance(tu.input, dict) else {}
	cmd = str(inp.get("command") or "").strip()
	path = str(
		inp.get("file_path") or inp.get("path") or inp.get("notebook_path") or ""
	).strip()
	lines = [
		"Permission reminded (not executed): peer session conflict.",
		"Do not overwrite peer-owned files. Prefer waiting or editing only your paths.",
	]
	if name == "Bash" and cmd:
		lines.append(f"Blocked command: {cmd[:300]}")
		lines.append(
			"Suggestion: `git add <only-your-paths>` then commit, "
			"or re-Read peer files before editing."
		)
	elif path:
		lines.append(f"Blocked path: {path}")
		lines.append("Suggestion: Re-Read the file after the other session finishes.")
	return "\n".join(lines)


def _notify_peers_after_allow(tu: ToolUse, *, cwd: str) -> None:
	"""继续：执行后给对方会话排队 T_now。"""
	sid = _self_session_id()
	if not sid or not (cwd or "").strip():
		return
	try:
		from engine.session_presence import default_session_presence

		reg = default_session_presence()
		label = reg.display_title(sid)
		inp = tu.input if isinstance(tu.input, dict) else {}
		cmd = str(inp.get("command") or "").strip()
		path = str(
			inp.get("file_path") or inp.get("path") or inp.get("notebook_path") or ""
		).strip()
		if cmd:
			msg = f"会话「{label}」已继续执行: {cmd[:200]}"
		elif path:
			msg = f"会话「{label}」已继续写入: {path}"
		else:
			msg = f"会话「{label}」已继续执行冲突操作（{(tu.name or 'tool')}）"
		for peer in reg.peers(cwd, sid):
			reg.queue_notice(peer.session_id, msg)
	except Exception:
		pass


def _queue_peer_remind_notices(tu: ToolUse, *, cwd: str) -> None:
	"""提醒：双方下一轮 T_now 都挂一条。"""
	sid = _self_session_id()
	if not sid or not (cwd or "").strip():
		return
	try:
		from engine.session_presence import default_session_presence

		reg = default_session_presence()
		label = reg.display_title(sid)
		inp = tu.input if isinstance(tu.input, dict) else {}
		cmd = str(inp.get("command") or "").strip()
		path = str(
			inp.get("file_path") or inp.get("path") or inp.get("notebook_path") or ""
		).strip()
		detail = cmd[:200] if cmd else (path or (tu.name or "tool"))
		self_msg = f"已选择提醒：未执行冲突操作（{detail}）。请只改自己的路径。"
		peer_msg = f"会话「{label}」因交叉选择了提醒，未执行: {detail}"
		reg.queue_notice(sid, self_msg)
		for peer in reg.peers(cwd, sid):
			reg.queue_notice(peer.session_id, peer_msg)
	except Exception:
		pass


def _find_exit_plan_use(tool_uses: list[ToolUse]) -> ToolUse | None:
	for tu in tool_uses:
		if (tu.name or "").strip() == "ExitPlanMode":
			return tu
	return None


def _attach_turn_context(
	projected: list[dict],
	*,
	approved_plan: str | None,
	forced_wrap_up: bool,
	runtime_notice: str | None,
	include_memory_index: bool = True,
	inject_instructions: bool | None = None,
	multi_agent: bool = False,
	working: WorkingSnapshot | None = None,
	workspace_cwd: str = "",
	cwd: str = "",
	subagent: bool = False,
	plan_pointer: bool = False,
	t_now_strategy: str = "",
	budget: object | None = None,
	loop_ledger: object | None = None,
) -> list[dict]:
	"""薄封装：委托 ``prompt.pre_llm_inject.run_pre_llm_inject``。

	``cwd`` / ``workspace_cwd`` 等价（优先 cwd）；缺省空串则跳过 Nested/Stale。
	``inject_instructions``：None 时跟随 ``include_memory_index``。
	``subagent``：T14 净化清单——子代理上下文跳过 peer/冲突/预览等易变块。
	``t_now_strategy``：声道策略（env_channel/legacy）；空串跟随全局解析。
	``budget``：BudgetTracker（禀赋①预算镜像数据源）；None 则零注入。
	"""
	from prompt.pre_llm_inject import (
		InjectContext,
		run_pre_llm_inject,
	)

	root = (cwd or workspace_cwd or "").strip()
	session_id = ""
	try:
		from engine.workspace_context import get_workspace_context

		ctx = get_workspace_context()
		if ctx is not None and ctx.session_id:
			session_id = str(ctx.session_id).strip()
	except Exception:
		session_id = ""
	# T9：T_now Goal 块——仅 blocked / pending_complete 注入（active 常态静默）；子代理不注入。
	goal_block = ""
	if not subagent and root.strip() and session_id.strip():
		try:
			from engine.goal_state import STATUS_BLOCKED, GoalStore

			g = GoalStore(root).current(session_id)
			if g is not None and (g.status == STATUS_BLOCKED or g.pending_complete):
				status = "已阻塞" if g.status == STATUS_BLOCKED else "待确认完成"
				goal_block = (
					"# Goal（background only）\n"
					f"目标：{g.text or g.title}\n"
					f"状态：{status}"
				)
				if len(goal_block) > 1200:
					goal_block = goal_block[:1200]
		except Exception:
			goal_block = ""
	return run_pre_llm_inject(
		projected,
		InjectContext(
			working=working,
			cwd=root,
			budget=budget,
			approved_plan=approved_plan,
			forced_wrap_up=forced_wrap_up,
			runtime_notice=runtime_notice,
			include_memory_index=include_memory_index,
			inject_instructions=inject_instructions,
			multi_agent=multi_agent,
			session_id=session_id,
			subagent=subagent,
			goal=goal_block,
			plan_pointer=plan_pointer,
			strategy=t_now_strategy,
			loop_ledger=loop_ledger,
		),
	)

def _append_skipped_tool_results(
	store: MessageStore,
	tool_uses: list[ToolUse],
	exit_use_id: str,
	reason: str,
) -> None:
	for tu in tool_uses:
		if tu.id == exit_use_id:
			continue
		store.append(
			tool_result_message(
				tu.id,
				tu.name,
				f"[{reason}] tool was not executed",
				is_error=True,
			)
		)


async def query_loop(
	*,
	store: MessageStore,
	model: ModelClient,
	tools: ToolRegistry,
	prompt: PromptAssembler,
	system_prompt: str,
	abort: AbortController,
	budget: BudgetTracker,
	working: WorkingSnapshot | None = None,
	coordinator: PermissionCoordinator | None = None,
	system_breakdown: list[dict] | None = None,
	agent_mode: str = "agent",
	multi_agent: bool = False,
	include_memory_index: bool = True,
	ensure_before: Any | None = None,
) -> AsyncIterator[EngineEvent]:
    """Run the model/tool loop and emit authoritative vendor usage events.

    ``ensure_before``：可选 awaitable/callable。首个非只读工具执行前会 await，
    用于让 rewind Before 快照与首轮 stream 重叠，写工具仍不得越过未就绪的 Before。

    ``multi_agent``：Composer chip。True 时在 T_now 追加软提示，偏向使用 Agent；
    不裁剪工具表、不拦截收尾。关闭时 Agent 工具仍可用，模型可主动 spawn。

    ``include_memory_index``：是否在 T_now 挂 Memory 索引。子 Agent 应传 False，
    避免工人提示词被索引撑大、也避免误答 Memory。
    """
    snap = working if working is not None else WorkingSnapshot()
    set_agent_mode(agent_mode)
    # T：审批模式活状态 —— turn 边界拍基线（收紧即时/放宽延后）并复位广播。
    # 仅当会话有 coordinator（真实会话）时执行；本地/无会话路径跳过。
    try:
        _perm_sid = (
            coordinator.session_id if coordinator is not None else ""
        ) or _self_session_id()
        if _perm_sid:
            begin_permission_turn(_perm_sid)
    except Exception:
        pass
    approved_plan: str | None = None
    # 首写收敛后：全量计划静默，切换为"实施中"指针块（正文已进紧邻历史）。
    plan_pointer = False
    # 投影增量缓存挂 WorkingSnapshot（跨 submit）；C1/C2 推进时 note_* 会清掉。
    # (tool_schemas, 其 JSON 序列化)；schemas 内容会话内不变，避免每轮 dumps。
    schemas_json_cache: tuple[list[dict], str] | None = None
    # 重复调用守卫（T6 递进建议制：阈值 [3,5,8]，只提醒不拒执行；
    # 每次 submit 新建即用户输入级重置）。
    repeat_guard = RepeatCallGuard()
    clear_advice()  # 轮首清残留提醒，T_now 块只反映本轮状态
    # R2'：同签名·同输出字节级折叠（结果写入 store 前替换为一行 [fold] 事实；
    # 每 submit 新建 → 与 repeat_guard 同步的用户输入级重置）。
    result_fold = IdenticalResultFold()
    # 行为账本（循环信号计数器：s1 结果等价 / s2 内容已见 / s3 首句重复）；
    # 豁免集与 RepeatCallGuard 同源；经 InjectContext 供 pre_llm_inject 直读。
    loop_ledger = LoopLedger(exempt_tools=frozenset(EXEMPT_TOOLS))
    # 循环熔断（铁律 #3 的执行层形态：无进展路径持续报错，永不静默）。
    # L1 同签名连续 / L2 周期重复 / L3 同签名同结果 / L4 同工具无新内容；
    # 命中即该次调用不执行，回一条中性结果型 ToolResult（不写 store 历史）。
    # 与 repeat_guard / result_fold 同步：每 submit 新建即用户输入级重置。
    loop_breaker = LoopBreaker(exempt=frozenset(EXEMPT_TOOLS))
    # 零命中前提复核：不同查询累计空结果 ≥2 起追加中立提示。
    zero_hit_tracker = ZeroHitTracker()
    # tu.id → 该调用结果上要追加的零命中提示文本。
    zero_hit_advice: dict[str, str] = {}
    # max_turns / max_tool_calling 硬停前的一次性收尾放行：配额内工具仍可用
    # （R3'：不再"一开闸全禁"——收尾恰好最需要落盘；配额尽才禁，文本引导
    # 收敛）。forced_wrap_up=True 表示已进入收尾窗；wrap_quota_left 是剩余
    # 可调用次数（XEYO_WRAP_QUOTA 覆盖，默认 3；0=维持旧的全禁语义）。
    forced_wrap_up = False
    wrap_quota_left = wrap_quota_from_env()
    turn_reasoning_parts: list[str] = []
    # 配对修复只在 submit 入口（及 abort 路径的 _fill_missing）做一次，
    # 不在每轮模型请求前全量扫 store。
    _repair_unpaired_tool_calls(store, "aborted")
    while True:
        if abort.aborted:
            yield StoppedEvent(reason="aborted")
            return
        if not budget.prepare_next_turn():
            if forced_wrap_up:
                # 收尾调用也已消耗，仍无文本可交付 → 维持原硬停语义。
                yield StoppedEvent(reason=budget.hard_stop_reason or "max_turns")
                return
            forced_wrap_up = True
            # R3'：进收尾窗时发布缺口清单 + 剩余配额（T_now wrap_up 块消费）。
            try:
                _publish_wrap_guide(
                    tools, _workspace_cwd_for_turn(tools), wrap_quota_left
                )
            except Exception:  # noqa: BLE001 — 引导增强失败不影响 wrap 主路径
                pass
        runtime_notice = budget.consume_runtime_notice()
        # 收尾窗广播（工具层只读信号）：窗口内长命令后台化，把窗口留给落盘。
        # 每轮刷新 → 剩余墙钟变化可被工具层看到；未进入窗口时广播 inactive。
        try:
            from engine.wrap_window import set_wrap_window

            set_wrap_window(forced_wrap_up, budget.wall_remaining_s())
        except Exception:  # noqa: BLE001 — 广播失败不影响主路径
            pass
        # system 左段保持稳定；Ask/Plan/计划/预算/wrap-up/MEMORY index 挂 T_now。
        budget.begin_turn()

        remaining = max(
            1,
            budget.max_turns + budget.grace_turns_remaining - budget.turn_count,
        )

        compact_cursor_before = snap.compact_cursor
        # T8：每轮先清空预取槽（防跨轮脏数据），再按开关决定是否异步预取。
        # C2 LLM 摘要旁路（默认关）：仅首压前（compact_cursor==0 且会话足够长）
        # 重放前缀打 warm cache，结果存进 snap._pending_c2_summary，供
        # apply_c2_messages 同步消费（失败/未启用 → 置空回退确定性摘要）。
        snap._pending_c2_summary = None
        if (
            c2_llm_summary_enabled()
            and int(snap.compact_cursor or 0) == 0
            and model is not None
            and len(store) >= _C2_LLM_PREFETCH_MIN_MESSAGES
        ):
            try:
                await prefetch_c2_summary(
                    snap, store.as_api_messages(), system_prompt, model, abort
                )
            except Exception:
                snap._pending_c2_summary = None
        # 厂商上下文达 95%（可用 XEYO_CONTEXT_COMPACT_RATIO）→ 强制 C2，避免 1261
        pressure_limit = _positive_int(getattr(model, "context_limit", None))
        if maybe_force_compact_on_pressure(
            store.as_api_messages(),
            snap,
            context_limit=pressure_limit,
            remaining_turns=remaining,
            system_prompt=system_prompt,
        ):
            snap.proj_cache = None
        summary_fp = len(snap.c2_summary_text or "")
        frozen = snap.c1_frozen_until
        cur_len = len(store)
        # 增量缓存：
        # - gate 关：整段 project 前缀可复用（旧行为）
        # - gate 开但已压缩：左段摘要冻结，只增量投影 cursor 右侧尾部
        # γ4 围栏写进 proj_cache（不进 MessageStore）：增量只围栏新段，
        # 命中缓存时不再全历史扫 fences。
        from prompt.fence import apply_tool_output_fences

        use_proj_cache = l5_mode() == "project" and (
            (not c2_gate()) or int(snap.compact_cursor or 0) > 0
        )
        # 缓存命中路径会跳过 project_for_model（其内部才推进 aging/C1）；
        # 在走缓存前显式跑一次老化决策。推进时 note_c1 会把 proj_cache 置
        # None，下面的命中检查自然失败、回落全量投影——不会投影错位。
        if use_proj_cache:
            try:
                from memory.runtime import maybe_advance_aging_boundary

                maybe_advance_aging_boundary(store.as_api_messages(), snap)
                frozen = snap.c1_frozen_until
            except Exception:
                pass
        proj_cache = snap.proj_cache
        if (
            use_proj_cache
            and proj_cache is not None
            and proj_cache[1] == frozen
            and proj_cache[2] == int(snap.compact_cursor or 0)
            and proj_cache[3] == summary_fp
            and cur_len >= proj_cache[0]
        ):
            base_len, _bf, cursor, _sfp, base_proj, base_names = proj_cache
            if cur_len == base_len:
                projected = base_proj
            else:
                api_all = store.as_api_messages()
                new_msgs = api_all[base_len:]
                if cursor > 0:
                    frozen_rel = max(0, frozen - cursor)
                    new_proj, names = project_incremental(
                        new_msgs,
                        base_len=base_len - cursor,
                        frozen_until=frozen_rel,
                        id_to_name=base_names,
                    )
                else:
                    new_proj, names = project_incremental(
                        new_msgs,
                        base_len=base_len,
                        frozen_until=frozen,
                        id_to_name=base_names,
                    )
                new_proj = apply_tool_output_fences(new_proj, id_to_name=names)
                projected = base_proj + new_proj
                snap.proj_cache = (
                    cur_len,
                    frozen,
                    cursor,
                    summary_fp,
                    projected,
                    names,
                )
        else:
            api_all = store.as_api_messages()
            projected = project_for_model(
                api_all,
                snap,
                remaining_turns=remaining,
                system_prompt=system_prompt,
                include_memory_index=_memory_index_live_enabled(),
                # 真实模型窗口（route capacity）——Path A 压力门据此推导，修复
                # 「C2 误以为窗口只有 128k」：主流模型已 1M，但 params.window_tokens 恒 128k。
                context_limit=_positive_int(getattr(model, "context_limit", None)),
            )
            names = build_tool_use_names(api_all)
            projected = apply_tool_output_fences(projected, id_to_name=names)
            if use_proj_cache:
                snap.proj_cache = (
                    cur_len,
                    snap.c1_frozen_until,
                    int(snap.compact_cursor or 0),
                    len(snap.c2_summary_text or ""),
                    projected,
                    names,
                )
            else:
                snap.proj_cache = None
        # 侧聊（side）模式：T_now 不挂 workspace 派生内容（Nested XEYO / stale
        # 提醒 / Memory 索引），cwd 传空即由 pre_llm_inject 统一跳过。
        from permissions.policy import side_mode as _side_mode
        from permissions.policy import in_subagent as _in_subagent

        _is_side = _side_mode()
        # T_now 声道（方案A）：env_channel 默认；模型被运行时标记不支持伪造
        # tool 对时 resolve 回 skip（L2：宁缺毋滥，不落 legacy 用户尾插）。
        from prompt.t_now_strategy import (
            ENV_FALLBACK_STATUS,
            STRATEGY_SKIP,
            env_unsupported_key,
            mark_env_channel_unsupported,
            resolve_t_now_strategy,
        )

        t_now_strat = resolve_t_now_strategy(
            _llm_provider_name(model), _llm_model_name(model)
        )
        _inject_kwargs: dict = dict(
            approved_plan=approved_plan,
            forced_wrap_up=forced_wrap_up,
            runtime_notice=runtime_notice,
            include_memory_index=include_memory_index and not _is_side,
            multi_agent=multi_agent,
            working=snap,
            cwd="" if _is_side else _workspace_cwd_for_turn(tools),
            subagent=_in_subagent(),
            plan_pointer=plan_pointer,
            budget=budget,
            loop_ledger=loop_ledger,
        )
        projected_pre_inject = projected
        # #8 首轮嗅探：会话第一轮（历史无 assistant）注入有界 pwd+ls 清单，
        # 零 LLM 调用、投影-only（env 声道对）、side/子代理/开关关闭时跳过。
        if not _is_side and not _in_subagent():
            try:
                from engine.first_sniff import maybe_first_sniff_text

                sniff_text = maybe_first_sniff_text(
                    projected,
                    "" if _is_side else _workspace_cwd_for_turn(tools),
                    subagent=_in_subagent(),
                    side=_is_side,
                )
                if sniff_text:
                    from prompt.turn_context import append_env_notice_pair

                    projected = append_env_notice_pair(projected, sniff_text)
            except Exception:  # noqa: BLE001 — 嗅探失败绝不影响主请求
                pass
        projected = _attach_turn_context(
            projected,
            t_now_strategy=t_now_strat,
            **_inject_kwargs,
        )
        api_messages = prompt.build(system_prompt, projected)

        tool_schemas = _plan_tool_schemas(tools, tools.schemas())
        # 收尾请求（forced_wrap_up）同样保留 tools 数组：DeepSeek 把工具定义渲染在
        # prompt 最前端，若在最后一枪摘掉 tools，整个请求前缀会从工具段起错位重哈希，
        # 导致该枪缓存命中率坍缩到仅 system 段（观测上一枪 90%+ → 6%），白付一次
        # 26k~36k token 的全量 miss（miss 价 ≈ hit×30）。"模型仍可能调工具"由
        # _admit_tool_use 的 wrap 配额(配额内放行/配额尽才拒) + _fill_missing 兜底。
        # schemas 会话内只读：JSON 序列化缓存，避免每轮重复 dumps。
        if schemas_json_cache is not None and schemas_json_cache[0] == tool_schemas:
            tool_schemas_json = schemas_json_cache[1]
        else:
            tool_schemas_json = json.dumps(
                tool_schemas, ensure_ascii=False, separators=(",", ":")
            )
            schemas_json_cache = (tool_schemas, tool_schemas_json)
        compression_started = snap.compact_cursor > compact_cursor_before
        if compression_started:
            yield ContextCompressionEvent(phase="start", source="automatic")

        narration_gate = StreamNarrationGate()
        tool_uses: list[ToolUse] = []
        early: dict[str, asyncio.Task[ToolResult]] = {}
        seen_tool_ids: set[str] = set()
        do_early = early_readonly_tools_enabled()
        turn_reasoning_parts = []
        # stream 期间即可 yield / 占配额 / early；progress 与 result 队列提前建好。
        wake = asyncio.Event()

        class _NotifyQueue(asyncio.Queue):  # type: ignore[type-arg]
            def put_nowait(self, item: Any) -> None:  # noqa: ANN401
                super().put_nowait(item)
                wake.set()

        progress_q: asyncio.Queue[ToolProgressEvent] = _NotifyQueue()
        result_q: asyncio.Queue[tuple[ToolUse, ToolResult]] = _NotifyQueue()
        results_by_id: dict[str, ToolResult] = {}
        quota_held: set[str] = set()
        emitted_calls: set[str] = set()
        from engine.xml_tool_call import XmlToolCallBuffer

        xml_buf = XmlToolCallBuffer()
        xml_recovered = False

        def _admit_tool_use(tu: ToolUse) -> list[EngineEvent]:
            """占配额 + yield ToolCall；只读可 early。返回待 yield 事件。"""
            nonlocal wrap_quota_left
            events: list[EngineEvent] = []
            if tu.id in seen_tool_ids:
                return events
            seen_tool_ids.add(tu.id)
            narration_gate.on_tool_use()
            tool_uses.append(tu)
            if forced_wrap_up:
                if wrap_quota_left <= 0:
                    results_by_id[tu.id] = ToolResult(
                        content="[wrap_up] wrap quota exhausted; "
                        "tools are disabled for this final answer",
                        is_error=True,
                        metadata={"wrap_up_rejected": True},
                    )
                    return events
                # R3'：收尾窗配额内放行——不再一开闸全禁。配额内的调用仍按
                # 只读/并发规则评估执行，但绕过 budget 的 tool-cap 拒绝（该闸
                # 的用途是防失控循环，收尾配额由引擎计数封顶，双闸语义重叠）。
                wrap_quota_left -= 1
            guard_action = safe_observe(
                repeat_guard.observe, tu.name, tu.input,
                label="RepeatCallGuard.observe",
            )
            # T6：ACTION_ADVICE 不改写 ToolResult——提醒经 T_now
            # （pre_llm_inject 的 Repeat guard 块）在下一轮模型请求前注入。
            _ = guard_action
            # 循环熔断：命中即该次调用不执行（也不占 tool-call 配额），回中性
            # 结果型 ToolResult；同签名再来一次仍会命中（永不静默）。判定失败
            # fail-open 放行（safe_observe 记 debug，不静默吞）。
            loop_refusal = safe_observe(
                loop_breaker.admit,
                tu.name,
                tu.input,
                label="LoopBreaker.admit",
            )
            if loop_refusal is not None:
                results_by_id[tu.id] = ToolResult(
                    content=loop_refusal.text,
                    is_error=True,
                    metadata=loop_refusal.metadata(),
                )
                return events
            # R3'：收尾窗配额内的调用由引擎配额计数封顶，跳过 budget 的
            # tool-cap 拒绝（该闸防失控循环，wrap 配额与其语义重叠）。
            if not forced_wrap_up and not budget.begin_tool_call():
                results_by_id[tu.id] = ToolResult(
                    content="[max_tool_calling reached; tool call was not executed]",
                    is_error=True,
                    metadata={"budget_rejected": True},
                )
                return events
            quota_held.add(tu.id)
            events.append(
                ToolCallEvent(
                    name=tu.name,
                    input=tu.input,
                    tool_use_id=tu.id,
                    # T13：tool_call.begin 元数据——参数摘要 + 是否同批并行。
                    input_summary=_tool_input_summary(tu.input),
                    parallel=len(tool_uses) > 1,
                )
            )
            emitted_calls.add(tu.id)
            # T4：副作用工具执行前，携带该 tool_use 的 assistant 行必须已在盘上
            # （崩溃后恢复才判定 OUTCOME_UNKNOWN 而非凭空 400）。失败则跳过——
            # fail-closed：宁可恢复时欠一条结果，也不得让无 tool_use 的裸结果落盘。
            if not is_concurrency_safe(tools, tu.name):
                _safe_flush_transcript()
            if do_early and _eligible_for_early(
                tools,
                tu,
                forced_wrap_up=forced_wrap_up,
            ):
                early[tu.id] = asyncio.create_task(
                    _run_one_tool(
                        tools,
                        tu,
                        abort,
                        coordinator=None,
                        progress_q=progress_q,
                        result_q=result_q,
                    )
                )
            return events

        # T4：模型请求前强制刷 transcript——上一轮 tool_result 必须先落盘，
        # 崩溃恢复时 hydrate 合成（TOOL_NOT_STARTED/OUTCOME_UNKNOWN）才有边界。
        _safe_flush_transcript()
        # 44 号：LLM 失败语义协议化——可重试错误（请求还未产出 chunk / 空响应）
        # 在同 turn 内重建同一请求重试（assistant 消息只在流结束后落盘，=
        # 「失败 chunk 永不进史」，重试安全）。已产出 chunk 的尝试不原地重试
        # （会向 GUI 重复吐字），直接失败收敛由上层错误路径收尾。
        # B0.5：每个逻辑模型调用一个 request_id，跨 attempt 不变（dsh S2/S4
        # 归因 + 重试可观测）；attempt 递增区分第几次尝试。
        call_request_id = uuid.uuid4().hex[:16]
        attempt = 0
        while True:
            attempt += 1
            # B0.5：每次尝试前注入记账 meta（model._meta_*），保持 stream() 接口
            # 不变 —— 对测试 fake / 其它模型实现零侵入。request_id 跨 attempt
            # 不变（归并同一次逻辑调用的重试），attempt 递增区分第几次尝试。
            model._meta_request_id = call_request_id
            model._meta_attempt = attempt
            model._meta_kind = "turn"
            saw_any = False
            failure: Any = None
            failure_message = ""
            failure_status: int | None = None
            pending_exc: BaseException | None = None
            try:
                async for chunk in model.stream(api_messages, tool_schemas, abort):
                    abort.raise_if_aborted()
                    saw_any = True
                    if chunk.kind == "text_delta":
                        for tu in xml_buf.feed(chunk.text):
                            xml_recovered = True
                            for ev in _admit_tool_use(tu):
                                yield ev
                        for piece in narration_gate.on_delta(chunk.text):
                            yield AssistantDelta(text=piece)
                    elif chunk.kind == "reasoning_delta":
                        if chunk.text:
                            turn_reasoning_parts.append(chunk.text)
                        yield ReasoningDelta(text=chunk.text)
                    elif chunk.kind == "tool_use" and chunk.tool_use is not None:
                        for ev in _admit_tool_use(chunk.tool_use):
                            yield ev
                if saw_any:
                    break
                # 44 号：流正常结束但零 chunk = EMPTY_RESPONSE（默认可重试）。
                failure = empty_response_failure()
                failure_message = "模型返回了空响应"
            except Aborted:
                await _cancel_early_tasks(early)
                # smoke-test #4：用户停止/中断时若厂商 usage 尾帧(include_usage)已
                # 在中断前到达,补发用量事件——否则该回合的 token/缓存命中在
                # GUI 与用量账本中整体缺失（"缓存命中有点异常,消耗记录对不上"）。
                # 客户端流在每次 stream() 开始时置空 last_usage,非 None 即本次流
                # 已取得真实 usage;本回合的用量尾(1119 行 emit)尚未执行,不会重复。
                _ab_usage = getattr(model, "last_usage", None)
                if isinstance(_ab_usage, dict):
                    budget.add_usage(_ab_usage)
                    _ah, _am, _ao = split_usage(_ab_usage)
                    yield UsageEvent(
                        prompt_tokens=_ah + _am,
                        completion_tokens=_ao,
                        cache_hit_tokens=_ah,
                        cache_miss_tokens=_am,
                        tokens=budget.last_usage_tokens,
                        used_tokens=budget.used_tokens,
                        usd=round(budget.last_usage_usd, 8),
                        used_usd=round(budget.used_usd, 8),
                        cny=round(budget.last_usage_cny, 8),
                        used_cny=round(budget.used_cny, 8),
                        cost_source=budget.last_cost_source,
                        usd_limit=budget.usd_limit,
                        context_tokens=_positive_int(
                            getattr(model, "last_context_tokens", None)
                        )
                        or _ah + _am,
                        context_limit=_positive_int(
                            getattr(model, "context_limit", None)
                        ),
                        context_breakdown=None,
                        compact_cursor=int(snap.compact_cursor or 0),
                        last_action=str(snap.last_action or ""),
                        c2_summary_chars=0,
                    )
                # 44 号：中断锚——已吐给 GUI 的部分输出必须入史（刷新/重放可见）。
                interrupted = _persist_interrupted_anchor(
                    store, narration_gate, tool_uses
                )
                yield StoppedEvent(reason="aborted", interrupted=interrupted)
                return
            except ProviderError as exc:
                # L2（2026-09-09）：env_channel 下、未吐任何 chunk 的结构类 4xx
                # （400/404/413/415/422 等），视为该模型/网关不接受伪造 tool 对
                # ——记进程级备忘，**本轮跳过 T_now 注入**（不再落回 legacy 用户
                # 尾插：引擎文本进用户角色=说话人混淆源；宁缺毋滥，执行层硬约束
                # 兜底）。非结构错误（402 欠费 / 429 限流 / 5xx）不回退。
                if (
                    t_now_strat == "env_channel"
                    and not saw_any
                    and exc.status_code in ENV_FALLBACK_STATUS
                ):
                    _fb_prov = _llm_provider_name(model)
                    _fb_model = _llm_model_name(model)
                    mark_env_channel_unsupported(env_unsupported_key(_fb_prov, _fb_model))
                    t_now_strat = STRATEGY_SKIP
                    projected = _attach_turn_context(
                        projected_pre_inject,
                        t_now_strategy=t_now_strat,
                        **_inject_kwargs,
                    )
                    api_messages = prompt.build(system_prompt, projected)
                    logging.getLogger(__name__).warning(
                        "T_now env_channel rejected (status=%s, provider=%s, "
                        "model=%s)；本轮跳过 T_now 注入（L2，不再 legacy 尾插）。",
                        exc.status_code,
                        _fb_prov,
                        _fb_model,
                    )
                    continue
                pending_exc = exc
                failure = classify_llm_failure(exc)
                failure_message = friendly_error(exc)
                failure_status = exc.status_code
            except OSError as exc:
                pending_exc = exc
                failure = classify_llm_failure(exc)
                failure_message = friendly_error(exc)
                failure_status = None
            if not (failure.retryable and not saw_any and attempt < _llm_max_attempts()):
                if failure.code == "empty_response":
                    raise EmptyResponseError() from None
                raise pending_exc
            delay_ms = _llm_retry_delay_ms(attempt, failure.retry_after_ms)
            _audit_llm_failure(
                failure.code,
                attempt=attempt,
                status=failure_status,
                provider=_llm_provider_name(model),
                model_name=_llm_model_name(model),
            )
            yield LlmRetryEvent(
                attempt=attempt,
                next_retry_ms=delay_ms,
                code=failure.code,
                message=failure_message,
                provider=_llm_provider_name(model),
                model=_llm_model_name(model),
            )
            await asyncio.sleep(delay_ms / 1000)
            yield LlmRetryStartedEvent(
                attempt=attempt + 1,
                provider=_llm_provider_name(model),
                model=_llm_model_name(model),
            )

        usage = getattr(model, "last_usage", None)
        hit, miss, out = split_usage(usage) if isinstance(usage, dict) else (0, 0, 0)
        # 分子口径（窗口占用）：厂商权威 prompt_tokens 优先——它含 system prompt 与
        # tool schemas，是真实输入。投影估算（_projected_tokens）只做兜底：它不含
        # system/tools，且字节/4 启发式对中文偏小，做分子会系统性低估占用。
        # 厂商 usage 缺失时回退投影（压缩立即反映）→ 再回退 hit+miss。
        vendor_context = _positive_int(getattr(model, "last_context_tokens", None))
        if vendor_context is not None:
            context_tokens = vendor_context
        else:
            projected_tokens = _projected_tokens(projected)
            context_tokens = projected_tokens if projected_tokens > 0 else None
        if context_tokens is None and hit + miss > 0:
            context_tokens = hit + miss
        context_limit = _positive_int(getattr(model, "context_limit", None))
        category_chars = _compute_category_chars(
            system_breakdown=system_breakdown,
            system_text=system_prompt,
            tool_schemas_json=tool_schemas_json,
            projected=projected,
        )
        context_breakdown = _scale_breakdown(
            category_chars, context_tokens if context_tokens is not None else 0
        )
        # Rules soft_over 标记从组装 breakdown 透传
        if system_breakdown and context_breakdown:
            soft_over = any(
                str(r.get("category")) == "rules" and r.get("soft_over")
                for r in system_breakdown
            )
            if soft_over:
                for row in context_breakdown:
                    if row.get("category") == "rules":
                        row["soft_over"] = True
        note_shot(snap, hit=hit, prompt=hit + miss, at=datetime.now())
        # observe_shot：dumps 全投影 + 落盘；丢到后台与后续收尾/工具重叠，
        # 离开本回合前 await（下一轮 Ĥ / LCP 依赖 last_x_sent）。
        def _observe_body() -> None:
            from memory.observe import observe_shot

            # 观测侧一律经 safe_observe 隔离（2026-09-14 事故的结构性防线）：
            # Ĥ / LCP 采样失败只落 debug 日志，绝不进主链路、绝不与防护共 try。
            safe_observe(
                observe_shot,
                snap,
                projected,
                hit=hit,
                miss=miss,
                out=out,
                context_tokens=context_tokens,
                turn=budget.turn_count,
                provider=getattr(model, "provider", None),
                model=getattr(model, "_model", None) or getattr(model, "model", None),
                label="memory.observe.observe_shot",
            )

        _observe_task = asyncio.create_task(asyncio.to_thread(_observe_body))

        async def _await_observe() -> None:
            try:
                await _observe_task
            except Exception:  # noqa: BLE001 — 观测任务失败只留痕
                logging.getLogger(__name__).debug(
                    "observe shot task failed", exc_info=True
                )

        budget.add_usage(usage)
        # 循环熔断取证：本回 token 归到该轮前最后一次放行的签名上（只记录，
        # 不驱动判据——按签名归属的占比会误伤整回合 bash 密集的正常工作）。
        safe_observe(
            loop_breaker.note_turn_tokens,
            budget.last_usage_tokens,
            label="LoopBreaker.note_turn_tokens",
        )
        if budget.last_usage is not None:
            yield UsageEvent(
                prompt_tokens=hit + miss,
                completion_tokens=out,
                cache_hit_tokens=hit,
                cache_miss_tokens=miss,
                tokens=budget.last_usage_tokens,
                used_tokens=budget.used_tokens,
                usd=round(budget.last_usage_usd, 8),
                used_usd=round(budget.used_usd, 8),
                cny=round(budget.last_usage_cny, 8),
                used_cny=round(budget.used_cny, 8),
                cost_source=budget.last_cost_source,
                usd_limit=budget.usd_limit,
                context_tokens=context_tokens,
                context_limit=context_limit,
                context_breakdown=context_breakdown or None,
                compact_cursor=int(snap.compact_cursor or 0),
                last_action=str(snap.last_action or ""),
                c2_summary_chars=len(snap.c2_summary_text or ""),
            )
        if compression_started:
            yield ContextCompressionEvent(
                phase="complete",
                source="automatic",
                context_tokens=context_tokens,
                context_limit=context_limit,
            )
        if budget.over_budget:
            await _cancel_early_tasks(early)
            await _await_observe()
            yield StoppedEvent(
                reason="budget_usd",
                budget_used_usd=round(budget.used_usd, 8),
                budget_limit_usd=budget.usd_limit,
            )
            return

        assistant_text, flush_deltas = narration_gate.finish(has_tools=bool(tool_uses))
        # 部分厂商（如 glm）会把 tool_call 写成 XML 纯文本而非 native tool_calls。
        # 流式路径已在 </tool_call> 闭合时回收；此处兜底整段未闭合/漏网。
        if not tool_uses:
            from engine.xml_tool_call import extract_xml_tool_calls
            from engine.process_narration import split_process_narration

            recovered, cleaned = extract_xml_tool_calls(assistant_text)
            if recovered:
                xml_recovered = True
                for tu in recovered:
                    for ev in _admit_tool_use(tu):
                        yield ev
                assistant_text, _xml_narr = split_process_narration(cleaned)
                flush_deltas = []
        elif xml_recovered:
            from engine.xml_tool_call import extract_xml_tool_calls
            from engine.process_narration import split_process_narration

            _ignored, cleaned = extract_xml_tool_calls(assistant_text)
            assistant_text, _xml_narr = split_process_narration(cleaned)
            flush_deltas = []
        for piece in flush_deltas:
            if piece:
                yield AssistantDelta(text=piece)
        # T28：过程旁白不再从 transcript 剥除——随消息留档（background only），
        # 投影送模型时忽略，仅供「当时为何动手」追溯与刷新后回看。
        narration = narration_gate.drain_narration()
        # 行为账本：s3 首句重复信号采集（在写入 store 前登记本轮输出）。
        safe_observe(
            loop_ledger.observe_assistant, assistant_text,
            label="LoopLedger.observe_assistant",
        )
        store.append(
            assistant_text_message(
                assistant_text,
                tool_uses or None,
                narration=narration,
                reasoning="".join(turn_reasoning_parts),
            )
        )

        if forced_wrap_up:
            # 空工具列表下正常不应出现 tool_use；万一厂商仍吐出，就补确定性
            # 错误行保持配对完整。收尾有任何文本则以 FinalEvent 交付；完全无
            # 文本（如假模型/异常空响应）则回退原硬停语义，保持既有契约。
            await _cancel_early_tasks(early)
            if tool_uses:
                _fill_missing_tool_results(store, tool_uses, "wrap_up")
            final_text = assistant_text.strip()
            if not final_text:
                await _await_observe()
                yield StoppedEvent(reason=budget.hard_stop_reason or "max_turns")
                return
            await _await_observe()
            yield FinalEvent(
                text=final_text,
                prompt_tokens=hit + miss,
                completion_tokens=out,
                cache_hit_tokens=hit,
                cache_miss_tokens=miss,
                usd=round(budget.last_usage_usd, 8),
                used_usd=round(budget.used_usd, 8),
                usd_limit=budget.usd_limit,
            )
            return

        exit_plan_use = _find_exit_plan_use(tool_uses)
        if current_agent_mode() == "plan" and exit_plan_use is not None:
            # 计划闸路径：其它工具一律跳过，取消已投机的 early 任务
            await _cancel_early_tasks(early)
            raw_plan_input = (
                exit_plan_use.input
                if isinstance(exit_plan_use.input, dict)
                else {}
            )
            raw_plan = raw_plan_input.get("plan")
            plan_text = (
                str(raw_plan).strip()
                if isinstance(raw_plan, str)
                else ""
            ) or assistant_text.strip()
            if not plan_text:
                _append_skipped_tool_results(store, tool_uses, exit_plan_use.id, "plan_rejected")
                store.append(
                    tool_result_message(
                        exit_plan_use.id,
                        "ExitPlanMode",
                        "ExitPlanMode requires a plan",
                        is_error=True,
                    )
                )
                await _await_observe()
                yield FinalEvent(text="ExitPlanMode requires a plan.")
                return

            plan_engine = default_plan_engine()
            session_id = coordinator.session_id if coordinator is not None else "local"
            turn_id = coordinator.turn_id if coordinator is not None else uuid.uuid4().hex[:12]
            pending = plan_engine.create(
                session_id=session_id,
                turn_id=turn_id,
                plan=plan_text,
                request_id=turn_id,
            )
            yield PlanPendingEvent(
                request_id=pending.request_id,
                session_id=pending.session_id,
                turn_id=pending.turn_id,
                plan=pending.plan,
                expires_at=pending.expires_at,
            )
            resolved = await plan_engine.wait(pending.request_id)
            approved = bool(resolved and resolved.approved)
            actor = resolved.actor if resolved is not None else ""
            reason = (
                "user_approved"
                if approved
                else "timeout"
                if resolved is None or not resolved.resolved
                else "user_rejected"
            )
            yield PlanResolvedEvent(
                request_id=pending.request_id,
                approved=approved,
                actor=actor,
                reason=reason,
            )
            if approved:
                store.append(
                    tool_result_message(
                        exit_plan_use.id,
                        "ExitPlanMode",
                        "Plan approved. Implement the approved plan.",
                        is_error=False,
                    )
                )
                _append_skipped_tool_results(
                    store,
                    tool_uses,
                    exit_plan_use.id,
                    "plan_approved",
                )
                approved_plan = plan_text
                set_agent_mode("agent")
                await _await_observe()
                continue

            store.append(
                tool_result_message(
                    exit_plan_use.id,
                    "ExitPlanMode",
                    "Plan not approved. Stop.",
                    is_error=True,
                )
            )
            _append_skipped_tool_results(store, tool_uses, exit_plan_use.id, "plan_rejected")
            await _await_observe()
            yield FinalEvent(
                text="Plan not approved.",
                prompt_tokens=hit + miss,
                completion_tokens=out,
                cache_hit_tokens=hit,
                cache_miss_tokens=miss,
                usd=round(budget.last_usage_usd, 8),
                used_usd=round(budget.used_usd, 8),
                usd_limit=budget.usd_limit,
            )
            return

        if not tool_uses:
            await _await_observe()
            yield FinalEvent(
                text=assistant_text,
                prompt_tokens=hit + miss,
                completion_tokens=out,
                cache_hit_tokens=hit,
                cache_miss_tokens=miss,
                usd=round(budget.last_usage_usd, 8),
                used_usd=round(budget.used_usd, 8),
                usd_limit=budget.usd_limit,
            )
            return

        admitted_tool_uses: list[ToolUse] = [
            tu for tu in tool_uses if tu.id in quota_held
        ]

        # 被闸拒绝的 early：cancel，避免白烧 IO 后把结果塞进历史
        admitted_ids = {tu.id for tu in admitted_tool_uses}
        rejected_early = {
            tid: task for tid, task in early.items() if tid not in admitted_ids
        }
        if rejected_early:
            await _cancel_early_tasks(rejected_early)
            for tid in rejected_early:
                early.pop(tid, None)

        if abort.aborted:
            await _cancel_early_tasks(early)
            _fill_missing_tool_results(store, tool_uses, "aborted")
            await _await_observe()
            yield StoppedEvent(reason="aborted")
            return

        late_uses = [tu for tu in admitted_tool_uses if tu.id not in early]
        early_admitted = {
            tu.id: early[tu.id] for tu in admitted_tool_uses if tu.id in early
        }
        # 写 / 外发等非只读工具：等 Before 快照就绪后再跑（只读 early 不受阻）。
        if late_uses and ensure_before is not None:
            needs_before = any(
                not tool_flag(
                    tools.get(tu.name),
                    "is_read_only",
                    default=False,
                )
                for tu in late_uses
            )
            if needs_before:
                try:
                    import inspect

                    gate: Any = ensure_before
                    if inspect.iscoroutinefunction(gate):
                        gate = await gate()
                    elif callable(gate):
                        gate = gate()
                    if inspect.isawaitable(gate):
                        await gate
                except Exception as exc:
                    for tu in late_uses:
                        if not tool_flag(
                            tools.get(tu.name),
                            "is_read_only",
                            default=False,
                        ):
                            results_by_id[tu.id] = ToolResult(
                                content=(
                                    f"[before_snapshot] blocked write: "
                                    f"{type(exc).__name__}: {exc}"
                                ),
                                is_error=True,
                                metadata={"before_snapshot_failed": True},
                            )
                    late_uses = [
                        tu
                        for tu in late_uses
                        if tool_flag(
                            tools.get(tu.name),
                            "is_read_only",
                            default=False,
                        )
                    ]

        late_task: asyncio.Task[list[ToolResult]] | None = None
        early_task: asyncio.Task[dict[str, ToolResult]] | None = None
        # Ask / Permission：工具一返回 pending 就 yield，wait 任务并行；
        # 整批工具跑完后再 gather 解析（用户若已点确认则立即返回）。
        ask_waiters: dict[str, asyncio.Task[Any]] = {}
        perm_waiters: dict[str, asyncio.Task[bool]] = {}
        ask_meta: dict[str, dict[str, Any]] = {}
        perm_meta: dict[str, dict[str, Any]] = {}
        seen_result_ids: set[str] = set()

        async def _await_early_map() -> dict[str, ToolResult]:
            out: dict[str, ToolResult] = {}
            for tid, task in early_admitted.items():
                res = await task
                out[tid] = res
                # early 在 stream 期可能已 put result_q；补投递供兜底。
                tu_early = next(
                    (u for u in admitted_tool_uses if u.id == tid),
                    None,
                )
                if tu_early is not None:
                    try:
                        result_q.put_nowait((tu_early, res))
                    except Exception:  # noqa: BLE001
                        pass
            return out

        def _ingest_raw_result(tu: ToolUse, result: ToolResult) -> list[EngineEvent]:
            """工具刚完成时：记零命中、立刻挂起 Ask/Permission。返回待 yield 事件。"""
            if tu.id in seen_result_ids:
                return []
            seen_result_ids.add(tu.id)
            events: list[EngineEvent] = []
            meta = getattr(result, "metadata", None) or {}
            if ZeroHitTracker.is_zero_hit(tu.name, meta):
                distinct_zero = safe_observe(
                    zero_hit_tracker.record, tu.name, tu.input,
                    label="ZeroHitTracker.record", default=0,
                )
                if distinct_zero >= ZERO_HIT_ADVICE_AT:
                    zero_hit_advice[tu.id] = ZeroHitTracker.notice(distinct_zero)
            ask_id = meta.get("ask_pending")
            if ask_id and coordinator is not None:
                from permissions.ask_store import default_ask_store

                rid = str(ask_id)
                ask_store = default_ask_store()
                ask_pending = ask_store.get(rid)
                events.append(
                    AskUserPendingEvent(
                        request_id=rid,
                        session_id=coordinator.session_id,
                        turn_id=coordinator.turn_id,
                        question=str(meta.get("question", "")),
                        options=list(meta.get("options") or []),
                        default=meta.get("default") or None,
                        questions=list(meta.get("questions") or []),
                        expires_at=ask_pending.expires_at if ask_pending else None,
                    )
                )
                ask_meta[tu.id] = {"rid": rid, "store": ask_store}
                ask_waiters[tu.id] = asyncio.create_task(ask_store.wait(rid))
                return events
            request_id = meta.get("permission_pending")
            if request_id and coordinator is not None:
                rid = str(request_id)
                pending_item = coordinator.store.get(rid)
                events.append(
                    PermissionPendingEvent(
                        request_id=rid,
                        tool_name=tu.name,
                        tool_input=tu.input if isinstance(tu.input, dict) else {},
                        reason=str(meta.get("reason", "needs_confirmation")),
                        prompt=str(meta.get("prompt", "")),
                        path=meta.get("path") or None,
                        expires_at=pending_item.expires_at if pending_item else None,
                        choices=list(
                            meta.get("choices")
                            or (pending_item.choices if pending_item else ())
                            or []
                        ),
                        peer_summary=str(
                            meta.get("peer_summary")
                            or (pending_item.peer_summary if pending_item else "")
                            or ""
                        ),
                        intent=intent_for(
                            choices=list(
                                meta.get("choices")
                                or (pending_item.choices if pending_item else ())
                                or []
                            )
                        ),
                    )
                )
                perm_meta[tu.id] = {"rid": rid, "tu": tu}
                perm_waiters[tu.id] = asyncio.create_task(coordinator.wait(rid))
                return events
            results_by_id[tu.id] = result
            return events

        try:
            if late_uses:
                late_task = asyncio.create_task(
                    run_tools_partitioned(
                        tools,
                        late_uses,
                        abort,
                        coordinator=coordinator,
                        progress_q=progress_q,
                        result_q=result_q,
                    )
                )
            if early_admitted:
                early_task = asyncio.create_task(_await_early_map())

            pending: set[asyncio.Task[Any]] = {
                t for t in (late_task, early_task) if t is not None
            }
            for t in pending:
                t.add_done_callback(lambda _t: wake.set())

            while pending:
                drained = False
                try:
                    while True:
                        yield progress_q.get_nowait()
                        drained = True
                except asyncio.QueueEmpty:
                    pass
                try:
                    while True:
                        tu_done, res_done = result_q.get_nowait()
                        for ev in _ingest_raw_result(tu_done, res_done):
                            yield ev
                        drained = True
                except asyncio.QueueEmpty:
                    pass
                pending = {t for t in pending if not t.done()}
                if not pending:
                    break
                if drained:
                    continue
                wake.clear()
                if not progress_q.empty() or not result_q.empty():
                    continue
                if any(t.done() for t in pending):
                    continue
                await wake.wait()
            try:
                while True:
                    yield progress_q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                while True:
                    tu_done, res_done = result_q.get_nowait()
                    for ev in _ingest_raw_result(tu_done, res_done):
                        yield ev
            except asyncio.QueueEmpty:
                pass

            late_results = late_task.result() if late_task is not None else []
            early_by_id = early_task.result() if early_task is not None else {}
            late_by_id = {
                tu.id: result for tu, result in zip(late_uses, late_results, strict=True)
            }
            # 兜底：若 result_q 漏投递，仍按完成顺序 ingest。
            for tu in admitted_tool_uses:
                if tu.id in seen_result_ids or tu.id in results_by_id:
                    continue
                raw = (
                    early_by_id[tu.id]
                    if tu.id in early_by_id
                    else late_by_id.get(tu.id)
                )
                if raw is None:
                    continue
                for ev in _ingest_raw_result(tu, raw):
                    yield ev
        except Aborted:
            if late_task is not None and not late_task.done():
                late_task.cancel()
            for t in (*ask_waiters.values(), *perm_waiters.values()):
                t.cancel()
            await _cancel_early_tasks(early)
            _fill_missing_tool_results(store, tool_uses, "aborted")
            await _await_observe()
            yield StoppedEvent(reason="aborted")
            return
        except Exception:
            if late_task is not None and not late_task.done():
                late_task.cancel()
            for t in (*ask_waiters.values(), *perm_waiters.values()):
                t.cancel()
            await _cancel_early_tasks(early)
            _fill_missing_tool_results(store, tool_uses, "error")
            await _await_observe()
            raise

        # 同批 Ask / Permission 并行等用户；已确认的立即返回。
        # 该区间同样要兜 Aborted / 异常：批准后的写工具重跑（tools.run）
        # 落在 abort 置位窗口会抛 Aborted，若不补 StoppedEvent / tool_result，
        # SSE 契约破坏、transcript 留 unpaired tool_use、turn 被记 failed。
        try:
            wait_set = set(ask_waiters.values()) | set(perm_waiters.values())
            if wait_set:
                await asyncio.wait(wait_set)
        except Aborted:
            if late_task is not None and not late_task.done():
                late_task.cancel()
            for t in (*ask_waiters.values(), *perm_waiters.values()):
                t.cancel()
            await _cancel_early_tasks(early)
            _fill_missing_tool_results(store, tool_uses, "aborted")
            await _await_observe()
            yield StoppedEvent(reason="aborted")
            return
        except Exception:
            if late_task is not None and not late_task.done():
                late_task.cancel()
            for t in (*ask_waiters.values(), *perm_waiters.values()):
                t.cancel()
            await _cancel_early_tasks(early)
            _fill_missing_tool_results(store, tool_uses, "error")
            await _await_observe()
            raise

        for tu_id, task in ask_waiters.items():
            info = ask_meta[tu_id]
            rid = str(info["rid"])
            try:
                resolved = task.result()
            except Exception:
                resolved = None
            timeout = resolved is None or resolved.answer is None
            answer = (
                resolved.answer if resolved and resolved.answer is not None else ""
            )
            yield AskUserResolvedEvent(
                request_id=rid,
                answer=answer,
                actor=resolved.actor if resolved else "",
                timeout=timeout,
            )
            if not timeout:
                results_by_id[tu_id] = ToolResult(content=answer, is_error=False)
            else:
                results_by_id[tu_id] = ToolResult(
                    content="[no answer: the user did not respond]",
                    is_error=True,
                    metadata={"ask_timeout": True},
                )

        for tu_id, task in perm_waiters.items():
            info = perm_meta[tu_id]
            rid = str(info["rid"])
            tu = info["tu"]
            try:
                choice = str(task.result() or "deny")
            except Exception:
                choice = "timeout"
            approved = choice == "allow"
            yield PermissionResolvedEvent(
                request_id=rid,
                approved=approved,
                actor="",
                reason="user_decided" if choice in ("allow", "deny", "remind") else choice,
                choice=choice,
            )
            if approved:
                try:
                    results_by_id[tu_id] = await tools.run(
                        tu, abort, coordinator=coordinator, skip_ask=True
                    )
                except Aborted:
                    results_by_id[tu_id] = ToolResult(
                        content="[tool aborted]",
                        is_error=True,
                        metadata={"aborted": True},
                    )
                _notify_peers_after_allow(tu, cwd=_workspace_cwd_for_turn(tools))
            elif choice == "remind":
                results_by_id[tu_id] = ToolResult(
                    content=_peer_remind_tool_message(tu),
                    is_error=True,
                    metadata={"permission_denied": True, "permission_choice": "remind"},
                )
                _queue_peer_remind_notices(tu, cwd=_workspace_cwd_for_turn(tools))
            else:
                # T3 统一文案：rejected（显式拒绝）/ cancelled（面板关闭/停止）/
                # unavailable（超时）——按 store 的 outcome 区分。
                _item = coordinator.store.get(rid)
                _outcome = str(getattr(_item, "outcome", "") or "")
                if _outcome == "aborted":
                    _deny_text = CANCELLED_COPY
                elif _outcome == "timeout" or choice == "timeout":
                    _deny_text = UNAVAILABLE_COPY
                else:
                    _deny_text = REJECTED_COPY
                results_by_id[tu_id] = ToolResult(
                    content=_deny_text,
                    is_error=True,
                    metadata={"permission_denied": True, "permission_choice": choice},
                )

        for tu in tool_uses:
            result = results_by_id[tu.id]

            if abort.aborted:
                _fill_missing_tool_results(store, tool_uses, "aborted")
                await _await_observe()
                yield StoppedEvent(reason="aborted")
                return
            result_metadata = getattr(result, "metadata", None) or {}
            suffixes: list[str] = []
            advice = zero_hit_advice.get(tu.id)
            if advice:
                # 多组不同查询皆空：中立提示回读原题，不指向具体方向。
                suffixes.append(advice)
            out_content = (
                result.content
                if not suffixes
                else f"{result.content}\n\n" + "\n\n".join(suffixes)
            )
            yield ToolResultEvent(
                name=tu.name,
                output=out_content,
                is_error=result.is_error,
                tool_use_id=tu.id,
                todos=getattr(result, "todos", None),
                operation_id=(
                    str(result_metadata["operation_id"])
                    if result_metadata.get("operation_id")
                    else None
                ),
                ui=getattr(result, "ui", None),
            )
            # R2'：同签名 · 输出字节级相同 → 历史/模型视图折叠为一行 [fold] 事实，
            # 保留 tool_use↔result 配对且首次完整输出仍在历史（信息无损）。
            # GUI 实时事件仍展示真实输出；折叠只作用于写入 store 的持久文本。
            stored_content = out_content
            # 诊断采集与防护动作**分属两条独立路径**：账本是诊断（失败只剩少
            # 一行数据），折叠是防护（失败即空转失去止血阀）。任何“共用一个
            # try”的写法都会让诊断侧异常连带打死折叠——2026-09-14 事故
            # （params_digest 传了原始 dict → TypeError → [fold] 全域失效）。
            # 观测统一经 safe_observe 隔离；折叠单独 try / fail-open 保留原文。
            # 行为账本：s1/s2 信号采集（纯计数，无副作用；豁免集在 LoopLedger
            # 内部处理）。fold 判定与其独立、互不影响。params_digest 只存摘要
            # （锚点报“参数变体种数”用）。
            safe_observe(
                loop_ledger.observe_tool,
                tu.name,
                out_content,
                label="LoopLedger.observe_tool",
                params_digest=params_digest(getattr(tu, "input", None)),
            )
            # 循环熔断：L3 结果等价 / L4 无新内容 / 半开探针自愈（写入 store 前）。
            safe_observe(
                loop_breaker.observe_result,
                tu.name,
                getattr(tu, "input", None),
                out_content,
                label="LoopBreaker.observe_result",
            )
            try:
                if not getattr(result, "images", None):
                    stored_content, _folded = result_fold.process(
                        tu.name, tu.input, out_content
                    )
            except Exception:  # noqa: BLE001 — 折叠失败 fail-open 保留原文
                logging.getLogger(__name__).debug(
                    "repeat fold failed", exc_info=True
                )
            store.append(
                tool_result_message(
                    tu.id,
                    tu.name,
                    stored_content,
                    is_error=result.is_error,
                    images=getattr(result, "images", None),
                )
            )
            # 批次4：Plan 衰减（首写收敛）——批准后本 query 内首次成功写盘，
            # 全量计划块静默并切换为"实施中"指针块（正文已在紧邻历史，
            # 重发只剩 ≤4k 冗余；指针保留"契约仍在"的轻在场）。
            if approved_plan and approved_plan_decays_on(tu.name, result.is_error):
                approved_plan = None
                plan_pointer = True
        if abort.aborted:
            _fill_missing_tool_results(store, tool_uses, "aborted")
            await _await_observe()
            yield StoppedEvent(reason="aborted")
            return
        if budget.over_token_budget():
            await _await_observe()
            yield StoppedEvent(reason="budget")
            return
        await _await_observe()
