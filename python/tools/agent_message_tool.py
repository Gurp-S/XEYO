"""``agent_send``：向**运行中**的子 agent 追加一条消息（park；其当前回合 settle 后同实例续跑）。

F5 落地：模型对后台 job 有 ``job_output``/``job_list``/``job_kill`` 三件套，
对子 agent 却只有 spawn 与 reuse（清侧链重跑）——缺「对既有工人说话」的动词
（Claude ``SendMessage`` / coordinator 的同形能力）。本工具补齐该动词。

语义边界（与引擎 live_agents 的 park 管线一致）：
- 只对**运行中**的 agent 生效；消息在其当前回合 settle 时消费，同实例续跑；
- 未运行/未知 agent → NOT_FOUND（对已结束 agent 的续聊属于 retry/reuse 面，
  本工具不做「写入 meta.pending_followups」那条人侧链路，避免两套身份混用）；
- owner 即安全边界：会话上下文里的 session_id（与 job 三件套同规）。
"""

from __future__ import annotations

from typing import Any

from engine.abort import AbortController
from tools.base_tool import ToolResult
from tools.error_taxonomy import INVALID_ARGUMENT, NOT_FOUND

AGENT_SEND_TOOL_NAME = "agent_send"

#: 与 HTTP follow-up 路由同档（inbox_registry 既有 2000 上限线）。
_MAX_TEXT_CHARS = 2000


def _session_id() -> str:
	try:
		from engine.workspace_context import get_workspace_context

		ctx = get_workspace_context()
		if ctx is not None and ctx.session_id:
			return str(ctx.session_id).strip()
	except Exception:  # noqa: BLE001
		pass
	return ""


class AgentSendTool:
	name = AGENT_SEND_TOOL_NAME

	@staticmethod
	def is_read_only() -> bool:
		return False

	@staticmethod
	def is_concurrency_safe() -> bool:
		return False

	def schema(self) -> dict[str, Any]:
		from engine.agent_runtime import enabled
		if enabled():
			return {"name": self.name, "description":
				"Durable message to a same-session agent_id or parent. Sender identity comes from the runtime. "
				"Messages arrive at model request boundaries; an inactive agent retains messages until resumed. "
				"message_id deduplicates retries; attempt_id rejects a replaced recipient execution.",
				"input_schema": {"type": "object", "properties": {
					"agent_id": {"type": "string"}, "text": {"type": "string", "maxLength": 8000},
					"message_id": {"type": "string"}, "attempt_id": {"type": "string"}},
					"required": ["agent_id", "text"]}}
		return {
			"name": self.name,
			"description": (
				"Send a follow-up to a running subagent (by agent_id). The message "
				"is parked and delivered when that agent's current turn settles; "
				"the same agent instance then continues."
			),
			"input_schema": {
				"type": "object",
				"properties": {
					"agent_id": {
						"type": "string",
						"description": "Subagent id to message",
					},
					"text": {
						"type": "string",
						"description": "Message text (max 2000 chars)",
					},
				},
				"required": ["agent_id", "text"],
			},
		}

	async def execute(
		self, input: dict[str, Any], abort: AbortController
	) -> ToolResult:
		from engine.agent_runtime import actor, enabled, result
		if enabled():
			import asyncio
			from engine.agent_run_store import AgentRunStore
			from engine.agent_identity import current_agent
			from engine.agent_io import owned_io
			abort.raise_if_aborted()
			sid, sender = actor()
			if not sid:
				return result({"error": "missing_session_identity"}, error=True)
			try:
				store = await asyncio.to_thread(AgentRunStore)
				identity = current_agent.get()
				item = await owned_io(store.send, sid, str(input.get("agent_id") or ""), sender,
					str(input.get("text") or ""), message_id=str(input.get("message_id") or ""),
					expected_attempt=str(input.get("attempt_id") or ""),
					sender_attempt=identity.attempt_id if identity else "")
				return result({"message_id": item["message_id"], "state": item["state"],
					"recipient": item["recipient"], "target_attempt": item["target_attempt"]})
			except Exception as exc:
				return result({"error": str(exc)}, error=True)
		agent_id = str(input.get("agent_id") or "").strip()
		text = str(input.get("text") or "").strip()
		if not agent_id or not text:
			return ToolResult(
				content="agent_id and text are required",
				is_error=True,
				status="error",
				error_kind=INVALID_ARGUMENT,
				retryable=False,
			)
		if len(text) > _MAX_TEXT_CHARS:
			return ToolResult(
				content=f"text too long (max {_MAX_TEXT_CHARS} chars)",
				is_error=True,
				status="error",
				error_kind=INVALID_ARGUMENT,
				retryable=False,
			)
		sid = _session_id()
		if not sid:
			return ToolResult(
				content="no session context",
				is_error=True,
				status="error",
				error_kind=INVALID_ARGUMENT,
				retryable=False,
			)
		try:
			from engine.live_agents import is_live_agent, post_to_agent
		except Exception:  # noqa: BLE001 — 无运行时（CLI in-process 外）→ 如实报未知
			return ToolResult(
				content=f"unknown or not-running agent: {agent_id}",
				is_error=True,
				status="error",
				error_kind=NOT_FOUND,
				retryable=False,
			)
		if not is_live_agent(sid, agent_id):
			return ToolResult(
				content=f"unknown or not-running agent: {agent_id}",
				is_error=True,
				status="error",
				error_kind=NOT_FOUND,
				retryable=False,
			)
		pending = post_to_agent(sid, agent_id, text, "")
		if pending < 0:
			return ToolResult(
				content="message rejected",
				is_error=True,
				status="error",
				error_kind=INVALID_ARGUMENT,
				retryable=False,
			)
		return ToolResult(
			content=(
				f"queued follow-up for agent {agent_id} ({pending} pending); "
				"delivered when its current turn settles"
			)
		)
