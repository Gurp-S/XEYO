/* eslint-disable */
/* 由 `py -3.11 -m server.export_stream_contract` 生成，请勿手改。
   后端帧名 / 请求体枚举的唯一真相：python/server/stream_contract.py
   与 python/server/routers/chat.py 的模型声明。 */

export const XY_ENVELOPE_KEY = "xy" as const;
export const CHUNK_EVENT_ID_KEY = "xeyo_event_id" as const;

export const STREAM_EVENT_TYPES = ["ask_user_pending", "ask_user_resolved", "context_compression_complete", "context_compression_start", "goal", "jobs", "llm_retry", "llm_retry_started", "multi_agent_delta", "multi_agent_progress", "multi_agent_task", "permission_pending", "permission_resolved", "plan_pending", "plan_resolved", "reasoning_delta", "steer_delivered", "stream_gap", "task_state_changed", "title", "tool_call", "tool_progress", "tool_result", "usage"] as const;
export type StreamEventType = (typeof STREAM_EVENT_TYPES)[number];

export const ACCEPT_EVENT_KEYS = {
	queued: ["delivery", "position", "queue_id", "queued"] as const,
	steered: ["delivery", "message_id", "queued", "steered"] as const,
} as const;
export type AcceptEventKind = keyof typeof ACCEPT_EVENT_KEYS;

export const CHAT_BODY_ENUMS = {
	agent_mode: ["agent", "ask", "plan"] as const,
	code_mode: ["full", "lite", "ultra"] as const,
	output_mode: ["full", "lite", "ultra"] as const,
	provider: ["anthropic", "deepseek", "fake", "local", "openai"] as const,
} as const;
