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
    read_rewind_gc_config,
    write_rewind_gc_config,
)
from server.deps import _MAX_USER_CHARS, _pool, api_error
from server.local_gate import require_loopback
from server.routers.extensions import require_workspace_arg
from common.errors import safe_error_detail

router = APIRouter(tags=["control"])

#: 身份键长度上界：与 ``sessions._MAX_ID_CHARS`` 同档（会话 / 请求 / grant id 实测
#: 都是 ``uuid4().hex`` 的 12–32 位），留足余量又挡掉「把整篇文档当 id 发过来」。
_MAX_ID_CHARS = 128


def _require_store_id(raw: Any, *, field: str) -> str:
	"""挂起项句柄（request_id / turn_id / grant_id）的边缘校验。

	复用 ``sessions._require_stable_id``（延迟导入，避开路由之间的导入环），不另立
	判据：空白 / 控制字符 / 超长 / 带路径分隔符一律 422，原样返回合法值。

	为什么这些 in-process 句柄也要校验：存储层自己还会再归一化一次——
	``PermissionGrantStore.revoke`` 对 key 做 ``strip()``，于是
	``" 9b8bde015466"`` 与 ``"9b8bde015466"`` 打到**同一条 grant**，
	撤销动作删掉的是另一个身份的数据。边缘先拒，执行层才有唯一身份。
	"""
	from server.routers.sessions import _require_stable_id

	return _require_stable_id(raw, field=field)


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

	ws = require_workspace_arg(workspace) or (CWD or "")
	try:
		return {"ok": True, "switches": current(ws or None), "stale": stale_keys(ws or None)}
	except Exception as exc:  # noqa: BLE001 — 读不出状态既不以裸 500 逃出，也不谎报成"没配"
		raise api_error(500, safe_error_detail(exc), "memory_settings_unreadable") from exc


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

	# 相对 workspace（``..`` / ``a/b``）按**服务端进程 cwd**取根，等于让调用方把
	# memory 段写进任意目录的 .xeyo/settings.json；空白照旧回退已登记 cwd。
	ws = require_workspace_arg(workspace) or require_workspace_arg(body.workspace) or (CWD or "")
	allowed = {k for (k, *_rest) in MEMORY_SWITCHES}
	bad = [k for k in body.updates if k not in allowed]
	if bad:
		# 本路由族的取值回执约定是 200 + ok:false（test_memory_switches 钉住）；
		# 这里只给未知键名截断，避免把调用方任意长的串整段反射回响应体。
		return {"ok": False, "error": f"未知记忆开关: {', '.join(map(str, bad))}"[:200]}
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
	except ValueError as exc:  # 非法取值：200 + ok:false（本路由族钉死的取值回执）
		return {"ok": False, "message": safe_error_detail(exc)}
	except Exception as exc:  # noqa: BLE001 — 写盘 / 环境桥接失败不是"没生效"，是失败
		raise api_error(500, safe_error_detail(exc), "memory_settings_write_failed") from exc


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
	raw = proc.stdout or ""
	out = "\n".join(raw.splitlines()[-6:])
	# 从监控输出解析真实日（ledger 的本地日），避免 UTC 与本地日不一致。
	# auto 会补齐「上次快照日之后 → ledger 最新日」的所有天，故列出全部、day 取最新那天。
	days = re.findall(r"deploy_project_mode_(\S+)", raw)
	return {
		"ok": proc.returncode == 0,
		"day": days[-1] if days else None,
		"days": days,
		"rc": proc.returncode,
		"tail": out,
	}


@router.get("/v1/settings/memory/report")
def memory_report(request: Request) -> dict[str, Any]:
	"""A3 监控报告（``docs/A3-monitor.html``）的落点与元信息，供设置页「打开报告」按钮用。

	路径取生成器里的同一常量（``scripts.memory_stack_eval.A3_HTML``），不在此复制路径字面量，
	避免报告换位置后两端漂移；``url`` 是可直接交给系统浏览器的 ``file://`` 链接。
	报告不存在时返回 ``ok=false/exists=false``（按钮据此禁用），不报错。
	"""
	require_loopback(request)
	import re
	from pathlib import Path

	from scripts.memory_stack_eval import A3_HTML

	path = Path(A3_HTML)
	try:
		url = path.as_uri()
	except ValueError:  # 非绝对路径等异常形态
		url = ""
	info: dict[str, Any] = {"ok": False, "exists": False, "path": str(path), "url": url}
	if not path.is_file():
		return info
	try:
		text = path.read_text(encoding="utf-8", errors="replace")
		st = path.stat()
	except OSError as exc:  # noqa: BLE001 — 报告**存在**却读不出：不能谎报成"尚未生成"
		raise api_error(500, safe_error_detail(exc), "memory_report_unreadable") from exc
	m = re.search(r'"generated_at":\s*"([^"]+)"', text)
	return {
		**info,
		"ok": True,
		"exists": True,
		"bytes": st.st_size,
		"mtime": round(st.st_mtime, 3),
		"generated_at": m.group(1) if m else None,
		# 日期集合：payload 里每天出现两次（day 行 + total.detail），set 去重即天数清单。
		"days": sorted(set(re.findall(r'"day": "(\d{4}-\d{2}-\d{2})"', text))),
	}


@router.get("/v1/settings/memory/report/view")
def memory_report_view(request: Request) -> Any:
	"""把 A3 报告当网页交给浏览器（系统默认浏览器 / 工作区预览面板）。

	为什么要多这一跳：桌面壳的 ``shell:allow-open`` scope 只放行 ``mailto:`` / ``tel:`` /
	``http(s)://`` —— ``file://`` 被插件**默认拒绝**（见其 scope 正则），故按钮直接开
	``file://`` 会报 Scoped command argument failed regex validation。这里用 loopback http
	出一个只读入口：既不用放宽壳的 scope，也不用把 ``file:`` 引进预览面板（面板同样明令禁
	``file:``）。只服务生成器写的那一个路径，不接受调用方传入路径。
	"""
	require_loopback(request)
	from pathlib import Path

	from fastapi.responses import FileResponse

	from scripts.memory_stack_eval import A3_HTML
	from server.deps import api_error

	path = Path(A3_HTML)
	if not path.is_file():
		raise api_error(404, "A3 report not generated yet", "not_found")
	return FileResponse(
		path,
		media_type="text/html; charset=utf-8",
		headers={"Cache-Control": "no-store"},
	)


class InterruptRequest(BaseModel):
	#: 会话 id 只做长度上界：``SessionPool.interrupt`` / ``TurnRunner.mark_stopping``
	#: 都是**精确键**的进程内字典（无 strip / 无文件名归一化），``"victim "`` 打不到
	#: ``victim``，落不存在的 id 也只是幂等 no-op——所以这里不套固定点（那会破坏
	#: 已钉死的幂等 stop 契约），只挡超长串。
	session_id: str = Field(max_length=_MAX_ID_CHARS)


@router.post("/v1/interrupt")
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
	request_id: str = Field(max_length=_MAX_ID_CHARS)
	approved: bool
	actor: str = Field(default="desktop", max_length=_MAX_ID_CHARS)
	#: allow / deny / remind；缺省时由 approved 推导（兼容旧客户端）。
	#: 认不得的非空值一律 422——静默按 approved 兜底等于替用户改写裁决。
	outcome: str | None = Field(default=None, max_length=32)
	#: T10：approved 且 remember=True 时记 always-allow grant（"don't ask again"）。
	remember: bool = False


@router.post("/v1/permission/resolve")
def permission_resolve(body: PermissionResolveRequest, request: Request) -> dict[str, Any]:
	"""前端/微信确认或拒绝一个挂起的权限请求。"""
	require_loopback(request)
	request_id = _require_store_id(body.request_id, field="request_id")
	choice = (body.outcome or "").strip().lower() or None
	if choice not in (None, "allow", "deny", "remind"):
		# 裁决语义有歧义绝不猜：此前拼错的 outcome 会静默回落到 ``approved``，
		# 实测 ``{"approved": true, "outcome": "deny-all"}`` 把一次拒绝意图
		# 变成了**放行**，还连带落了永久的 always-allow grant。
		raise api_error(
			422, "outcome must be allow / deny / remind", "invalid_request"
		)
	store = default_permission_store()
	ok = store.resolve(request_id, body.approved, actor=body.actor, choice=choice)
	grant_id = ""
	if ok and body.remember and body.approved and choice in (None, "allow"):
		# T10：按 (tool, 规则指纹) 记 always-allow；Bash=命令前缀，其他=matched_rule。
		item = store.get(request_id)
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
				scope=store.workspace_of(request_id) or "",
				actor=body.actor,
			)
			grant_id = grant.grant_id if grant else ""
	return {"ok": ok, "request_id": request_id, "grant_id": grant_id}


@router.get("/v1/permissions/grants")
def list_permission_grants(request: Request, scope: str | None = None) -> dict[str, Any]:
	"""T10：列出 always-allow 授权（可按工作区过滤），供 GUI 管理。"""
	require_loopback(request)
	from permissions.store import default_grant_store

	# 相对 scope 会被 ``PermissionGrantStore.list`` 按服务端进程 cwd 取根，实测
	# ``?scope=ws`` 让一个确有授权的工作区报成 ``grants: []``（"什么都没授权"的假绿）。
	# 语义：**不发 scope = 列全部**（GUI 就这么调）；发了但是空白 = 意图不明的过滤条件，
	# 既不静默放宽成"列全部"（那会把别的工作区的授权算到这个过滤上），也不静默清空。
	if scope is not None and not str(scope).strip():
		raise api_error(422, "scope is blank", "invalid_request")
	want_scope = require_workspace_arg(scope, field="scope")
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
		for g in default_grant_store().list(scope=want_scope or None)
	]
	return {"ok": True, "grants": grants}


@router.delete("/v1/permissions/grants/{grant_id}")
def revoke_permission_grant(grant_id: str, request: Request) -> dict[str, Any]:
	"""T10：撤销一个 always-allow 授权（审计 permission.grant.revoked）。"""
	require_loopback(request)
	from permissions.store import default_grant_store

	# grant_id 是 store handle，且 revoke() 自己 strip() —— 未校验时
	# ``DELETE /v1/permissions/grants/%20<id>`` 实测返回 200 ok:true 并**删掉了
	# <id> 那条真实授权**。固定点校验后这类写法 422、零删除。
	gid = _require_store_id(grant_id, field="grant_id")
	ok = default_grant_store().revoke(gid)
	return {"ok": ok, "grant_id": gid}


class AskUserResolveRequest(BaseModel):
	request_id: str = Field(max_length=_MAX_ID_CHARS)
	#: 作答文本会成为工具结果进模型注意力，上界与 chat 的用户消息同档。
	answer: str = Field(max_length=_MAX_USER_CHARS)
	actor: str = Field(default="desktop", max_length=_MAX_ID_CHARS)


@router.post("/v1/ask/resolve")
def ask_user_resolve(body: AskUserResolveRequest, request: Request) -> dict[str, Any]:
	"""前端/微信提交对一个挂起提问（AskUserQuestion）的作答。"""
	require_loopback(request)
	request_id = _require_store_id(body.request_id, field="request_id")
	ok = default_ask_store().resolve_answer(
		request_id, body.answer, actor=body.actor
	)
	return {"ok": ok, "request_id": request_id}


class PlanApproveRequest(BaseModel):
	approved: bool
	actor: str = Field(default="desktop", max_length=_MAX_ID_CHARS)


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
	"""写入回溯 blob GC 设置；非法取值 422，写盘失败结构化 500。

	此前非法值走 ``200 + ok:false``：GUI 的 ``setRewindGcSettings`` 只看
	``res.ok``，于是"keep_recent=0 被拒"在前端渲染成**保存成功**（假绿）；
	而 ``write_rewind_gc_config`` 的 ``mkdir`` 失败（父路径被占位 / 只读盘）
	以 ``FileExistsError`` 裸逃出路由。
	"""
	require_loopback(request)
	if body.keep_recent is not None and body.keep_recent < 1:
		raise api_error(422, "keep_recent must be >= 1", "invalid_request")
	if body.max_bytes is not None and body.max_bytes < 0:
		raise api_error(422, "max_bytes must be >= 0", "invalid_request")
	try:
		saved = write_rewind_gc_config(
			keep_recent=body.keep_recent,
			max_bytes=body.max_bytes,
		)
	except OSError as exc:
		raise api_error(500, safe_error_detail(exc), "rewind_gc_write_failed") from exc
	return {"ok": True, **saved}


@router.post("/v1/plan/{turn_id}/approve")
def plan_approve(turn_id: str, body: PlanApproveRequest, request: Request) -> dict[str, Any]:
	"""批准或拒绝一个 Plan 模式下已经产出的实现计划。"""
	require_loopback(request)
	tid = _require_store_id(turn_id, field="turn_id")
	ok = default_plan_engine().resolve(
		tid, body.approved, actor=body.actor
	)
	return {"ok": ok, "request_id": tid, "approved": body.approved}
