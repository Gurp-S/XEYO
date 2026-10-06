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
