"""挂起权限请求存储（M3 骨架）。

key = request_id，保存 pending 请求与唤醒信号；支持超时与幂等 resolve。
同一 request_id 只能被处理一次。
桌面 / 微信 resolve 均走本 store，成功时写 ``permission.resolved`` 审计。

三选 peer ASK：``user_choice`` 为 allow / deny / remind；旧客户端只传 approved。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from permissions.pending_ttl import ttl_for_request

# 用户对挂起权限的选择（与审计 outcome 生命周期字段分离）。
USER_CHOICE_ALLOW = "allow"
USER_CHOICE_DENY = "deny"
USER_CHOICE_REMIND = "remind"
_VALID_USER_CHOICES = frozenset(
	{USER_CHOICE_ALLOW, USER_CHOICE_DENY, USER_CHOICE_REMIND}
)


@dataclass
class PendingPermission:
	request_id: str
	session_id: str
	turn_id: str
	tool_name: str
	tool_input: dict[str, Any]
	reason: str
	prompt: str
	expires_at: float | None
	created_at: float
	matched_rule: str = ""
	command_summary: str = ""
	choices: tuple[str, ...] = ()
	peer_summary: str = ""
	resolved: bool = False
	approved: bool | None = None
	#: allow / deny / remind（三选或由 approved 推导）
	user_choice: str = ""
	actor: str = ""
	#: user_decided / timeout / aborted —— 供 wait 侧区分结束原因。
	outcome: str = "user_decided"
	#: T10：请求发起时的工作区根（grant 落盘的 workspace 维度）。
	workspace: str = ""
	#: P0b 指纹 v2：网关调用解析出的目标注册名（mcp__server__raw__hex）；
	#: 原生 mcp__ 工具留空（tool_name 即注册名，指纹函数自行识别）。
	mcp_target: str = ""


class PendingPermissionStore:
	"""进程内、按 request_id 索引的挂起权限存储。"""

	def __init__(self, ttl_seconds: float | None = None) -> None:
		# T3：None = 按请求风险分级（ttl_for_request）；<=0 = 不超时（交互式）；
		# >0 = 固定 TTL（测试/特殊面板）。
		self._ttl = ttl_seconds
		self._items: dict[str, PendingPermission] = {}
		self._events: dict[str, asyncio.Event] = {}

	def create(
		self,
		*,
		session_id: str,
		turn_id: str,
		tool_name: str,
		tool_input: dict[str, Any],
		reason: str,
		prompt: str,
		request_id: str | None = None,
		matched_rule: str = "",
		command_summary: str = "",
		choices: tuple[str, ...] | list[str] | None = None,
		peer_summary: str = "",
		mcp_target: str = "",
	) -> PendingPermission:
		self._prune()
		rid = request_id or uuid.uuid4().hex
		now = time.time()
		choice_tuple = tuple(str(c) for c in (choices or ()) if str(c).strip())
		if self._ttl is None:
			# T3：风险分级——danger/secret/protected → 60s；普通 → 180s。
			ttl = ttl_for_request(
				reason=reason, matched_rule=matched_rule, tool_name=tool_name
			)
		elif self._ttl <= 0:
			ttl = None  # 交互式：不超时，等用户显式结束
		else:
			ttl = self._ttl
		item = PendingPermission(
			request_id=rid,
			session_id=session_id,
			turn_id=turn_id,
			tool_name=tool_name,
			tool_input=tool_input,
			reason=reason,
			prompt=prompt,
			expires_at=(now + ttl) if ttl is not None else None,
			created_at=now,
			matched_rule=matched_rule or "",
			command_summary=command_summary or "",
			choices=choice_tuple,
			peer_summary=peer_summary or "",
			workspace=_current_workspace(),
			mcp_target=(mcp_target or "").strip(),
		)
		self._items[rid] = item
		self._events[rid] = asyncio.Event()
		return item

	def get(self, request_id: str) -> PendingPermission | None:
		return self._items.get(request_id)

	def pending_for_session(self, session_id: str) -> PendingPermission | None:
		"""返回该会话尚未处理的挂起请求（每会话通常至多一个在途）。"""
		for item in self._items.values():
			if item.session_id == session_id and not item.resolved:
				return item
		return None

	def workspace_of(self, request_id: str) -> str:
		"""T10：该请求创建时的工作区根（供 grant 落 workspace 维度）。"""
		item = self._items.get(request_id)
		return item.workspace if item else ""

	def resolve(
		self,
		request_id: str,
		approved: bool,
		actor: str = "",
		outcome: str = "user_decided",
		*,
		choice: str | None = None,
	) -> bool:
		item = self._items.get(request_id)
		if item is None or item.resolved:
			return False
		item.resolved = True
		user_choice = (choice or "").strip().lower()
		if user_choice in _VALID_USER_CHOICES:
			item.user_choice = user_choice
			item.approved = user_choice == USER_CHOICE_ALLOW
		else:
			item.approved = bool(approved)
			item.user_choice = (
				USER_CHOICE_ALLOW if item.approved else USER_CHOICE_DENY
			)
		item.actor = actor
		item.outcome = outcome or "user_decided"
		ev = self._events.get(request_id)
		if ev is not None:
			ev.set()
		try:
			from audit.log import default_audit_log

			fields: dict[str, Any] = {
				"session_id": item.session_id,
				"turn_id": item.turn_id,
				"request_id": request_id,
				"tool_name": item.tool_name,
				"reason": item.reason,
				"matched_rule": item.matched_rule,
				"approved": bool(item.approved),
				"user_choice": item.user_choice,
				"actor": actor,
				"outcome": item.outcome,
			}
			if item.command_summary:
				fields["command_summary"] = item.command_summary
			default_audit_log().record("permission.resolved", **fields)
		except Exception:
			pass
		return True

	def cancel_pending_for_session(
		self, session_id: str, actor: str = "abort"
	) -> int:
		"""把该会话所有未决请求按"已取消（拒绝）"处理并立刻唤醒等待者。

		abort 不会唤醒挂在 ``wait`` 上的 asyncio.Event——回合等待审批时点
		停止，租约要等面板 TTL（180s）到期才释放。interrupt 路径调用本方法
		让等待者即刻返回。返回取消的请求数。
		"""
		count = 0
		for item in list(self._items.values()):
			if item.session_id != session_id or item.resolved:
				continue
			if self.resolve(
				item.request_id,
				approved=False,
				actor=actor,
				outcome="aborted",
				choice=USER_CHOICE_DENY,
			):
				count += 1
		return count

	async def wait(
		self, request_id: str, timeout: float | None = None
	) -> PendingPermission | None:
		item = self._items.get(request_id)
		if item is None:
			return None
		if timeout is None:
			# T3：expires_at None（不超时）→ 无限期等待，直到显式 resolve。
			timeout = (
				max(0.0, item.expires_at - time.time())
				if item.expires_at is not None
				else None
			)
		ev = self._events.get(request_id)
		if ev is not None and not ev.is_set():
			try:
				await asyncio.wait_for(ev.wait(), timeout=timeout)
			except asyncio.TimeoutError:
				pass
		return self._items.get(request_id)

	def _prune(self) -> None:
		now = time.time()
		for rid in (
			r
			for r, it in self._items.items()
			if it.expires_at is not None
			and it.expires_at < now
			and not it.resolved
		):
			self._items.pop(rid, None)
			self._events.pop(rid, None)


_default_store: PendingPermissionStore | None = None


def default_permission_store() -> PendingPermissionStore:
	"""进程级共享挂起权限存储，供所有引擎与 resolve 端点使用。"""
	global _default_store
	if _default_store is None:
		_default_store = PendingPermissionStore()
	return _default_store


def _current_workspace() -> str:
	"""T10：当前回合的工作区根（无上下文则空串）。"""
	try:
		from engine.workspace_context import get_workspace_context

		ctx = get_workspace_context()
		return (ctx.cwd if ctx else "") or ""
	except Exception:
		return ""


# ---------------------------------------------------------------------------
# T10：grant store —— per-(tool, 规则指纹) always-allow（"don't ask again"）。
# 生命周期：TTL + workspace 维度；增删均写事件化审计；进程内存储。
# 红线：grant 只能把 ASK 放行为 ALLOW，永不触碰 DENY（policy 侧守卫）。
# ---------------------------------------------------------------------------

#: 默认 TTL：24h；XEYO_GRANT_TTL_SEC 覆盖（<=0 = 不过期）。
DEFAULT_GRANT_TTL_SEC = 24 * 3600.0


@dataclass
class PermissionGrant:
	tool_name: str
	#: 规则指纹：Bash=命令前缀（program + 首参数），其他工具=matched_rule。
	fingerprint: str
	#: 工作区根（os.path.abspath）；"" 仅匹配无工作区上下文的请求。
	scope: str = ""
	created_at: float = 0.0
	expires_at: float | None = None
	actor: str = ""
	#: 稳定 id（撤销 / 枚举用）。
	grant_id: str = field(default="")


def _grant_workspace_scope() -> str:
	try:
		return os.path.abspath(_current_workspace()) if _current_workspace() else ""
	except Exception:
		return ""


class PermissionGrantStore:
	"""进程内 always-allow 授权存储。"""

	def __init__(self, default_ttl: float | None = None) -> None:
		if default_ttl is None:
			raw = (os.environ.get("XEYO_GRANT_TTL_SEC") or "").strip()
			try:
				default_ttl = float(raw) if raw else DEFAULT_GRANT_TTL_SEC
			except ValueError:
				default_ttl = DEFAULT_GRANT_TTL_SEC
		self._ttl = default_ttl
		self._grants: dict[str, PermissionGrant] = {}

	def _prune(self) -> None:
		now = time.time()
		for gid in [
			gid
			for gid, g in self._grants.items()
			if g.expires_at is not None and g.expires_at < now
		]:
			self._grants.pop(gid, None)

	def add(
		self,
		*,
		tool_name: str,
		fingerprint: str,
		scope: str | None = None,
		ttl: float | None = None,
		actor: str = "",
	) -> PermissionGrant | None:
		tool = (tool_name or "").strip()
		fp = (fingerprint or "").strip()
		if not tool or not fp:
			return None
		self._prune()
		effective_scope = (
			os.path.abspath(scope) if scope else _grant_workspace_scope()
		)
		now = time.time()
		effective_ttl = self._ttl if ttl is None else ttl
		grant = PermissionGrant(
			tool_name=tool,
			fingerprint=fp,
			scope=effective_scope,
			created_at=now,
			expires_at=(now + effective_ttl) if effective_ttl and effective_ttl > 0 else None,
			actor=actor or "",
			grant_id=hashlib.sha1(
				f"{tool}\x00{fp}\x00{effective_scope}".encode("utf-8")
			).hexdigest()[:12],
		)
		self._grants[grant.grant_id] = grant
		try:
			from audit.log import default_audit_log

			default_audit_log().record(
			"permission.grant.added",
			tool_name=grant.tool_name,
			fingerprint=grant.fingerprint,
			scope=grant.scope,
			grant_id=grant.grant_id,
			expires_at=grant.expires_at,
			actor=grant.actor,
		)
		except Exception:
			pass
		return grant

	def match(
		self, *, tool_name: str, fingerprint: str, scope: str | None = None
	) -> PermissionGrant | None:
		"""命中未过期 grant；scope 大小写不敏感（Windows 路径）。"""
		self._prune()
		fp = (fingerprint or "").strip().lower()
		tool = (tool_name or "").strip().lower()
		if not fp or not tool:
			return None
		effective_scope = (
			os.path.abspath(scope) if scope else _grant_workspace_scope()
		)
		now = time.time()
		for grant in self._grants.values():
			if grant.tool_name.lower() != tool:
				continue
			if grant.fingerprint.strip().lower() != fp:
				continue
			if grant.scope != effective_scope and grant.scope.lower() != (
				effective_scope or ""
			).lower():
				continue
			if grant.expires_at is not None and grant.expires_at < now:
				continue
			return grant
		return None

	def revoke(self, grant_id: str) -> bool:
		grant = self._grants.pop((grant_id or "").strip(), None)
		if grant is None:
			return False
		try:
			from audit.log import default_audit_log

			default_audit_log().record(
				"permission.grant.revoked",
				grant_id=grant.grant_id,
				tool_name=grant.tool_name,
				fingerprint=grant.fingerprint,
				scope=grant.scope,
			)
		except Exception:
			pass
		return True

	def list(self, scope: str | None = None) -> list[PermissionGrant]:
		self._prune()
		if scope:
			want = os.path.abspath(scope)
			return [
				g for g in self._grants.values() if g.scope == want
			]
		return list(self._grants.values())


def canonical_args(tool_input: dict[str, Any] | None) -> str:
	"""§15.1② args 规范化纯函数：键序排序、紧凑分隔、ASCII 转义。

	身份与参数分离（§15.1①）：v2 指纹**不含** args —— 本函数服务于
	repeat_guard / 网关 describe 校验 / 审计去重等「参数规范化」消费方。
	非 dict 或空 → 空串；不可序列化叶子经 ``default=str`` 稳定化，绝不抛出。
	"""
	if not isinstance(tool_input, dict) or not tool_input:
		return ""
	try:
		return json.dumps(
			tool_input,
			sort_keys=True,
			separators=(",", ":"),
			ensure_ascii=True,
			default=str,
		)
	except Exception:  # noqa: BLE001 — 纯函数不抛
		return ""


#: 指纹版本（§15.1③）：前缀参与比对，v1 旧授权结构上不可能命中。
_MCP_FP_VERSION = "v2"


def mcp_grant_fingerprint(registered_tool_name: str) -> str:
	"""MCP 调用点身份指纹 v2（§15.1①③）：``("mcp-tool", 注册名)`` 结构化哈希。

	- 注册名 = ``mcp__<server>__<raw>__<12hex>``（网关路径为**解析后**的目标
	  注册名 —— 身份经已知工具集校验，绝不从 args 读取，注入免疫）。
	- 返回 ``v2:<32hex>``；身份不可用 → 空串（不可落 grant，fail-safe）。
	"""
	tool = (registered_tool_name or "").strip()
	if not tool.startswith("mcp__") or len(tool) <= len("mcp__"):
		return ""
	canon = json.dumps(["mcp-tool", tool], ensure_ascii=True, separators=(",", ":"))
	digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:32]
	return f"{_MCP_FP_VERSION}:{digest}"


def grant_fingerprint(
	tool_name: str,
	tool_input: dict[str, Any] | None,
	*,
	matched_rule: str = "",
	command_summary: str = "",
	mcp_target: str = "",
) -> str:
	"""计算 always-allow 指纹。

	- Bash：命令前缀 = program + 首参数（如 ``git status`` / ``python``），
	  对应 UI 文案「don't ask again for commands starting with …」。
	- MCP 动态/网关工具（P0b v2）：调用点身份哈希 —— 原生工具即 ``tool_name``
	  （注册名），网关为解析后的目标注册名（``mcp_target``）。args 永不参与：
	  同工具异 args 同指纹、伪装字段不迁移；v1 裸 matched_rule 旧授权无法
	  静默复用（版本隔离）。**修复 v1 过放**：v1 对所有 MCP 工具共用
	  ``mcp_outbound_ask``，放行一个即放行全部 —— v2 按注册名隔离。
	- 其他工具：matched_rule（同类原因聚合；拒绝类规则在 policy 先于 grant 生效）。
	"""
	name = (tool_name or "").strip().lower()
	target = (mcp_target or "").strip()
	if name.startswith("mcp__") or target.startswith("mcp__"):
		identity_name = target if target.startswith("mcp__") else (tool_name or "").strip()
		return mcp_grant_fingerprint(identity_name)
	if name == "bash":
		raw = ""
		if command_summary:
			raw = command_summary
		elif isinstance(tool_input, dict):
			c = tool_input.get("command")
			if isinstance(c, str):
				raw = c
		toks = raw.split()
		if not toks:
			return ""
		if len(toks) == 1:
			return toks[0].lower()
		return f"{toks[0].lower()} {toks[1].lower()}"
	return (matched_rule or "").strip()


_default_grant_store: PermissionGrantStore | None = None


def default_grant_store() -> PermissionGrantStore:
	"""进程级共享 always-allow 存储。"""
	global _default_grant_store
	if _default_grant_store is None:
		_default_grant_store = PermissionGrantStore()
	return _default_grant_store
