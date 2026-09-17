"""Chat 域路由：主 Agent 流式对话、Side-chat 直连模型与旧版兼容垫片。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from common.errors import friendly_error

from model.openai_compat import PROVIDER_PRESETS

from msgtypes.envelope import EventIdGenerator
from msgtypes.events import (
	AssistantDelta,
	ReasoningDelta,
	FinalEvent,
	StoppedEvent,
	ToolCallEvent,
	ToolProgressEvent,
	ToolResultEvent,
	UsageEvent,
	ContextCompressionEvent,
	SteerDeliveredEvent,
	ResultEvent,
	AskUserPendingEvent,
	AskUserResolvedEvent,
	PermissionPendingEvent,
	PermissionResolvedEvent,
	PlanPendingEvent,
	PlanResolvedEvent,
	TaskStateEvent,
	LlmRetryEvent,
	LlmRetryStartedEvent,
)
from msgtypes.message import Message, user_message
from permissions.policy import (
	set_agent_mode,
	set_browser_preview_url,
	set_code_compact,
	set_code_mode,
	set_output_compact,
	set_output_mode,
	set_permission_mode,
	set_side_mode,
	set_surface,
)
from tools.web_search_tool.config import set_searxng_url
from server.deps import (
	_MAX_PRIOR_CHARS,
	_MAX_PRIOR_MESSAGES,
	_MAX_USER_CHARS,
	_extract_bearer,
	_pool,
	_resolve_base_url,
	_validated_media_refs,
	api_error,
	error_body,
	fake_model_enabled,
	local_model_allowed,
)
from server.session_pool import CwdConflictError, ModelConfig
from server.local_gate import require_loopback

_stream_log = logging.getLogger("xeyo.chat.stream")

# Multi-Agent：主会话 Markdown 摘要里，每个子任务「正文」段的硬上限。
# 仅防模型/异常输出撑爆 JSONL 与 SSE delta，不是业务截断；完整对话见侧链。
_MAIN_SUMMARY_BODY_LIMIT = 4096
# 运行中 progress 帧 / 卡片一行预览（比主摘要短，减轻 SSE 负载）。
_TASK_PROGRESS_RESULT_LIMIT = 800

# T33：聊天面与控制面同标准——仅 loopback（LAN 直连默认 403；
# 隧道部署用 XEYO_ALLOW_REMOTE_CONTROL=1 显式放开）。
router = APIRouter(tags=["chat"], dependencies=[Depends(require_loopback)])

class ChatMessage(BaseModel):
	role: str
	content: str | list[Any] | None = None
	media_refs: list[str] = Field(default_factory=list, max_length=8)
	id: str | None = Field(default=None, max_length=256)


class ChatCompletionRequest(BaseModel):
	model: str
	messages: list[ChatMessage] = Field(default_factory=list)
	media_refs: list[str] = Field(default_factory=list, max_length=8)
	stream: bool = True
	temperature: float | None = None
	# XEYO 扩展字段
	session_id: str | None = None
	# "local"（本地推理）需 XEYO_ALLOW_LOCAL_MODEL=1 门禁开启，默认拒绝；
	# "fake"（HTTP 全栈测试假模型）需 XEYO_ALLOW_FAKE_MODEL=1。
	provider: Literal["deepseek", "openai", "local", "fake"] | None = None
	base_url: str | None = None
	thinking: str | None = None
	reasoning_effort: str | None = None
	# L1.2：本轮 USD 上限；缺省回落 XEYO_MAX_BUDGET_USD / 不限额。
	max_budget_usd: float | None = None
	# 供应商模型元数据给出的上下文上限；未知时不发送伪造值。
	context_limit: int | None = Field(default=None, gt=0)
	# 最大输出 tokens（可选）；None = 不限制，不发送该字段。
	max_tokens: int | None = Field(default=None, gt=0)
	# 前端选择的审批模式：always / risk / never；缺省回退 env / 默认 risk。
	permission_mode: str | None = None
	# T10：权限 preset（readonly / workspace-write / full）；仅会话创建时 pin，
	# 后续请求传入不同值不溯及既有会话。
	permission_preset: str | None = None
	# 可选自建 SearXNG 基址（如 http://127.0.0.1:8080）；空则 Bing/Mojeek。
	searxng_url: str | None = None
	# 前端选择的会话 Agent 模式：agent / plan / ask；缺省 agent。
	agent_mode: Literal["agent", "plan", "ask"] | None = None
	# 设置「输出精简」：True 时 T_now 注入压缩铁律 + 模式段；不进 system 左段。
	# T31：None = 客户端未设置 → 由会话 durable 模式记录决定（投影覆盖）。
	output_compact: bool | None = None
	# 输出精简模式：lite / full / ultra；仅 output_compact 开启时生效，缺省 lite。
	output_mode: Literal["lite", "full", "ultra"] | None = None
	# 设置「写代码精简」：True 时 T_now 注入实现体积铁律 + 模式段。
	code_compact: bool | None = None
	# 写代码精简模式：lite / full / ultra；仅 code_compact 开启时生效，缺省 lite。
	code_mode: Literal["lite", "full", "ultra"] | None = None
	# 右侧预览浏览器当前 URL（仅面板打开时由 GUI 上报）；T_now 注入，不进历史。
	browser_preview_url: str | None = None
	# Composer Multi-Agent chip：True → T_now 软提示偏向 Agent；不锁工具、不拦收尾；
	# False → 仍注册 Agent，主模型可主动 spawn。不再走分解流水线。
	multi_agent: bool = False
	# 用户选中的工作区根；钉死到该 session，禁止默认 python/。
	workspace: str | None = None
	# 侧聊（side chat）：只读工具白名单 + 不注入 workspace 内容（CWD/XEYO.md/
	# Memory 索引等）。session_id 用 side- 前缀，transcript 与主链路同格式。
	side: bool = False
	# P1 mid-turn inbox：会话忙时把消息排进 FIFO（settle 后自动投递），返回 202
	# 而非 409。默认 False 保持 CLI/旧客户端 409 兼容；GUI 置 True；side 会话强制忽略。
	queue_if_busy: bool = False
	# 引导（steer）：忙时消息不排队等 settle，而是到**边界**投递——作为真 user
	# 消息进历史，模型在下一步行动前看到它（不打断正在进行的工具批次）。
	# 仅在 queue_if_busy 同时为 True 时生效；side 会话强制忽略；入队失败回落排队。
	steer_if_busy: bool = False
	# 遗留字段：旧批量 API 的显式 tasks；工具化后忽略（主模型自行 tool call）。
	tasks: list[dict[str, Any]] | None = None


def _engine_for(
	session_id: str,
	cfg: ModelConfig,
	*,
	initial_messages: list[Message] | None = None,
	workspace: str | None = None,
	permission_preset: str | None = None,
):
	try:
		return _pool.get_or_create(
			session_id,
			cfg,
			initial_messages=initial_messages,
			cwd=(workspace or "").strip() or None,
			permission_preset=permission_preset,
		)
	except CwdConflictError as e:
		raise api_error(400, str(e)) from e
	except (FileNotFoundError, NotADirectoryError, ValueError) as e:
		raise api_error(400, str(e)) from e


def _workspace_for(session_id: str, body: ChatCompletionRequest) -> str | None:
	"""T31 workspace SSOT：服务端权威。

	会话已钉死 cwd → 忽略客户端 workspace（服务端说了算：不覆写、也不冲突）。
	未钉死 → 用服务端把客户端发送的 workspace id/路径解析成真实路径。
	"""
	pinned = _pool.session_cwd(session_id)
	if pinned:
		return None
	return _pool.resolve_workspace(body.workspace) or None


def _busy_or_queue(
	session_id: str,
	body: "ChatCompletionRequest",
	user_text: str,
	*,
	media_refs: list[str],
	message_id: str | None,
) -> JSONResponse:
	"""会话忙时的统一出口：queue_if_busy → 排队并返回 202；否则抛 409。

	- 排队：把真实用户消息入 FIFO（只存文本/媒体/客户端 id），settle 后由
	  inbox 租户自动投递；绝不触碰 T_now / MessageStore（KV 前缀零破坏）。
	- 引导（steer）：同一个 FIFO 里的消息改由**边界**投递（下一轮采样前），
	  作为真 user 消息进历史——工具批次不被打断，模型立刻看到。
	- 409：维持 CLI/旧客户端行为（GUI 在 queue_if_busy=True 时走排队路径）。
	"""
	if body.steer_if_busy and body.side:
		# 引导在 side 会话不支持：明确告知（不静默降级成排队）
		raise api_error(
			409, "side 会话不支持引导；请等本轮结束后再发", "steer_unsupported_side"
		)
	if body.steer_if_busy and body.queue_if_busy and not body.side:
		from engine.t_now_steer import push as _steer_push

		if _steer_push(
			session_id,
			user_text,
			images=media_refs,
			message_id=message_id or "",
		):
			return JSONResponse(
				status_code=202,
				content={
					"queued": True,
					"steered": True,
					# 投递口径显式化：boundary = 本轮下一个边界就送到模型；
					# after_turn = 回落 settle 后排（下一轮才送达）。
					"delivery": "boundary",
				},
			)
		# 引导入队失败（队列满 / 内部异常）→ 回落既有 settle 排队语义
	if body.queue_if_busy and not body.side:
		from server.inbox_registry import (
			InboxQueueFull,
			InboxTextTooLong,
			get_inbox_registry,
		)

		reg = get_inbox_registry()
		try:
			item = reg.enqueue(
				session_id,
				user_text,
				media_refs=media_refs,
				message_id=message_id,
			)
		except InboxQueueFull as e:
			raise api_error(429, str(e), "queue_full") from e
		except InboxTextTooLong as e:
			# 2026-09-05 修正：超长不再静默截断，明确 413（用户可拆分重发）。
			raise api_error(413, str(e), "inbox_text_too_long") from e
		position = len(reg.snapshot(session_id)["items"])
		# 2026-09-05 e2e 抓修：Starlette JSONResponse 第一个位置参数是 content，
		# 旧写法 JSONResponse(202, {...}) 把 202 当 content、payload 当 status_code
		# → 忙时排队路径必然 TypeError 500（202 从未真正返回过）。
		return JSONResponse(
			status_code=202,
			content={
				"queued": True,
				"delivery": "after_turn",
				"queue_id": item.queue_id,
				"position": position,
			},
		)
	raise api_error(409, "会话正忙，请稍候或点停止后重试", "session_busy")


def _parse_goal_round_header(raw: str | None) -> tuple[str, int, int] | None:
	"""解析 41 号合成轮标记头 ``X-Xeyo-Goal-Round: "<goal_id>@<round>@<cap>"``。

	仅用于 enriched resume prompt 的轮次注入；解析失败一律返回 None（人类发的
	同名头无效即可，不报错——该头不是安全边界，只是提示富化）。
	"""
	t = (raw or "").strip()
	if not t:
		return None
	parts = t.split("@")
	if len(parts) != 3:
		return None
	gid = parts[0].strip()
	try:
		rnd = int(parts[1])
		cap = int(parts[2])
	except ValueError:
		return None
	if not gid or rnd < 1 or cap < 1:
		return None
	return gid, rnd, cap


def _effective_request_modes(engine: Any, body: ChatCompletionRequest) -> dict[str, Any]:
	"""T31：把请求体模式作为投影覆盖到会话 durable 模式记录上。

	- 会话已有 durable 模式 → 以它为准，请求体为投影覆盖（回复会话/跨入口恢复
	  时模式自动重建，请求体不再自造默认值碾压）。
	- 会话还没有模式记录（/首建）→ 请求体值即首建（first-effective-wins）。
	返回生效模式 dict（agent_mode / output_compact / output_mode / code_compact /
	code_mode），同时写回 working，供引擎在回合结束 flush 持久化。
	"""
	from memory.working import apply_modes, resolve_modes

	working = getattr(getattr(engine, "_session", None), "working", None)
	if working is None:
		# 引擎尚未构建完整 working 时退化为纯请求体投影（不应发生，fail-closed）。
		from memory.working import WorkingSnapshot

		working = WorkingSnapshot(session_id=getattr(engine, "session_id", "") or "")
	eff = resolve_modes(
		working,
		agent_mode=body.agent_mode,
		output_compact=body.output_compact,
		output_mode=body.output_mode,
		code_compact=body.code_compact,
		code_mode=body.code_mode,
	)
	apply_modes(working, eff)
	return eff


def _message_text(content: str | list[Any] | None) -> str:
	if content is None:
		return ""
	if isinstance(content, str):
		return content
	if isinstance(content, list):
		parts: list[str] = []
		for block in content:
			if isinstance(block, dict) and block.get("type") == "text":
				parts.append(str(block.get("text") or ""))
			elif isinstance(block, str):
				parts.append(block)
		return "\n".join(parts)
	return str(content)


def _last_user_text(messages: list[ChatMessage]) -> str:
	for m in reversed(messages):
		if m.role != "user":
			continue
		return _message_text(m.content)
	return ""


_MULTI_AGENT_RESUME_CUES = frozenset({
	"继续",
	"继续执行",
	"继续进行",
	"继续做",
	"继续吧",
	"请继续",
	"接着",
	"接着做",
	"接着干",
	"续跑",
	"resume",
	"continue",
	"go on",
})


def _is_multi_agent_resume_cue(text: str) -> bool:
	"""「继续」类短指令：不是新目标，应复用原任务目标 / checkpoint。"""
	t = (text or "").replace("\u200b", "").replace("\ufeff", "").strip()
	if not t:
		return False
	low = t.lower()
	if t in _MULTI_AGENT_RESUME_CUES or low in _MULTI_AGENT_RESUME_CUES:
		return True
	# 「继续。」「继续！」等短变体仍算口令；带实质内容的「继续把…」不算。
	stripped = t.strip("。.!?！？~… \t\r\n")
	low2 = stripped.lower()
	return stripped in _MULTI_AGENT_RESUME_CUES or low2 in _MULTI_AGENT_RESUME_CUES


def _previous_user_goal(messages: list[ChatMessage]) -> str:
	"""跳过本轮用户消息与续跑口令，取上一条实质用户目标。"""
	seen_latest = False
	for m in reversed(messages):
		if m.role != "user":
			continue
		text = _message_text(m.content).strip()
		if not text:
			continue
		if not seen_latest:
			seen_latest = True
			continue
		if _is_multi_agent_resume_cue(text):
			continue
		return text
	return ""


def _build_enriched_resume_prompt(
	*,
	user_cue: str,
	goal: str,
	todos: list[dict[str, Any]] | None = None,
	stop_reason: str = "",
	active_agents: list[str] | None = None,
	round_info: tuple[str, int, int] | None = None,
) -> str:
	"""结构化续跑前缀：用户气泡仍显示「继续」，engine 收到 enriched prompt。

	41 号：``round_info``（goal_id, round, cap）非 None 时为 goal 轮合成提交，
	追加轮次行与完成判定权威声明（``<goal_round>`` 的证据要求）。
	"""
	lines = [
		"# Resume state（background only）",
		f"resume_cue={((user_cue or '继续').strip() or '继续')}；interrupted_turn=true",
	]
	goal_s = (goal or "").strip()
	if goal_s:
		lines.append(f"Original goal:\n{goal_s}")
	incomplete: list[str] = []
	for t in todos or []:
		if not isinstance(t, dict):
			continue
		status = str(t.get("status") or "").lower()
		if status in {"completed", "cancelled", "canceled"}:
			continue
		content = str(t.get("content") or t.get("text") or t.get("title") or "").strip()
		if content:
			incomplete.append(f"- [{status or 'pending'}] {content}")
	if incomplete:
		lines.append("Incomplete todos:")
		lines.extend(incomplete[:24])
	agents = [a for a in (active_agents or []) if a]
	if agents:
		lines.append("Interrupted subagents: " + ", ".join(agents[:16]))
	if stop_reason:
		lines.append(f"Last stop reason: {stop_reason}")
	if round_info:
		_gid, _rnd, _cap = round_info
		lines.append(
			f"Goal round: {_rnd}/{_cap}；bound_goal={_gid}；continuation=automatic。"
		)
		lines.append("completion_basis=workspace_state_and_tool_results")
	return "\n".join(lines)


def _last_user_media_refs(messages: list[ChatMessage]) -> list[str]:
	for m in reversed(messages):
		if m.role == "user":
			return list(m.media_refs or [])
	return []


def _client_message_id(item: ChatMessage) -> str | None:
	raw = (item.id or "").strip()
	return raw or None


def _engine_message_from_chat(item: ChatMessage) -> Message | None:
	role = (item.role or "").lower()
	if role not in ("user", "assistant", "system"):
		return None
	text = _message_text(item.content).strip()
	if not text:
		return None
	client_id = _client_message_id(item)
	if role == "system":
		return user_message(f"[system]\n{text}", message_id=client_id)
	if role == "assistant":
		return Message(
			role="assistant",
			content=text,
			id=client_id or uuid.uuid4().hex,
		)
	return user_message(
		text,
		images=_validated_media_refs(item.media_refs),
		message_id=client_id,
	)


def _split_prior_and_user(
	messages: list[ChatMessage],
) -> tuple[list[Message], str, str | None]:
	"""先前回合（engine Message）+ 最新用户文本，供 submit 使用。

	末尾 user 消息不包含在 prior 中 — submit_message 会自行追加。
	"""
	user_text = _last_user_text(messages).strip()
	last_user_idx = -1
	for i in range(len(messages) - 1, -1, -1):
		if messages[i].role == "user":
			last_user_idx = i
			break
	prior_raw = messages[:last_user_idx] if last_user_idx >= 0 else list(messages)
	last_user_id = (
		_client_message_id(messages[last_user_idx]) if last_user_idx >= 0 else None
	)

	prior: list[Message] = []
	total_chars = 0
	for m in prior_raw:
		msg = _engine_message_from_chat(m)
		if msg is None:
			continue
		if (
			msg.role == "assistant"
			and prior
			and prior[-1].role == "assistant"
		):
			prev = prior[-1]
			merged = f"{_message_text(prev.content)}\n\n{_message_text(msg.content)}".strip()
			prior[-1] = Message(
				role="assistant",
				content=merged,
				id=prev.id,
			)
			total_chars += len(_message_text(msg.content))
			continue
		total_chars += len(_message_text(msg.content))
		prior.append(msg)

	if len(prior) > _MAX_PRIOR_MESSAGES:
		prior = prior[-_MAX_PRIOR_MESSAGES:]
	total_chars = sum(len(_message_text(m.content)) for m in prior)
	while prior and total_chars > _MAX_PRIOR_CHARS:
		dropped = prior.pop(0)
		total_chars -= len(_message_text(dropped.content))

	return prior, user_text, last_user_id


def _openai_chunk(content: str, *, model: str, finish: str | None = None) -> str:
	payload = {
		"id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
		"object": "chat.completion.chunk",
		"created": int(time.time()),
		"model": model,
		"choices": [
			{
				"index": 0,
				"delta": {"content": content} if content else {},
				"finish_reason": finish,
			}
		],
	}
	return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# 主气泡锚点：分配说明 | 子 Agent 卡片 | 汇总（FE 按此切开，注释本身不展示）
_XY_AGENTS_ANCHOR = "\n\n<!--xeyo:agents-->\n\n"


def _xy_chunk(xy: dict[str, Any], *, model: str) -> str:
	"""XEYO 结构化旁路（tool_call / tool_result）。

	不放在 ``choices[].delta.content`` 中，以便 FE 渲染 ``role: tool``
	行而非 Markdown 内联工具噪声（#8）。
	"""
	payload = {
		"id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
		"object": "chat.completion.chunk",
		"created": int(time.time()),
		"model": model,
		"xy": xy,
		"choices": [
			{
				"index": 0,
				"delta": {},
				"finish_reason": None,
			}
		],
	}
	return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


_UI_FIELD_MAX = 240


def _sanitize_tool_input_for_ui(raw: Any) -> Any:
	"""在 SSE 旁路中缩小 Write/Edit 正文，保持 FE 响应流畅。"""
	if not isinstance(raw, dict):
		return raw
	out = dict(raw)
	content = out.get("content")
	if isinstance(content, str) and len(content) > _UI_FIELD_MAX:
		lines = content.count("\n") + (1 if content else 0)
		out["content"] = (
			content[:_UI_FIELD_MAX]
			+ f"\n… [{lines} lines, {len(content)} chars]"
		)
		out["_content_lines"] = lines
	for key in ("old_string", "new_string"):
		val = out.get(key)
		if isinstance(val, str) and len(val) > _UI_FIELD_MAX:
			lines = val.count("\n") + (1 if val else 0)
			out[key] = (
				val[:_UI_FIELD_MAX] + f"\n… [{lines} lines, {len(val)} chars]"
			)
	return out


def _sse_error(message: str, err_type: str = "model_error") -> str:
	"""OpenAI 风格 SSE 错误帧 — FE parseOpenAiSse 读取 obj.error。"""
	payload = error_body(message, err_type)
	return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"










@router.post("/v1/chat/completions", response_model=None)
async def chat_completions(
	request: Request,
	body: ChatCompletionRequest,
	authorization: str | None = Header(default=None),
	x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
	x_provider: str | None = Header(default=None, alias="X-Provider"),
	x_base_url: str | None = Header(default=None, alias="X-Base-Url"),
	x_xeyo_surface: str | None = Header(default=None, alias="X-Xeyo-Surface"),
	x_goal_round: str | None = Header(default=None, alias="X-Xeyo-Goal-Round"),
):
	api_key = _extract_bearer(authorization)
	# T39：/compact 双闸守卫在函数较早处使用 get_turn_runner；必须在此先绑定，
	# 否则会命中函数级 import（line ~665）之下的名称未绑定错误（UnboundLocalError）。
	from engine.turn_runner import get_turn_runner
	provider = (body.provider or x_provider or "deepseek").lower()
	if provider not in PROVIDER_PRESETS or (
		provider == "local" and not local_model_allowed()
	) or (provider == "fake" and not fake_model_enabled()):
		raise api_error(400, f"unsupported provider: {provider}")
	# 本地模型免 API Key 需 XEYO_ALLOW_LOCAL_MODEL=1 显式开启。
	if not api_key:
		if provider in ("local", "fake"):
			api_key = "local"
		else:
			raise api_error(
				401,
				"Missing API key. Set Authorization: Bearer <key>",
				"authentication_error",
			)

	base_url = _resolve_base_url(provider, body.base_url or x_base_url)
	session_id = body.session_id or x_session_id or f"anon-{uuid.uuid4().hex[:8]}"
	# 41 号：合成轮标记（driver 自调用时携带；人类请求无此头 → None）。
	goal_round = _parse_goal_round_header(x_goal_round)
	media_refs = _validated_media_refs(
		body.media_refs or _last_user_media_refs(body.messages)
	)
	prior_messages, user_text, user_message_id = _split_prior_and_user(body.messages)
	if not user_text:
		raise api_error(400, "no user message content")
	if len(user_text) > _MAX_USER_CHARS:
		raise api_error(
			413,
			f"user message too large ({len(user_text)} > {_MAX_USER_CHARS} chars)",
		)

	# T29 测试钩子：仅当 XEYO_TEST_STREAM_DROP=1 且用户消息含哨兵时，故意让前端在
	# 未收到 [DONE] 前断流 → 前端触发「连接中断」banner，且不自动 interrupt。
	# 生产路径（未设该 env 或缺哨兵）完全不受影响。
	drop_stream = (
		os.environ.get("XEYO_TEST_STREAM_DROP") == "1"
		and "__XEYO_DROP_STREAM__" in user_text
	)

	# 手动 /compact：不进模型循环，强制前进 C2 游标并回一条系统说明
	_compact_cmd = user_text.strip().lower()
	if _compact_cmd in {"/compact", "compact", "/压缩"}:
		# T39：与主路径同源双闸。先查 TurnRunner.is_running——权限等待久的 turn
		# 租约可能被 stale 回收，只查租约会让 compact 与活跃 turn 并发改写
		# session.working；两道都过才放行。
		if get_turn_runner().is_running(session_id):
			raise api_error(
				409,
				"会话正忙，请稍候或点停止后重试",
				"session_busy",
			)
		lease_id = _pool.try_begin(session_id)
		if lease_id is None:
			raise api_error(
				409,
				"会话正忙，请稍候或点停止后重试",
				"session_busy",
			)
		cfg = ModelConfig(
			provider=provider,
			api_key=api_key,
			base_url=base_url,
			model=body.model,
			thinking=(body.thinking or "disabled").strip().lower(),
			reasoning_effort=(body.reasoning_effort or "").strip().lower(),
			max_budget_usd=body.max_budget_usd,
			context_limit=body.context_limit,
			max_tokens=body.max_tokens,
		)
		try:
			engine = _engine_for(
				session_id,
				cfg,
				initial_messages=prior_messages or None,
				workspace=_workspace_for(session_id, body),
			)
			# 统一斜杠命令：/compact 复用 slash.dispatch（与 CLI / 远程同源）。
			from slash.dispatch import DispatchContext, dispatch as _dispatch_slash

			_compact_res = _dispatch_slash(
				"compact",
				"",
				ctx=DispatchContext(session_id=session_id, engine=engine),
			)
			note = _compact_res.message or "已请求压缩。"
			_compact_payload = (
				_compact_res.result if isinstance(_compact_res.result, dict) else {}
			)
			after = int(_compact_payload.get("compact_cursor") or 0)
			chars = int(_compact_payload.get("c2_summary_chars") or 0)

			async def _compact_stream() -> AsyncIterator[bytes]:
				payload = {
					"id": f"compact-{uuid.uuid4().hex[:8]}",
					"object": "chat.completion.chunk",
					"choices": [
						{
							"index": 0,
							"delta": {"role": "assistant", "content": note},
							"finish_reason": None,
						}
					],
				}
				yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()
				done = {
					"id": payload["id"],
					"object": "chat.completion.chunk",
					"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
					"xeyo": {
						"type": "context_compression",
						"source": "manual",
						"compact_cursor": after,
						"c2_summary_chars": chars,
						"active": after > 0,
					},
				}
				yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n".encode()
				yield b"data: [DONE]\n\n"

			return StreamingResponse(
				_compact_stream(),
				media_type="text/event-stream",
				headers={"X-Session-Id": session_id},
			)
		except HTTPException:
			raise
		except Exception as e:  # noqa: BLE001
			raise api_error(500, friendly_error(e), "server_error") from e
		finally:
			_pool.end(session_id, lease_id)

	# 41 号：人类消息让位最高优先——取消在途 goal 轮预约（不消耗轮号）。
	# 放在全部 busy 闸之前：人类请求永远优先于 driver 的合成轮。
	# 42 号（§3.3）泛化：同一入口取消在途 job 唤醒决策；人类输入是唯一
	# 恢复共享唤醒预算的通道（合成轮面 job-wake/goal-driver 不恢复）。
	# 2026-09-05 事故修正：yield_to_human **只对人类面调用**——合成轮请求
	# （goal-driver/job-wake）整个跑在 driver 的预约 task 里，对它调
	# yield_to_human 会取消它自己 → 合成轮在 turn 启动前自我湮灭。
	_human_surface = (x_xeyo_surface or "").strip() not in ("goal-driver", "job-wake")
	# P1：mid-turn inbox 投递轮（submit_synthetic surface="inbox"）——是真实用户消息，
	# 但应跳过 resume 富化 / goal 自动创建 / checkpoint 清理 / jobs digest 注入（省钱第二杠杆）。
	_inbox_surface = (x_xeyo_surface or "").strip() == "inbox"
	if _human_surface:
		try:
			from server.goal_round_driver import get_goal_round_driver

			get_goal_round_driver().yield_to_human(session_id)
		except Exception:  # noqa: BLE001
			pass
	if _human_surface:
		try:
			from server.job_registry import get_job_registry

			_jobs = get_job_registry()
			_jobs.cancel_wake(session_id)
			_jobs.restore_wake(session_id)
		except Exception:  # noqa: BLE001
			pass

	# 41 号：记录最近一次人类请求的模型环境（仅内存、随进程消失），供 goal 轮
	# 合成提交复用——否则 driver 自调用无法过 Authorization 闸（401）。
	# 2026-09-05 修正：移到 busy 闸**之前**（首条消息被排队时 env 也要落位），
	# 且仅人类面记录（合成轮的 env 本就取自这份快照，回写是同值 no-op）。
	if _human_surface:
		try:
			from server.goal_round_driver import get_goal_round_driver

			get_goal_round_driver().note_request_env(
				session_id,
				{
					"model": body.model,
					"provider": provider,
					"base_url": base_url,
					"api_key": api_key,
					"thinking": (body.thinking or "disabled").strip().lower(),
					"reasoning_effort": (body.reasoning_effort or "").strip().lower(),
					"max_budget_usd": body.max_budget_usd,
					"context_limit": body.context_limit,
					"permission_preset": body.permission_preset,
					"permission_mode": body.permission_mode,
					"workspace": _workspace_for(session_id, body),
				},
			)
		except Exception:  # noqa: BLE001
			logging.getLogger(__name__).debug("note_request_env failed", exc_info=True)

	# TurnRunner 判活兜底：busy 租约被 stale 回收但 detached turn 仍在跑时，
	# 租约互斥会放行叠跑；runner 知道所有活 turn，此处拦下（同 409 语义）。
	from engine.turn_runner import get_turn_runner

	if get_turn_runner().is_running(session_id):
		return _busy_or_queue(
			session_id, body, user_text,
			media_refs=media_refs,
			message_id=user_message_id,
		)

	lease_id = _pool.try_begin(session_id)
	if lease_id is None:
		return _busy_or_queue(
			session_id, body, user_text,
			media_refs=media_refs,
			message_id=user_message_id,
		)

	cfg = ModelConfig(
		provider=provider,
		api_key=api_key,
		base_url=base_url,
		model=body.model,
		thinking=(body.thinking or "disabled").strip().lower(),
		reasoning_effort=(body.reasoning_effort or "").strip().lower(),
		max_budget_usd=body.max_budget_usd,
		context_limit=body.context_limit,
		max_tokens=body.max_tokens,
	)
	# 42 号：人类下一轮开工时的 T_now 补投——一次性摘出 pending 完成通知
	# 摘要并 set 进请求级 contextvar（pre_llm_inject 强挂块消费）。
	# 注入即出队：错放（turn 未开起来）与 settlement 同风险，P0 接受。
	# P1：inbox 投递轮跳过 jobs digest 注入（省 input token）。
	if _human_surface and not _inbox_surface:
		try:
			from permissions.policy import set_pending_jobs_digest
			from server.job_registry import get_job_registry

			set_pending_jobs_digest(get_job_registry().pending_digest(session_id))
		except Exception:  # noqa: BLE001
			pass
	try:
		engine = _engine_for(
			session_id,
			cfg,
			initial_messages=prior_messages or None,
			workspace=_workspace_for(session_id, body),
			permission_preset=body.permission_preset,
		)
	except HTTPException:
		_pool.end(session_id, lease_id)
		raise
	except Exception as e:  # noqa: BLE001
		_pool.end(session_id, lease_id)
		raise api_error(500, friendly_error(e), "server_error") from e

	# #4：在 get_or_create 窗口内点击停止 — 记下标志；主路径靠 submit 携带，
	# 多 Agent 靠 stop_requested。仍 interrupt 一次以打断可能残留的旧回合。
	stop_requested = _pool.take_pending_interrupt(session_id)
	if stop_requested:
		engine.interrupt()

	async def event_stream() -> AsyncIterator[bytes]:
		from engine.turn_runner import get_turn_runner

		runner = get_turn_runner()
		# T31：模式 durable SSOT —— 请求体是投影，会话 durable 记录为准。
		set_permission_mode(body.permission_mode)
		eff = _effective_request_modes(engine, body)
		set_agent_mode(eff["agent_mode"])
		set_output_compact(eff["output_compact"])
		set_output_mode(eff["output_mode"])
		set_code_compact(eff["code_compact"])
		set_code_mode(eff["code_mode"])
		set_browser_preview_url(body.browser_preview_url)
		set_searxng_url(body.searxng_url)
		set_side_mode(bool(body.side))
		# T35：入口面标识（默认 gui；tui/remote 由客户端经 X-Xeyo-Surface 上报）。
		set_surface(x_xeyo_surface)
		envelope_gen = EventIdGenerator()
		turn_id = uuid.uuid4().hex[:12]

		# Resume cue：结构化续跑，而非裸「继续」口令。
		# P1：inbox 投递轮是真实用户消息（含跨回合排队），不做 resume 富化——
		# warm engine 历史已含目标，富化只会占 token（省钱第二杠杆）。
		resume_cue = _is_multi_agent_resume_cue(user_text) and not _inbox_surface
		submit_text = user_text
		goal_for_snap = user_text
		# 修订2（设计32）：续跑富化指令改走 submit_options.resume_directive →
		# T_now 投影-only 送达；落库与 GUI 气泡只存真实用户文本（如「继续」）。
		# 旧行为（富化长文落库成 user 消息）是跨任务锚定的残留通道。
		resume_directive_text = ""
		if resume_cue:
			# 41 号（38 号触发点 #4 补接线）：blocked goal 经 resume cue 恢复
			# active（清 blocked_reason）；是否重新 armed 由用户显式操作，不自动。
			try:
				from engine.goal_state import GoalStore as _GS

				_ws = str(
					(getattr(engine, "config", None) or {}).get("cwd") or ""
				).strip()
				if _ws:
					_g = _GS(_ws).current(session_id)
					if _g is not None and _g.status == "blocked":
						await _GS(_ws).transition_async(
							_g.goal_id, "active", revision=_g.revision
						)
						_stream_log.info(
							"goal resumed from blocked session=%s goal=%s",
							session_id,
							_g.goal_id,
						)
			except Exception:  # noqa: BLE001
				pass
			goal = _previous_user_goal(body.messages)
			working = getattr(getattr(engine, "_session", None), "working", None)
			todos = list(getattr(working, "todos", None) or [])
			prev_snap = None
			try:
				from engine.turn_snapshot import hydrate as hydrate_turn

				prev_snap = hydrate_turn(session_id)
			except Exception:  # noqa: BLE001
				prev_snap = None
			if not goal and prev_snap is not None:
				goal = prev_snap.goal_text or ""
			goal_for_snap = goal or (prev_snap.goal_text if prev_snap else "") or user_text
			resume_directive_text = _build_enriched_resume_prompt(
				user_cue=user_text,
				goal=goal,
				todos=todos,
				stop_reason=(prev_snap.stop_reason if prev_snap else ""),
				active_agents=(prev_snap.active_agent_ids if prev_snap else None),
				round_info=goal_round,
			)
			_stream_log.info(
				"resume_cue session=%s turn_id=%s goal_chars=%s",
				session_id,
				turn_id,
				len(goal or ""),
			)

		# T9：非续跑且无绑定 → create+bind 目标（单写、try/except 降级，绝不阻塞主路径）。
		# XEYO_GOAL_AUTO_CREATE（默认 0）：生产默认**不自动建 goal**——目标只在用户
		# 显式新建（GUI「+ 新建目标」/ PATCH action=new）后存在，GoalDock 随之出现，
		# 显式建目标、State-not-scheduling。设 1 可回到「每条消息自动建
		# 绑定」的旧行为（隔离/e2e 如需确定性可显式关闭，见 playwright.config.ts）。
		_goal_auto = os.environ.get("XEYO_GOAL_AUTO_CREATE", "0").strip().lower()
		if (
			not resume_cue
			and not _inbox_surface  # P1：inbox 投递轮不自动建 goal（免副作用与调用）
			and _goal_auto not in ("0", "false", "no", "off")
			and (user_text or "").strip()
		):
			try:
				from engine.goal_state import GoalStore

				ws = str((getattr(engine, "config", None) or {}).get("cwd") or "").strip()
				if ws:
					gstore = GoalStore(ws)
					if gstore.current(session_id) is None:
						# async 路径用 create_and_bind_async：blocking 的
						# ``create``/``bind`` 用 _run 会命中「running loop」报错并
						# 被外层吞掉（目标从未落盘/绑定，整条 goal 链失效）。
						await gstore.create_and_bind_async(
							title=(user_text or "")[:48],
							text=user_text or "",
							owner=session_id,
							origin="submit",
							session_id=session_id,
						)
			except Exception:  # noqa: BLE001
				pass

		# 清理遗留 scheduler checkpoint：仅非续跑口令时清，避免「继续」误伤。
		# P1：inbox 投递轮不清 checkpoint（它是真实用户消息，非新任务的「继续」）。
		if not resume_cue and not _inbox_surface:
			try:
				from engine.scheduler import (
					checkpoint_is_incomplete,
					clear_scheduler_checkpoint,
					read_scheduler_checkpoint,
				)

				ws = str(
					(getattr(engine, "config", None) or {}).get("cwd")
					or _pool.session_cwd(session_id)
					or "."
				)
				ckpt_old = read_scheduler_checkpoint(ws, session_id)
				if checkpoint_is_incomplete(ckpt_old):
					clear_scheduler_checkpoint(ws, session_id)
			except Exception:  # noqa: BLE001
				pass

		submit_options: dict[str, Any] = {
			"agent_mode": eff["agent_mode"],
			"stop_requested": bool(stop_requested),
			"multi_agent": bool(body.multi_agent),
		}
		if resume_directive_text:
			submit_options["resume_directive"] = resume_directive_text
		if media_refs:
			submit_options["images"] = media_refs
		if user_message_id:
			submit_options["user_message_id"] = user_message_id

		def _id(xy: dict[str, Any]) -> dict[str, Any]:
			return {
				**xy,
				"schema_version": "1.0",
				"session_id": session_id,
				"turn_id": turn_id,
				"event_id": envelope_gen.next(),
			}

		async def _producer() -> AsyncIterator[tuple[int, bytes, str]]:
			"""Detached producer：与 HTTP 连接无关；转换 engine 事件为 SSE 帧。"""
			full = ""
			done_sent = False
			try:
				# 41 号：goal 投影帧（whole-value）——turn 起点同步 goal + driver
				# 态（GUI 另有事件驱动刷新与轻量轮询补 settlement 后的变化）。
				try:
					from engine.goal_state import GoalStore as _GS
					from server.goal_round_driver import (
						get_goal_round_driver as _get_driver,
					)

					_ws = str(
						(getattr(engine, "config", None) or {}).get("cwd") or ""
					).strip()
					_g = _GS(_ws).current(session_id) if _ws else None
					if _g is not None:
						_xy = _id({
							"type": "goal",
							"goal": _g.to_dict(),
							"driver": _get_driver().snapshot(session_id),
						})
						yield (
							int(_xy["event_id"]),
							_xy_chunk(_xy, model=body.model).encode("utf-8"),
							"goal",
						)
				except Exception:  # noqa: BLE001
					pass
				# 42 号：jobs whole-value 帧（turn start 播种；owner turn 存活
				# 期内的结算变化靠 GUI 对 GET /jobs 轻量轮询补齐）。
				try:
					from server.job_registry import get_job_registry

					_jobs_reg = get_job_registry()
					if _jobs_reg.version() > 0:
						_xy = _id({
							"type": "jobs",
							"jobs": _jobs_reg.snapshot_list(session_id),
							"wake_budget_left": _jobs_reg.wake_budget_left(session_id),
						})
						yield (
							int(_xy["event_id"]),
							_xy_chunk(_xy, model=body.model).encode("utf-8"),
							"jobs",
						)
				except Exception:  # noqa: BLE001
					pass
				# T5：会话标题——首个 sidecar 缺失时即时落盘并推 SSE 帧；
				# pinned/enhanced 不重推。后台 LLM 增强（可选）失败静默。
				try:
					from engine.title import (
						ensure_instant_title,
						fire_and_forget_enhance,
						read_title,
					)
					from model.openai_compat import OpenAICompatClient

					_existing = read_title(session_id)
					_entry = ensure_instant_title(session_id, user_text)
					if _existing is None or str(_existing.get("title") or "") != str(
						_entry.get("title") or ""
					):
						_xy = _id({
							"type": "title",
							"title": str(_entry.get("title") or ""),
							"pinned": bool(_entry.get("pinned")),
							"enhanced": bool(_entry.get("enhanced")),
						})
						yield (
							int(_xy["event_id"]),
							_xy_chunk(_xy, model=body.model).encode("utf-8"),
							"title",
						)
					if _existing is None and cfg.api_key:
						# 仅首个 sidecar 缺失时派发一次后台增强；失败保留即时标题。
						_title_client = OpenAICompatClient(
							api_key=cfg.api_key,
							base_url=cfg.base_url,
							model=cfg.model,
							provider=cfg.provider,
							thinking="disabled",
							reasoning_effort="",
							session_id=session_id or "",
						)
						fire_and_forget_enhance(session_id, user_text, _title_client)
				except Exception:  # noqa: BLE001
					pass
				async for ev in engine.submit(submit_text, options=submit_options):
					frames: list[tuple[int, bytes, str]] = []
					if isinstance(ev, AssistantDelta):
						full += ev.text
						eid = envelope_gen.next()
						frames.append((
							eid,
							_openai_chunk(ev.text, model=body.model).encode("utf-8"),
							"delta",
						))
					elif isinstance(ev, ReasoningDelta):
						if ev.text:
							xy = _id({"type": "reasoning_delta", "text": ev.text})
							frames.append((
								int(xy["event_id"]),
								_xy_chunk(xy, model=body.model).encode("utf-8"),
								"reasoning_delta",
							))
					elif isinstance(ev, ToolCallEvent):
						xy_call: dict[str, Any] = {
							"type": "tool_call",
							"name": ev.name,
							"input": _sanitize_tool_input_for_ui(ev.input),
						}
						if ev.tool_use_id:
							xy_call["tool_use_id"] = ev.tool_use_id
						xy = _id(xy_call)
						frames.append((
							int(xy["event_id"]),
							_xy_chunk(xy, model=body.model).encode("utf-8"),
							"tool_call",
						))
					elif isinstance(ev, ToolProgressEvent):
						xy_payload = getattr(ev, "xy", None)
						if isinstance(xy_payload, dict) and xy_payload.get("type"):
							xy = _id(dict(xy_payload))
						else:
							xy = _id({
								"type": "tool_progress",
								"name": ev.name,
								"tool_use_id": ev.tool_use_id,
								"message": ev.message,
								"elapsed_ms": int(ev.elapsed_ms or 0),
							})
						frames.append((
							int(xy["event_id"]),
							_xy_chunk(xy, model=body.model).encode("utf-8"),
							str(xy.get("type") or "tool_progress"),
						))
					elif isinstance(ev, ToolResultEvent):
						xy = {
							"type": "tool_result",
							"name": ev.name,
							"output": ev.output,
							"is_error": bool(ev.is_error),
						}
						if ev.tool_use_id:
							xy["tool_use_id"] = ev.tool_use_id
						if ev.todos is not None:
							xy["todos"] = ev.todos
						ui_payload = getattr(ev, "ui", None)
						if isinstance(ui_payload, dict):
							xy["ui"] = ui_payload
						xy = _id(xy)
						frames.append((
							int(xy["event_id"]),
							_xy_chunk(xy, model=body.model).encode("utf-8"),
							"tool_result",
						))
					elif isinstance(ev, LlmRetryEvent):
						# 44 号：重试调度决策帧（非 surface，不进 transcript）。
						xy = _id({
							"type": "llm_retry",
							"attempt": int(ev.attempt),
							"next_retry_ms": int(ev.next_retry_ms),
							"code": ev.code,
						})
						if ev.message:
							xy["message"] = ev.message
						if ev.provider:
							xy["provider"] = ev.provider
						if ev.model:
							xy["model"] = ev.model
						frames.append((
							int(xy["event_id"]),
							_xy_chunk(xy, model=body.model).encode("utf-8"),
							"llm_retry",
						))
					elif isinstance(ev, LlmRetryStartedEvent):
						# 44 号：重试实际开始帧（非 surface）。
						xy = _id({
							"type": "llm_retry_started",
							"attempt": int(ev.attempt),
						})
						if ev.provider:
							xy["provider"] = ev.provider
						if ev.model:
							xy["model"] = ev.model
						frames.append((
							int(xy["event_id"]),
							_xy_chunk(xy, model=body.model).encode("utf-8"),
							"llm_retry_started",
						))
					elif isinstance(ev, FinalEvent):
						if not full and ev.text:
							eid = envelope_gen.next()
							frames.append((
								eid,
								_openai_chunk(ev.text, model=body.model).encode("utf-8"),
								"final_text",
							))
						eid = envelope_gen.next()
						frames.append((
							eid,
							_openai_chunk("", model=body.model, finish="stop").encode(
								"utf-8"
							),
							"final",
						))
					elif isinstance(ev, StoppedEvent):
						if ev.reason == "budget_usd":
							note = (
								f"\n\n[预算超限，已停止：本轮已用 "
								f"${ev.budget_used_usd or 0:.4f}"
								f"（上限 ${ev.budget_limit_usd or 0:.4f}）]\n"
							)
						elif ev.reason == "aborted" and ev.interrupted:
							note = "\n\n[stopped: aborted (interrupted)]\n"
						else:
							note = f"\n\n[stopped: {ev.reason}]\n"
						eid = envelope_gen.next()
						frames.append((
							eid,
							_openai_chunk(note, model=body.model).encode("utf-8"),
							"stopped",
						))
						eid = envelope_gen.next()
						frames.append((
							eid,
							_openai_chunk("", model=body.model, finish="stop").encode(
								"utf-8"
							),
							"stopped_finish",
						))
					elif isinstance(ev, UsageEvent):
						xy = {
							"type": "usage",
							"prompt_tokens": ev.prompt_tokens,
							"completion_tokens": ev.completion_tokens,
							"cache_hit_tokens": ev.cache_hit_tokens,
							"cache_miss_tokens": ev.cache_miss_tokens,
							"tokens": ev.tokens,
							"used_tokens": ev.used_tokens,
							"usd": ev.usd,
							"used_usd": ev.used_usd,
							"cny": ev.cny,
							"used_cny": ev.used_cny,
							"cost_source": ev.cost_source,
							"usd_limit": ev.usd_limit,
						}
						if ev.context_tokens is not None:
							xy["context_tokens"] = ev.context_tokens
						if ev.context_limit is not None:
							xy["context_limit"] = ev.context_limit
						if ev.context_breakdown:
							xy["context_breakdown"] = ev.context_breakdown
						xy["compact_cursor"] = int(ev.compact_cursor or 0)
						xy["last_action"] = str(ev.last_action or "")
						xy["c2_summary_chars"] = int(ev.c2_summary_chars or 0)
						xy = _id(xy)
						frames.append((
							int(xy["event_id"]),
							_xy_chunk(xy, model=body.model).encode("utf-8"),
							"usage",
						))
					elif isinstance(ev, PermissionPendingEvent):
						xy = _id({
							"type": "permission_pending",
							"request_id": ev.request_id,
							"tool_name": ev.tool_name,
							"input": _sanitize_tool_input_for_ui(ev.tool_input),
							"reason": ev.reason,
							"prompt": ev.prompt,
							"path": ev.path,
							"expires_at": ev.expires_at,
							"choices": list(ev.choices or []),
							"peer_summary": ev.peer_summary or "",
							"intent": ev.intent,
						})
						frames.append((
							int(xy["event_id"]),
							_xy_chunk(xy, model=body.model).encode("utf-8"),
							"permission_pending",
						))
					elif isinstance(ev, PermissionResolvedEvent):
						xy = _id({
							"type": "permission_resolved",
							"request_id": ev.request_id,
							"approved": bool(ev.approved),
							"actor": ev.actor,
							"reason": ev.reason,
							"resolved_at": ev.resolved_at,
							"choice": ev.choice or "",
						})
						frames.append((
							int(xy["event_id"]),
							_xy_chunk(xy, model=body.model).encode("utf-8"),
							"permission_resolved",
						))
					elif isinstance(ev, AskUserPendingEvent):
						xy = _id({
							"type": "ask_user_pending",
							"request_id": ev.request_id,
							"session_id": ev.session_id,
							"turn_id": ev.turn_id,
							"question": ev.question,
							"options": ev.options,
							"default": ev.default,
							"questions": ev.questions,
							"expires_at": ev.expires_at,
						})
						frames.append((
							int(xy["event_id"]),
							_xy_chunk(xy, model=body.model).encode("utf-8"),
							"ask_user_pending",
						))
					elif isinstance(ev, AskUserResolvedEvent):
						xy = _id({
							"type": "ask_user_resolved",
							"request_id": ev.request_id,
							"answer": ev.answer,
							"actor": ev.actor,
							"timeout": bool(ev.timeout),
							"resolved_at": ev.resolved_at,
						})
						frames.append((
							int(xy["event_id"]),
							_xy_chunk(xy, model=body.model).encode("utf-8"),
							"ask_user_resolved",
						))
					elif isinstance(ev, PlanPendingEvent):
						xy = _id({
							"type": "plan_pending",
							"request_id": ev.request_id,
							"session_id": ev.session_id,
							"turn_id": ev.turn_id,
							"plan": ev.plan,
							"expires_at": ev.expires_at,
						})
						frames.append((
							int(xy["event_id"]),
							_xy_chunk(xy, model=body.model).encode("utf-8"),
							"plan_pending",
						))
					elif isinstance(ev, PlanResolvedEvent):
						xy = _id({
							"type": "plan_resolved",
							"request_id": ev.request_id,
							"approved": bool(ev.approved),
							"actor": ev.actor,
							"reason": ev.reason,
							"resolved_at": ev.resolved_at,
						})
						frames.append((
							int(xy["event_id"]),
							_xy_chunk(xy, model=body.model).encode("utf-8"),
							"plan_resolved",
						))
					elif isinstance(ev, TaskStateEvent):
						xy = _id({
							"type": "task_state_changed",
							"task_status": ev.task_status,
							"current_tool": ev.current_tool,
							"interruptible": bool(ev.interruptible),
							"error": ev.error,
						})
						frames.append((
							int(xy["event_id"]),
							_xy_chunk(xy, model=body.model).encode("utf-8"),
							"task_state_changed",
						))
					elif isinstance(ev, SteerDeliveredEvent):
						xy = _id({
							"type": "steer_delivered",
							"count": int(ev.count or 0),
							"message_ids": list(ev.message_ids or ()),
						})
						frames.append((
							int(xy["event_id"]),
							_xy_chunk(xy, model=body.model).encode("utf-8"),
							"steer_delivered",
						))
					elif isinstance(ev, ContextCompressionEvent):
						xy = {
							"type": (
								"context_compression_start"
								if ev.phase == "start"
								else "context_compression_complete"
							),
							"source": ev.source,
						}
						if ev.context_tokens is not None:
							xy["context_tokens"] = ev.context_tokens
						if ev.context_limit is not None:
							xy["context_limit"] = ev.context_limit
						xy = _id(xy)
						frames.append((
							int(xy["event_id"]),
							_xy_chunk(xy, model=body.model).encode("utf-8"),
							str(xy["type"]),
						))
					for item in frames:
						yield item
					# A2b（2026-09-09）：完成信号锚定「内容终结事件」而非 submit
					# 迭代自然排空。引擎契约：ResultEvent 是 submit_message 的
					# 最后一个事件（query_loop 不产它），其后只剩 finally 收尾
					# （transcript flush / memory 归档 / rewind After 快照+差量同步
					# +journal 终态 / revision commit），全部不产帧。因此此刻立即
					# 发 [DONE]——GUI 判定的回合完成不再被 rewind/memory 数百 ms
					# 收尾阻塞（「模型答完仍回复中」根因 #2）；runner/lease/settle
					# 语义零变化（收尾照常排空后才归还租约）。防御：若 ResultEvent
					# 后仍出现事件（引擎契约破坏），继续正常分发，不吞帧。
					if isinstance(ev, ResultEvent) and not done_sent:
						done_sent = True
						done_id = envelope_gen.next()
						yield (done_id, b"data: [DONE]\n\n", "done")
				if not done_sent:
					# 引擎契约破坏兜底：迭代自然排空却没产 ResultEvent →
					# 补发完成帧（等同旧行为），绝不让客户端空等。
					done_id = envelope_gen.next()
					yield (done_id, b"data: [DONE]\n\n", "done")
			except Exception as e:  # noqa: BLE001
				err_id = envelope_gen.next()
				yield (
					err_id,
					_sse_error(friendly_error(e), "model_error").encode("utf-8"),
					"error",
				)
				done_id = envelope_gen.next()
				yield (done_id, b"data: [DONE]\n\n", "done")
				_stream_log.warning(
					"turn_end session=%s turn_id=%s reason=error",
					session_id,
					turn_id,
					exc_info=True,
				)

		# ContextVar 在 create_task 时拷贝；HTTP finally 清 mode 不影响 producer。
		try:
			await runner.start(
				session_id=session_id,
				lease_id=lease_id,
				model=body.model,
				goal_text=goal_for_snap,
				user_message_id=user_message_id or "",
				producer=_producer,
				turn_id=turn_id,
			)
		except Exception:
			_pool.end(session_id, lease_id)
			raise

		# 订阅者：断连只停推流，不 interrupt / 不 pool.end。
		# 心跳：subscribe() 静默 12s 时 yield None（tick），这里发 ping，避免
		# FE 60s idle watchdog 误杀投影流。禁止 wait_for(__anext__)——超时取消
		# 会把 CancelledError 注入订阅生成器并拆毁它，SSE 在无 [DONE] 下提前 EOF。
		try:
			agen = runner.subscribe(session_id, cursor=0)
			while True:
				if drop_stream:
					# T29 测试钩子：断流（不补 [DONE]）→ 前端 SSE 无完成标记，
					# 触发「连接中断」banner。只停推流，绝不 interrupt / pool.end。
					runner.note_client_disconnect(session_id, turn_id)
					break
				try:
					frame = await agen.__anext__()
				except StopAsyncIteration:
					break
				if frame is None:
					if await request.is_disconnected():
						runner.note_client_disconnect(session_id, turn_id)
						break
					yield b": ping\n\n"
					continue
				if await request.is_disconnected():
					runner.note_client_disconnect(session_id, turn_id)
					break
				yield frame
		except asyncio.CancelledError:
			# HTTP 取消 ≠ 用户 Stop：turn 继续 detached。
			runner.note_client_disconnect(session_id, turn_id)
			return
		finally:
			# 不 cancel producer、不 pool.end（TurnRunner 终态负责）。
			set_permission_mode(None)
			set_output_compact(False)
			set_output_mode(None)
			set_code_compact(False)
			set_code_mode(None)
			set_browser_preview_url(None)
			set_searxng_url(None)
			set_side_mode(False)
			set_surface(None)

	if not body.stream:
		chunks: list[str] = []
		xy_events: list[dict[str, Any]] = []
		stream_error: str | None = None
		try:
			async for raw in event_stream():
				line = raw.decode("utf-8")
				if not line.startswith("data: ") or "[DONE]" in line:
					continue
				try:
					obj = json.loads(line[6:])
					# 非流式也必须暴露 SSE 错误帧（流式路径已处理）。
					err = obj.get("error")
					if isinstance(err, dict):
						stream_error = str(err.get("message") or err)
						continue
					if isinstance(obj.get("xy"), dict):
						xy_events.append(obj["xy"])
					delta = (obj.get("choices") or [{}])[0].get("delta") or {}
					if "content" in delta:
						chunks.append(str(delta["content"]))
				except Exception:
					pass
		except Exception:
			# TurnRunner 持有 lease；勿在此 pool.end，否则会与 detached turn 抢租约。
			raise
		if stream_error:
			raise api_error(502, stream_error, "model_error")
		# 非流式须等 turn 结束，否则只读到部分订阅帧。
		from engine.turn_runner import get_turn_runner as _gtr

		await _gtr().wait_done(session_id, timeout=600.0)
		text = "".join(chunks)
		return JSONResponse(
			{
				"id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
				"object": "chat.completion",
				"created": int(time.time()),
				"model": body.model,
				"choices": [
					{
						"index": 0,
						"message": {"role": "assistant", "content": text},
						"finish_reason": "stop",
					}
				],
				# 非流式客户端的结构化工具（#8）。
				"xy_events": xy_events,
			}
		)

	return StreamingResponse(
		event_stream(),
		media_type="text/event-stream",
		headers={
			"Cache-Control": "no-cache",
			"Connection": "keep-alive",
			"X-Accel-Buffering": "no",
		},
	)


# 旧版 bridge 兼容薄封装（供早期 bat 脚本使用）
class LegacyChatBody(BaseModel):
	sessionId: str
	text: str
	provider: str = "deepseek"
	model: str = "deepseek-chat"
	base_url: str | None = None
	# T33：body 不再接受 api_key（密钥只走 Authorization header / env / config）。


@router.post("/api/chat", response_model=None)
async def legacy_chat(
	request: Request,
	body: LegacyChatBody,
	authorization: str | None = Header(default=None),
):
	"""兼容垫片 → OpenAI completions。"""
	req = ChatCompletionRequest(
		model=body.model,
		messages=[ChatMessage(role="user", content=body.text)],
		stream=True,
		session_id=body.sessionId,
		provider=body.provider if body.provider in ("deepseek", "openai") else "deepseek",
		base_url=body.base_url,
	)
	auth = authorization
	return await chat_completions(
		request,
		req,
		authorization=auth,
		x_session_id=body.sessionId,
		x_provider=body.provider,
		x_base_url=body.base_url,
	)
