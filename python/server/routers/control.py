"""Control 域路由：打断、权限确认、提问作答、计划批准。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, Field

from engine.plan import default_plan_engine
from permissions.ask_store import default_ask_store
from permissions.store import default_permission_store
from rewind.blob_gc import (
    _flag,
    _int_env,
    garbage_collect,
    read_rewind_gc_config,
    write_rewind_gc_config,
)
from server.deps import _pool
from server.local_gate import require_loopback
from common.errors import safe_error_detail

router = APIRouter(tags=["control"])


class MemorySwitchBody(BaseModel):
	"""记忆系统开关 POST 体：只收开关更新（值域校验在 memory.memory_switches）。"""

	workspace: str | None = Field(default=None, max_length=1024)
	updates: dict[str, Any] = Field(default_factory=dict)


@router.get("/v1/settings/memory")
def get_memory_switches(
	request: Request,
	workspace: str | None = Query(default=None, max_length=1024),
	authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
	"""记忆系统开关生效值（settings.memory > 默认），供设置面板读取。

	``switches`` 每项带 ``exposed``（是否 GUI 暴露）/ ``ignored``（运行时是否忽略该键）/
	``effective``（运行时真值）——前端按 ``exposed`` 过滤、按 ``effective`` 显示。
	``stale`` = settings.memory 里的已删/未知残留键（只读报告，不写盘；POST 时才清理）。
	"""
	_ = authorization
	require_loopback(request)
	from memory.memory_switches import current, stale_keys
	from server.deps import CWD

	ws = (workspace or "").strip() or (CWD or "")
	try:
		return {"ok": True, "switches": current(ws or None), "stale": stale_keys(ws or None)}
	except Exception as exc:  # noqa: BLE001
		return {"ok": False, "message": str(exc)}


@router.post("/v1/settings/memory")
def post_memory_switches(
	body: MemorySwitchBody,
	request: Request,
	workspace: str | None = Query(default=None, max_length=1024),
	authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
	"""应用记忆系统开关：settings.json 原子写 + 实时写 os.environ（运行时立即生效）。

	``save`` 顺带清掉 settings.memory 里的已删/未知残留键（运行时本就不读）；
	``pruned`` 回执被清理的键名，便于审计。
	"""
	_ = authorization
	require_loopback(request)
	from memory.memory_switches import MEMORY_SWITCHES, apply_to_environ, current, prune_stale, save
	from server.deps import CWD

	ws = (workspace or body.workspace or "").strip() or (CWD or "")
	allowed = {k for (k, *_rest) in MEMORY_SWITCHES}
	bad = [k for k in body.updates if k not in allowed]
	if bad:
		return {"ok": False, "error": f"未知记忆开关: {', '.join(map(str, bad))}"}
	try:
		# 先清两侧残留键（home + workspace）；无残留则零写入。回执用于审计。
		# save 内部也会再清一次（幂等），此处先做是为了拿到"本次清掉了哪些"的准确回执。
		pruned = prune_stale(ws or None)
		saved = save(body.updates, ws or None)
		applied = apply_to_environ(ws or None)
		return {
			"ok": True,
			"memory": saved,
			"applied_env": applied,
			"pruned": pruned,
			"switches": current(ws or None),
			"stale": [],
		}
	except Exception as exc:  # noqa: BLE001 — 非法取值等
		return {"ok": False, "message": str(exc)}


@router.post("/v1/settings/memory/snapshot")
def run_memory_snapshot(request: Request) -> dict[str, Any]:
	"""手动运行一次 A3 日常监控快照（复用 --monitor-daily，按天 upsert 天然去重）。

	与每日计划任务（本地 A3 监控批处理 + schtasks）写同一处证据：docs/12 表D
	的 ``deploy_project_mode_<day>`` 行，同一天重复点只覆盖不新增。
	"""
	require_loopback(request)
	import re
	import subprocess
	import sys
	from pathlib import Path

	py_dir = Path(__file__).resolve().parents[2]
	try:
		proc = subprocess.run(
			[sys.executable, "-m", "scripts.memory_stack_eval", "--monitor-daily"],
			cwd=str(py_dir),
			capture_output=True,
			text=True,
			timeout=120,
		)
	except Exception as exc:  # noqa: BLE001 — 内部异常痕迹不外漏
		return {"ok": False, "error": safe_error_detail(exc)}
	out = "\n".join((proc.stdout or "").splitlines()[-6:])
	# 从监控输出解析真实日（ledger 的本地日），避免 UTC 与本地日不一致
	day = None
	m = re.search(r"deploy_project_mode_(\S+)", proc.stdout or "")
	if m:
		day = m.group(1)
	return {
		"ok": proc.returncode == 0,
		"day": day,
		"rc": proc.returncode,
		"tail": out,
	}


class InterruptRequest(BaseModel):
	session_id: str


@router.post("/v1/interrupt")
@router.post("/api/interrupt")
def interrupt(body: InterruptRequest, request: Request) -> dict[str, Any]:
	require_loopback(request)
	try:
		from engine.turn_runner import get_turn_runner

		get_turn_runner().mark_stopping(body.session_id, reason="user_stop")
	except Exception:
		pass
	ok = _pool.interrupt(body.session_id)
	return {"ok": ok}


class PermissionResolveRequest(BaseModel):
	request_id: str
	approved: bool
	actor: str = "desktop"
	#: allow / deny / remind；缺省时由 approved 推导（兼容旧客户端）。
	outcome: str | None = None
	#: T10：approved 且 remember=True 时记 always-allow grant（"don't ask again"）。
	remember: bool = False


@router.post("/v1/permission/resolve")
def permission_resolve(body: PermissionResolveRequest, request: Request) -> dict[str, Any]:
	"""前端/微信确认或拒绝一个挂起的权限请求。"""
	require_loopback(request)
	choice = (body.outcome or "").strip().lower() or None
	if choice not in (None, "allow", "deny", "remind"):
		choice = None
	store = default_permission_store()
	ok = store.resolve(body.request_id, body.approved, actor=body.actor, choice=choice)
	grant_id = ""
	if ok and body.remember and body.approved and choice in (None, "allow"):
		# T10：按 (tool, 规则指纹) 记 always-allow；Bash=命令前缀，其他=matched_rule。
		item = store.get(body.request_id)
		if item is not None:
			from permissions.store import default_grant_store, grant_fingerprint

			fp = grant_fingerprint(
				item.tool_name,
				item.tool_input,
				matched_rule=item.matched_rule,
				command_summary=item.command_summary,
				mcp_target=str(getattr(item, "mcp_target", "") or ""),
			)
			grant = default_grant_store().add(
				# 网关调用：以解析后的目标注册名落库（原生/网关路径同一身份）。
				tool_name=str(getattr(item, "mcp_target", "") or "") or item.tool_name,
				fingerprint=fp,
				scope=store.workspace_of(body.request_id) or "",
				actor=body.actor,
			)
			grant_id = grant.grant_id if grant else ""
	return {"ok": ok, "request_id": body.request_id, "grant_id": grant_id}


@router.get("/v1/permissions/grants")
def list_permission_grants(request: Request, scope: str | None = None) -> dict[str, Any]:
	"""T10：列出 always-allow 授权（可按工作区过滤），供 GUI 管理。"""
	require_loopback(request)
	from permissions.store import default_grant_store

	grants = [
		{
			"grant_id": g.grant_id,
			"tool_name": g.tool_name,
			"fingerprint": g.fingerprint,
			"scope": g.scope,
			"created_at": g.created_at,
			"expires_at": g.expires_at,
			"actor": g.actor,
		}
		for g in default_grant_store().list(scope=scope)
	]
	return {"ok": True, "grants": grants}


@router.delete("/v1/permissions/grants/{grant_id}")
def revoke_permission_grant(grant_id: str, request: Request) -> dict[str, Any]:
	"""T10：撤销一个 always-allow 授权（审计 permission.grant.revoked）。"""
	require_loopback(request)
	from permissions.store import default_grant_store

	ok = default_grant_store().revoke(grant_id)
	return {"ok": ok, "grant_id": grant_id}


class AskUserResolveRequest(BaseModel):
	request_id: str
	answer: str
	actor: str = "desktop"


@router.post("/v1/ask/resolve")
def ask_user_resolve(body: AskUserResolveRequest, request: Request) -> dict[str, Any]:
	"""前端/微信提交对一个挂起提问（AskUserQuestion）的作答。"""
	require_loopback(request)
	ok = default_ask_store().resolve_answer(
		body.request_id, body.answer, actor=body.actor
	)
	return {"ok": ok, "request_id": body.request_id}


class PlanApproveRequest(BaseModel):
	approved: bool
	actor: str = "desktop"


class RewindGcSettings(BaseModel):
	keep_recent: int | None = None
	max_bytes: int | None = None


@router.get("/v1/settings/rewind-gc")
def get_rewind_gc_settings(request: Request) -> dict[str, Any]:
	"""回溯 blob GC 设置（设计 §36 §9.1）：读取持久化配置 + 环境默认。"""
	require_loopback(request)
	cfg = read_rewind_gc_config()
	return {
		**cfg,
		"defaults": {
			"enabled": _flag("XEYO_BLOB_GC_ENABLED", default=False),
			"dry_run": _flag("XEYO_BLOB_GC_DRY_RUN", default=True),
			"max_bytes": _int_env("XEYO_BLOB_GC_MAX_BYTES", None),
		},
	}


@router.put("/v1/settings/rewind-gc")
def put_rewind_gc_settings(body: RewindGcSettings, request: Request) -> dict[str, Any]:
	"""写入回溯 blob GC 设置；负数给 400。"""
	require_loopback(request)
	if body.keep_recent is not None and body.keep_recent < 1:
		return {"ok": False, "error": "keep_recent 必须 ≥ 1"}
	if body.max_bytes is not None and body.max_bytes < 0:
		return {"ok": False, "error": "max_bytes 必须 ≥ 0"}
	saved = write_rewind_gc_config(
		keep_recent=body.keep_recent,
		max_bytes=body.max_bytes,
	)
	return {"ok": True, **saved}


@router.post("/v1/settings/rewind-gc/run")
def run_rewind_gc(request: Request) -> dict[str, Any]:
	"""手动触发一次 blob GC（读取配置/环境；默认 dry-run 只报告）。"""
	require_loopback(request)
	try:
		result = garbage_collect()
		return {"ok": True, **result.to_dict()}
	except Exception as exc:  # noqa: BLE001
		# T34：内部异常痕迹不出 API。
		return {"ok": False, "error": safe_error_detail(exc)}


@router.post("/v1/plan/{turn_id}/approve")
def plan_approve(turn_id: str, body: PlanApproveRequest, request: Request) -> dict[str, Any]:
	"""批准或拒绝一个 Plan 模式下已经产出的实现计划。"""
	require_loopback(request)
	ok = default_plan_engine().resolve(
		turn_id, body.approved, actor=body.actor
	)
	return {"ok": ok, "request_id": turn_id, "approved": body.approved}
