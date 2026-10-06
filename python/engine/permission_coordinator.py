"""权限协调器：发起 / 恢复 / 超时权限请求。

把 SessionTaskState 与 PendingPermissionStore 缝合起来：
- request：创建 pending 请求、状态转 waiting_permission、发布 PermissionPendingEvent。
- wait：等待确认（超时按拒绝处理），状态回 running、发布 PermissionResolvedEvent。
- resolve：外部（前端/微信）确认或拒绝（审计由 store.resolve 统一写）。

已接入 query_loop / ToolRegistry.run：策略 ASK 时挂起，用户确认后以 skip_ask 重跑。
三选 peer ASK：wait 返回 allow / deny / remind / timeout。
"""

from __future__ import annotations

import time

from typing import Any, Callable

from audit.log import default_audit_log
from engine.task_state import SessionTaskState
from msgtypes.events import (
	PermissionPendingEvent,
	PermissionResolvedEvent,
)
from permissions.pending_ttl import intent_for
from permissions.store import (
	USER_CHOICE_ALLOW,
	USER_CHOICE_DENY,
	USER_CHOICE_REMIND,
	PendingPermissionStore,
)


class PermissionCoordinator:
	"""按会话持有 pending 权限与任务状态衔接。"""

	def __init__(
		self,
		*,
		store: PendingPermissionStore,
		task_state: SessionTaskState,
		session_id: str,
		turn_id: str = "",
		on_event: Callable[[Any], None] | None = None,
	) -> None:
		self.store = store
		self.task_state = task_state
		self.session_id = session_id
		self.turn_id = turn_id
		self.on_event = on_event

	def request(
		self,
		*,
		tool_name: str,
		tool_input: dict[str, Any],
		reason: str,
		prompt: str,
		turn_id: str | None = None,
		matched_rule: str = "",
		rule_id: str = "",
		reason_code: str = "",
		resource: str = "",
		command_summary: str = "",
		choices: tuple[str, ...] | list[str] | None = None,
		peer_summary: str = "",
		mcp_target: str = "",
		permission_snapshot_id: str = "",
		tool_use_id: str = "",
		model_request_id: str = "",
		projection_id: str = "",
	) -> str:
		tid = turn_id or self.turn_id
		item = self.store.create(
			session_id=self.session_id,
			turn_id=tid,
			tool_name=tool_name,
			tool_input=tool_input,
			reason=reason,
			prompt=prompt,
			matched_rule=matched_rule,
			command_summary=command_summary,
			choices=choices,
			peer_summary=peer_summary,
			mcp_target=mcp_target,
			permission_snapshot_id=permission_snapshot_id,
			tool_use_id=tool_use_id,
			model_request_id=model_request_id,
			projection_id=projection_id,
		)
		self.task_state.set_status(
			"waiting_permission", turn_id=tid, current_tool=tool_name, interruptible=False
		)
		fields: dict[str, Any] = {
			"session_id": self.session_id,
			"turn_id": tid,
			"request_id": item.request_id,
			"tool_name": tool_name,
			"reason": reason,
			"matched_rule": matched_rule or "",
			"rule_id": rule_id or matched_rule or "",
			"reason_code": reason_code or "",
			"resource": resource or "",
			"permission_snapshot_id": permission_snapshot_id or "",
			"expires_at": item.expires_at,
		}
		if command_summary:
			fields["command_summary"] = command_summary
		for name, value in (
			("tool_use_id", tool_use_id),
			("model_request_id", model_request_id),
			("projection_id", projection_id),
		):
			if value:
				fields[name] = value
		if item.choices:
			fields["choices"] = list(item.choices)
		default_audit_log().record("permission.pending", **fields)
		self._emit(
			PermissionPendingEvent(
				request_id=item.request_id,
				tool_name=tool_name,
				tool_input=tool_input,
				reason=reason,
				prompt=prompt,
				expires_at=item.expires_at,
				choices=list(item.choices),
				peer_summary=item.peer_summary or "",
				intent=intent_for(choices=item.choices),
			)
		)
		return item.request_id

	async def wait(self, request_id: str, timeout: float | None = None) -> str:
		"""等待用户选择，返回 allow / deny / remind / timeout。"""
		item = await self.store.wait(request_id, timeout=timeout)
		if item is None:
			# 项已经不在了（过期剪枝 / 会话清理把它摘掉），不是"用户没答"那么轻：
			# 这一支原先直接 return，于是 task_state 永远停在
			# ``waiting_permission`` + ``interruptible=False``（request() 设的），
			# GUI 的授权卡不消失、连中断都被判不可打断，
			# 且这一枪的审批终态**一条 resolved 审计都没留下**。
			# 这里补齐的是状态与留痕，判定不变（与超时档同为拒绝）。
			default_audit_log().record(
				"permission.resolved",
				session_id=self.session_id,
				turn_id=self.turn_id,
				request_id=request_id,
				tool_name="",
				reason="",
				matched_rule="",
				approved=False,
				user_choice=USER_CHOICE_DENY,
				actor="",
				outcome="timeout",
				pending_absent=True,
			)
			self.task_state.set_status("running", current_tool=None, interruptible=True)
			self._emit(
				PermissionResolvedEvent(
					request_id=request_id,
					approved=False,
					actor="",
					reason="timeout",
					choice="timeout",
				)
			)
			return "timeout"
		if not item.resolved:
			# 超时：store.resolve 未调用，此处补 resolved 审计。
			fields: dict[str, Any] = {
				"session_id": self.session_id,
				"turn_id": self.turn_id,
				"request_id": request_id,
				"tool_name": item.tool_name,
				"reason": item.reason,
				"matched_rule": item.matched_rule,
				"approved": False,
				"user_choice": USER_CHOICE_DENY,
				"actor": "",
				"outcome": "timeout",
			}
			if item.command_summary:
				fields["command_summary"] = item.command_summary
			for name in ("tool_use_id", "model_request_id", "projection_id"):
				value = getattr(item, name, "")
				if value:
					fields[name] = value
			default_audit_log().record("permission.resolved", **fields)
			choice = "timeout"
			approved = False
			reason = "timeout"
		else:
			choice = (item.user_choice or "").strip().lower()
			if choice not in (
				USER_CHOICE_ALLOW,
				USER_CHOICE_DENY,
				USER_CHOICE_REMIND,
			):
				choice = (
					USER_CHOICE_ALLOW if item.approved else USER_CHOICE_DENY
				)
			approved = choice == USER_CHOICE_ALLOW
			reason = item.outcome or "user_decided"
		self.task_state.set_status("running", current_tool=None, interruptible=True)
		self._emit(
			PermissionResolvedEvent(
				request_id=request_id,
				approved=approved,
				actor=item.actor or "",
				reason=reason,
				choice=choice,
			)
		)
		return choice

	def cancel_pending(self, *, actor: str = "abort") -> int:
		"""把本会话所有未决权限请求按取消处理并唤醒等待者（interrupt 路径）。"""
		return self.store.cancel_pending_for_session(self.session_id, actor=actor)

	def resolve(
		self,
		request_id: str,
		approved: bool,
		actor: str = "",
		*,
		choice: str | None = None,
	) -> bool:
		# 审计由 store.resolve 统一写入，避免与 HTTP/微信直调双记。
		ok = self.store.resolve(
			request_id, approved, actor=actor, choice=choice
		)
		if ok:
			item = self.store.get(request_id)
			user_choice = (
				(item.user_choice if item else "")
				or (USER_CHOICE_ALLOW if approved else USER_CHOICE_DENY)
			)
			self._emit(
				PermissionResolvedEvent(
					request_id=request_id,
					approved=bool(approved) if choice is None else user_choice == USER_CHOICE_ALLOW,
					actor=actor,
					reason="user_decided",
					choice=user_choice,
				)
			)
		return ok

	def _emit(self, ev: Any) -> None:
		if self.on_event is not None:
			self.on_event(ev)
