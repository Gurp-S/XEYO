from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Union

# 事件类型
"""
AssistantDelta   # 模型正在吐字
ToolCallEvent    # 准备调工具
ToolResultEvent  # 工具跑完
FinalEvent       # 本轮正常结束（无更多工具）
StoppedEvent     # 异常结束：aborted / max_turns / max_tool_calling / budget / budget_usd
UsageEvent       # 每轮模型调用的 token / USD（L1.2 设置页展示）
ResultEvent      # submit 回合结束（对齐 SDK type=result）
PermissionPendingEvent   # 危险/需确认工具请求：permission_ask 触发挂起
PermissionResolvedEvent  # 审批已确认/拒绝/超时
AskUserPendingEvent      # 助手向用户提问：ask_user 触发挂起（同构于权限挂起）
AskUserResolvedEvent     # 用户已作答/超时
PlanPendingEvent         # Plan 模式产出计划，等待用户确认
PlanResolvedEvent        # 用户已批准/拒绝/超时
TaskStateEvent           # 会话任务状态变化（queued/running/waiting_permission/...）
"""



@dataclass
class AssistantDelta:
	text: str
	type: str = "assistant_delta"


@dataclass
class ReasoningDelta:
	text: str
	type: str = "reasoning_delta"


@dataclass
class ToolCallEvent:
	name: str
	input: dict[str, Any]
	tool_use_id: str = ""
	# T13：tool_call.begin 元数据——参数摘要 + 是否与其它工具同批并行。
	input_summary: str = ""
	parallel: bool = False
	type: str = "tool_call"


@dataclass
class ToolProgressEvent:
	"""长工具执行中的心跳 / 进度（不写 transcript）。

	``xy``：可选旁路帧（如 Agent 工具的 multi_agent_task / delta / progress），
	由 chat SSE 原样转发；心跳帧保持 xy=None。
	"""

	name: str
	tool_use_id: str = ""
	message: str = ""
	elapsed_ms: int = 0
	xy: dict[str, Any] | None = None
	type: str = "tool_progress"


@dataclass
class ToolResultEvent:
	name: str
	output: str
	is_error: bool = False
	tool_use_id: str = ""
	"""可选的结构化 UI 载荷（例如 TodoWrite 清单）。"""
	todos: list[dict[str, str]] | None = None
	"""可选的 durable rewind operation id。"""
	operation_id: str | None = None
	"""桌面 UI 旁路（XeyoUI open_preview / open_panel / send_to_session）。"""
	ui: dict[str, Any] | None = None
	# T13：tool_call.end 元数据——执行耗时（ms）+ 是否发生 spill（tool-results 截断）。
	duration_ms: int = 0
	spilled: bool = False
	type: str = "tool_result"


@dataclass
class FinalEvent:
	text: str
	"""本轮累计（L1.2）：最后一次模型调用的 usage 快照。"""
	prompt_tokens: int = 0
	completion_tokens: int = 0
	cache_hit_tokens: int = 0
	cache_miss_tokens: int = 0
	usd: float = 0.0
	used_usd: float = 0.0
	usd_limit: float | None = None
	type: str = "final"


@dataclass
class StoppedEvent:
	reason: Literal["max_turns", "max_tool_calling", "aborted", "budget", "budget_usd", "wall"]
	"""L1.2：超 USD 上限时附带本轮金额，便于 UI 提示。"""
	budget_used_usd: float | None = None
	budget_limit_usd: float | None = None
	# 44 号：中断锚——abort 时已有部分输出（「用户看到的必须入史」）。
	interrupted: bool = False
	type: str = "stopped"


@dataclass
class UsageEvent:
	"""一轮模型调用的真实消耗（来自厂商响应 usage）。"""

	prompt_tokens: int = 0
	completion_tokens: int = 0
	cache_hit_tokens: int = 0
	cache_miss_tokens: int = 0
	tokens: int = 0
	used_tokens: int = 0
	usd: float = 0.0
	used_usd: float = 0.0
	cny: float = 0.0
	used_cny: float = 0.0
	cost_source: str = "estimate"
	usd_limit: float | None = None
	# 当前模型请求实际消耗的 prompt/context token 数；来自上游 usage。
	context_tokens: int | None = None
	# 仅在厂商或运行配置提供可靠上限时发送，未知时保持 None。
	context_limit: int | None = None
	# 发送给模型的上下文构成（按内容分类的 token 数），供前端画分段用量条。
	# 形如 [{category, label, tokens}]；sum(tokens) 约等于 context_tokens。
	context_breakdown: list[dict[str, Any]] | None = None
	# C2 压缩态（来自 WorkingSnapshot），供用量预览感知。
	compact_cursor: int = 0
	last_action: str = ""
	c2_summary_chars: int = 0
	type: str = "usage"


@dataclass
class ContextCompressionEvent:
	"""后端真实 Context 压缩生命周期，不代表普通 token 流。"""

	phase: Literal["start", "complete"]
	source: Literal["automatic", "manual"] = "automatic"
	context_tokens: int | None = None
	context_limit: int | None = None
	type: str = "context_compression"


@dataclass
class SteerDeliveredEvent:
	"""运行中输入的用户消息已在**边界**投递进历史的回执（管道 1）。

	只放事实：条数 + 客户端消息 id。不回灌文本——文本客户端本地已有，
	回灌反而会跟用户在输入框里的编辑打架。
	"""

	count: int = 0
	message_ids: tuple[str, ...] = ()
	type: str = "steer_delivered"


@dataclass
class ResultEvent:
	"""一轮 submit 的结束信号（flush 之后 yield）。"""

	subtype: Literal[
		"success",
		"error_max_turns",
		"error_max_tool_calling",
		"aborted",
		"budget",
		"budget_usd",
		"error_during_execution",
	]
	result: str = ""
	is_error: bool = False
	duration_ms: int = 0
	num_turns: int = 0
	session_id: str = ""
	stop_reason: str | None = None
	budget_used_usd: float | None = None
	budget_limit_usd: float | None = None
	type: str = "result"


@dataclass
class PermissionPendingEvent:
	"""工具需要用户确认：该 turn 挂起，等待 resolve_permission。

	前端/微信据此渲染可读的确认框；同一 request_id 只能被处理一次。
	三选 peer ASK 时带 choices / peer_summary。
	"""

	request_id: str
	tool_name: str
	tool_input: dict[str, Any]
	reason: str
	prompt: str
	path: str | None = None
	expires_at: float | None = None
	choices: list[str] = field(default_factory=list)
	peer_summary: str = ""
	#: T3 面板渲染意图：confirm（普通确认）/ choice（三选冲突）/ plan-review。
	intent: str = "confirm"
	type: str = "permission_pending"


@dataclass
class PermissionResolvedEvent:
	"""审批结果：确认 / 拒绝 / 提醒 / 超时，唤醒被挂起的工具调用。"""

	request_id: str
	approved: bool
	actor: str = ""
	reason: str = ""
	resolved_at: float | None = None
	#: allow / deny / remind / timeout
	choice: str = ""
	type: str = "permission_resolved"


@dataclass
class AskUserPendingEvent:
	"""助手向用户提问：该 turn 挂起，等待用户作答。

	与权限挂起同构，但等待的是用户答案文本（自由输入或选项之一）。
	前端据此渲染可作答的输入框；同一 request_id 只能被处理一次。
	"""

	request_id: str
	session_id: str
	turn_id: str
	question: str
	options: list[str] = field(default_factory=list)
	default: str | None = None
	#: 结构化分题口径（[{question, options[{label,description}], multiSelect, default}]）；
	#: 空列表 = legacy 单问题，GUI 回落 question/options 平铺渲染。
	questions: list[dict] = field(default_factory=list)
	expires_at: float | None = None
	type: str = "ask_user_pending"


@dataclass
class AskUserResolvedEvent:
	"""用户对提问的作答结果：已作答 / 超时。"""

	request_id: str
	answer: str = ""
	actor: str = ""
	timeout: bool = False
	resolved_at: float | None = None
	type: str = "ask_user_resolved"


@dataclass
class PlanPendingEvent:
	"""Plan 模式产出计划：该 turn 挂起，等待用户确认执行。"""

	request_id: str
	session_id: str
	turn_id: str
	plan: str
	expires_at: float | None = None
	type: str = "plan_pending"


@dataclass
class PlanResolvedEvent:
	"""Plan 确认结果：批准 / 拒绝 / 超时，供前端关闭确认面板。"""

	request_id: str
	approved: bool
	actor: str = ""
	reason: str = ""
	resolved_at: float | None = None
	type: str = "plan_resolved"


@dataclass
class TaskStateEvent:
	"""会话任务状态流转事件，供所有入口（桌面/远程/微信）消费。"""

	session_id: str
	turn_id: str
	task_status: str
	current_tool: str | None = None
	interruptible: bool = True
	error: str | None = None
	type: str = "task_state_changed"


@dataclass
class LlmRetryEvent:
	"""44 号：LLM 请求失败后的重试调度决策（``llm/retry``，非 surface 事件）。

	UI 依据 ``next_retry_ms`` 渲染倒计时；``code`` 为 ``classify_llm_failure``
	的稳定错误码；不进 transcript / 消息历史。
	"""

	attempt: int
	next_retry_ms: int
	code: str
	message: str = ""
	provider: str = ""
	model: str = ""
	type: str = "llm_retry"


@dataclass
class LlmRetryStartedEvent:
	"""44 号：重试实际开始（``llm/retry-started``，非 surface 事件）。"""

	attempt: int
	provider: str = ""
	model: str = ""
	type: str = "llm_retry_started"


EngineEvent = Union[
	AssistantDelta,
	ReasoningDelta,
	ToolCallEvent,
	ToolProgressEvent,
	ToolResultEvent,
	FinalEvent,
	StoppedEvent,
	UsageEvent,
	ContextCompressionEvent,
	ResultEvent,
	PermissionPendingEvent,
	PermissionResolvedEvent,
	AskUserPendingEvent,
	AskUserResolvedEvent,
	PlanPendingEvent,
	PlanResolvedEvent,
	TaskStateEvent,
	LlmRetryEvent,
	LlmRetryStartedEvent,
]
