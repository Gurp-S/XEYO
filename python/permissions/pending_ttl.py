"""权限挂起超时与统一文案（T3）。

风险分级 TTL：
- 交互式提问（AskUserQuestion）→ 不超时（``None``），由用户显式关闭结束；
- 普通权限确认 → 180s（``PENDING_PANEL_TTL_SECONDS``）；
- 危险操作（reason/matched_rule 命中 danger/secret/protected）→ 60s；

统一结果文案（query_loop 组装 ToolResult 用）：
- rejected：用户显式拒绝；
- cancelled：面板关闭 / Esc / 停止按钮（outcome=aborted）；
- unavailable：审批不可用（超时或协调器缺失）。

审计配对：``permission.pending`` ↔ ``permission.resolved``（allow/deny 都记），
即计划中的 approval.asked/decided 对——命名以 permission.* 为准，不再双写。
"""

from __future__ import annotations

PENDING_PANEL_TTL_SECONDS = 180.0
PENDING_DANGER_TTL_SECONDS = 60.0

_DANGER_MARKERS = ("danger", "secret", "protected")

#: 统一文案（面向模型；GUI 另有中文渲染）。
REJECTED_COPY = (
	"Permission denied: the user explicitly rejected this action."
)
CANCELLED_COPY = (
	"Permission request cancelled: the user dismissed the approval panel "
	"before deciding."
)
UNAVAILABLE_COPY = (
	"Approval unavailable: the request timed out without a decision "
	"and was treated as rejected."
)


def ttl_for_request(
	*, reason: str = "", matched_rule: str = "", tool_name: str = ""
) -> float | None:
	"""按请求风险返回 TTL 秒数；``None`` = 不超时。"""
	blob = f"{reason} {matched_rule}".lower()
	if any(k in blob for k in _DANGER_MARKERS):
		return PENDING_DANGER_TTL_SECONDS
	return PENDING_PANEL_TTL_SECONDS


def intent_for(*, choices: tuple[str, ...] | list[str] | None = None) -> str:
	"""面板渲染意图：带 choices 的三选 = choice；否则 confirm。"""
	return "choice" if choices else "confirm"
