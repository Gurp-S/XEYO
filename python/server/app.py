"""FastAPI 应用 — OpenAI 兼容 Chat Completions + XEYO 扩展。"""

from __future__ import annotations

import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from common.errors import friendly_error

from server.deps import (
	CWD,
	_error_type_for_status,
	_pool,
	error_body,
)
from server.local_gate import require_loopback

# ---------------------------------------------------------------------------
# 工具链后台预热(18:1x):import 惰性化的代价(启动→首用点平移)用后台线程回填。
# 启动完成即起 daemon 线程把 catalog/24 工具模块导入并弃置式构建一次 registry,
# 使 sys.modules 在首个会话/首条命令前就绪 → 首会话 _build / 首条 Bash 路由 /
# 首次 Ask 不再付一次性 import。事件循环不受阻塞;失败静默(不影响服务)。
# 关闭:XEYO_NO_PREWARM=1;pytest 进程内不预热(TestClient 大量实例防拖慢)。
# ---------------------------------------------------------------------------
_prewarm_lock = threading.Lock()
_prewarm_started = False


def _run_toolchain_prewarm() -> None:
	try:
		from tools.catalog import build_default_registry

		build_default_registry(cwd=str(Path.cwd()))  # 触发全部工具模块 import,弃置实例
	except Exception:  # noqa: BLE001 — 预热失败静默,服务照常
		logging.getLogger("xeyo.lifespan").debug("toolchain prewarm failed", exc_info=True)


def _ensure_toolchain_prewarm() -> None:
	"""进程级幂等:同一进程只起一次预热线程。"""
	global _prewarm_started
	if _prewarm_started:
		return
	flag = os.environ.get("XEYO_NO_PREWARM", "").strip().lower()
	if flag in ("1", "true", "yes", "on"):
		return
	if "pytest" in sys.modules:  # TestClient 生命周期反复进入 → 不预热
		return
	with _prewarm_lock:
		if _prewarm_started:
			return
		_prewarm_started = True
	threading.Thread(
		target=_run_toolchain_prewarm,
		name="toolchain-prewarm",
		daemon=True,
	).start()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
	import asyncio
	import logging
	from pathlib import Path

	from channels.api import get_runner, get_store
	from channels.filehelper.service import autostart, shutdown as fh_shutdown
	from channels.ilink.service import shutdown as il_shutdown
	from engine.turn_snapshot import (
		list_recoverable,
		mark_crashed_as_recovery,
	)
	from engine.turn_runner import bind_turn_runner
	from engine.subagent_runner import upsert_subagent_meta, list_subagent_metas

	_log = logging.getLogger("xeyo.lifespan")
	bind_turn_runner(_pool)

	# 41/42 号：goal round driver + job registry——settlement 槽注册 hub
	# （engine 槽 ← server 注入；hub 再分发给两个租户，异常互不影响）。
	try:
		from engine.turn_runner import set_turn_settlement_listener
		from server.turn_settlement_hub import on_turn_settled

		set_turn_settlement_listener(on_turn_settled)
		_log.info("settlement hub registered (goal + jobs tenants)")
	except Exception:
		_log.warning("settlement hub registration failed", exc_info=True)

	# 进程重启：活 turn 已死；把 running → recovery_required，子 agent running → interrupted。
	try:
		for snap in list_recoverable():
			if snap.is_active() or snap.status == "waiting_permission":
				mark_crashed_as_recovery(snap)
				_log.info(
					"recovery_required session=%s turn_id=%s reason=%s",
					snap.session_id,
					snap.turn_id,
					snap.stop_reason,
				)
			# 侧链卡片：running → interrupted，避免 GUI 永久转圈
			try:
				for meta in list_subagent_metas(snap.session_id) or []:
					if not isinstance(meta, dict):
						continue
					st = str(meta.get("status") or "")
					aid = str(meta.get("agent_id") or "").strip()
					if st == "running" and aid:
						upsert_subagent_meta(
							snap.session_id,
							agent_id=aid,
							task_desc=str(meta.get("task_desc") or ""),
							status="interrupted",
						)
			except Exception:  # noqa: BLE001
				_log.debug("sidechain interrupt mark failed", exc_info=True)
	except Exception:  # noqa: BLE001
		_log.warning("startup turn recovery scan failed", exc_info=True)

	# §9.2：进程重启后，进行中但未达终态的 rewind → recovery_required（重试/放弃）。
	try:
		from rewind.hotpath import mark_crashed_rewinds

		n = mark_crashed_rewinds()
		if n:
			_log.info("marked %s rewind(s) as recovery_required on startup", n)
	except Exception:  # noqa: BLE001
		_log.warning("startup rewind recovery scan failed", exc_info=True)

	async def _sidechain_gc_loop() -> None:
		"""每小时清理超 TTL 的子 agent 侧链（B6/C9）。"""
		from engine.subagent_runner import gc_sidechains
		from memory import journal

		ttl = float(os.environ.get("XEYO_SIDECHAIN_GC_TTL_S", str(7 * 24 * 3600)))
		interval = float(os.environ.get("XEYO_SIDECHAIN_GC_INTERVAL_S", "3600"))
		sessions_root = Path.home() / ".xeyo" / "sessions"
		journal_root = Path.home() / ".xeyo" / "journal"
		while True:
			await asyncio.sleep(max(60.0, interval))
			try:
				if sessions_root.is_dir():
					for d in sessions_root.iterdir():
						if d.is_dir():
							gc_sidechains(d.name, ttl_seconds=ttl)
				if journal_root.is_dir():
					for jf in journal_root.glob("*.jsonl"):
						wsid = jf.stem
						journal.gc(wsid, ttl_seconds=ttl)
			except Exception:  # noqa: BLE001
				pass

	async def _blob_gc_loop() -> None:
		"""定期执行一次回溯 blob GC（读配置/环境；默认 dry-run、禁用时只报告）。"""
		from rewind.blob_gc import garbage_collect, read_rewind_gc_config

		interval = float(os.environ.get("XEYO_BLOB_GC_INTERVAL_S", "3600"))
		while True:
			await asyncio.sleep(max(60.0, interval))
			try:
				cfg = read_rewind_gc_config()
				enabled_env = os.environ.get("XEYO_BLOB_GC_ENABLED", "").strip().lower()
				enabled = enabled_env in ("1", "true", "yes", "on")
				if not enabled:
					continue
				# 阻塞的 GC 在后台线程跑，避免卡住事件循环。
				await asyncio.to_thread(garbage_collect)
			except Exception:  # noqa: BLE001
				_log.warning("blob gc loop failed", exc_info=True)

	gc_task = asyncio.create_task(_sidechain_gc_loop())
	blob_gc_task = asyncio.create_task(_blob_gc_loop())
	await autostart(get_runner(), get_store())
	_ensure_toolchain_prewarm()
	# 本地模型：仅在设置里启用时拉起。默认关 ⇒ 进程不存在 ⇒ 零常驻占用。
	# 已在跑（上次会话遗留且 /health 通）则收养，不重复拉起：单实例约束下
	# 重复拉起会把显存撞爆。
	try:
		from localmodels.manager import default_manager as _local_model_manager

		_local_model_manager().autostart()
	except Exception:  # noqa: BLE001 — 本地模型起不来不应阻断引擎启动
		_log.warning("local model autostart failed", exc_info=True)
	try:
		yield
	finally:
		# 41/42 号：hub teardown——driver 全量 disarm + 唤醒任务取消 + 请求环境清。
		try:
			from server.turn_settlement_hub import shutdown as hub_shutdown

			hub_shutdown()
		except Exception:
			_log.warning("settlement hub shutdown failed", exc_info=True)
		gc_task.cancel()
		blob_gc_task.cancel()
		try:
			await gc_task
		except asyncio.CancelledError:
			pass
		try:
			await blob_gc_task
		except asyncio.CancelledError:
			pass
		await il_shutdown(get_runner())
		await fh_shutdown(get_runner())
		# F1：清理 MCP 管理器（关闭全部 stdio server 子进程；Windows JobObject 已有）。
		try:
			from extension.mcp_manager import shutdown_all_managers

			shutdown_all_managers()
		except Exception:  # noqa: BLE001
			_log.warning("mcp shutdown_all_managers failed", exc_info=True)
		# 本地模型：连带收掉 llama-server 的 pid 树。「随 XEYO 关闭而关闭」不能只靠
		# 正常退出路径——异常退出时由 run.json 兜底（XEYO.bat 也读同一份文件）。
		try:
			from localmodels.manager import shutdown as local_model_shutdown

			local_model_shutdown()
		except Exception:  # noqa: BLE001
			_log.warning("local model shutdown failed", exc_info=True)


app = FastAPI(title="XEYO", version="0.1.0", lifespan=_lifespan)


def _cors_origins() -> list[str]:
	"""允许的跨域来源；XEYO_CORS_ORIGINS 逗号分隔覆盖。

	默认只放行本机开发前端（Vite 5173/1421、Tauri 1420）与 Tauri WebView 来源。
	不再使用 "*" 通配符：通配符 + allow_credentials 是规范禁止的组合，
	且等于对任意网页开放本地 API（API key 走 header 可被任意页面读取）。
	"""
	raw = os.environ.get("XEYO_CORS_ORIGINS", "").strip()
	if raw:
		return [o.strip() for o in raw.split(",") if o.strip()]
	return [
		"http://localhost:5173",
		"http://127.0.0.1:5173",
		"http://localhost:1420",
		"http://127.0.0.1:1420",
		"http://localhost:1421",
		"http://127.0.0.1:1421",
		"tauri://localhost",
		"http://tauri.localhost",
		"https://tauri.localhost",
	]


_cors_origins_resolved = _cors_origins()
# T33：方法/头从 "*" 收敛为实际清单（GUI/tui/远程 UI 实际使用的全集）。
_CORS_METHODS = ["GET", "POST", "DELETE", "PATCH", "OPTIONS"]
_CORS_HEADERS = [
	"Content-Type",
	"Authorization",
	"X-Provider",
	"X-Base-Url",
	"X-Session-Id",
	"X-Remote-Token",
]
app.add_middleware(
	CORSMiddleware,
	allow_origins=_cors_origins_resolved,
	# "*" + credentials 组合无效且危险；仅显式白名单时带凭证。
	allow_credentials="*" not in _cors_origins_resolved,
	allow_methods=_CORS_METHODS,
	allow_headers=_CORS_HEADERS,
)


@app.middleware("http")
async def _allow_private_network(request: Request, call_next):
	"""Chromium 本地网络访问（Local/Private Network Access）兼容。

	webview（如 http://tauri.localhost）fetch 到 loopback 后端（127.0.0.1）时，
	Chrome 会要求预检响应带 ``Access-Control-Allow-Private-Network: true``；
	FastAPI 内置 CORSMiddleware 不输出该头，导致真实 webview 报 "Failed to fetch"。
	这里在预检响应上补上（非预检请求携带也不影响浏览器解析）。
	"""
	response = await call_next(request)
	try:
		if request.method == "OPTIONS" and response.headers.get("access-control-allow-origin"):
			response.headers["Access-Control-Allow-Private-Network"] = "true"
	except Exception:  # noqa: BLE001
		pass
	return response

# 启动时仅登记 UI cwd（可能为空）；不把 Python 包根当作工作区。
try:
	from session.cwd import set_cwd as _boot_set_cwd

	if CWD:
		_boot_set_cwd(CWD, set_as_original=True)
except Exception:
	pass

from channels.api import init_remote, router as remote_router
from channels.filehelper.api import router as filehelper_router
from channels.ilink.api import router as ilink_router

init_remote(_pool)
app.include_router(remote_router)
app.include_router(filehelper_router)
app.include_router(ilink_router)

from server.routers.workspace import router as workspace_router

app.include_router(workspace_router, dependencies=[Depends(require_loopback)])

from server.routers.media import router as media_router

app.include_router(media_router, dependencies=[Depends(require_loopback)])

from server.routers.usage import router as usage_router

app.include_router(usage_router, dependencies=[Depends(require_loopback)])

from server.routers.audit import router as audit_router

app.include_router(audit_router, dependencies=[Depends(require_loopback)])

from server.routers.control import router as control_router

app.include_router(control_router)

from server.routers.commands import router as slash_commands_router

app.include_router(slash_commands_router)

from server.routers.sessions import router as sessions_router

app.include_router(sessions_router)


from server.routers.rewind import router as rewind_hotpath_router

app.include_router(rewind_hotpath_router)

from server.routers.memory import router as memory_router

app.include_router(memory_router, dependencies=[Depends(require_loopback)])

from server.routers.chat import router as chat_router

app.include_router(chat_router)


from server.routers.goals import router as goals_router

app.include_router(goals_router)

from server.routers.jobs import router as jobs_router

app.include_router(jobs_router)

from server.routers.skills import router as skills_router

app.include_router(skills_router)

from server.routers.references import router as references_router  # noqa: E402

app.include_router(references_router)

from server.routers.extensions import router as extensions_router  # noqa: E402

app.include_router(extensions_router)

from server.routers.mcp import router as mcp_router  # noqa: E402

app.include_router(mcp_router)

from server.routers.plugins import router as plugins_router  # noqa: E402

app.include_router(plugins_router)

from server.routers.local_models import router as local_models_router  # noqa: E402

app.include_router(local_models_router, dependencies=[Depends(require_loopback)])


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):  # type: ignore[no-untyped-def]
	_ = request
	detail = exc.detail
	if isinstance(detail, dict) and "message" in detail:
		payload = error_body(
			str(detail.get("message") or ""),
			str(detail.get("type") or _error_type_for_status(exc.status_code)),
		)
	elif isinstance(detail, dict) and "error" in detail:
		payload = detail  # 已是统一结构
	elif isinstance(detail, list):
		# FastAPI / Pydantic 校验错误
		parts: list[str] = []
		for item in detail:
			if isinstance(item, dict) and "msg" in item:
				loc = item.get("loc")
				prefix = ".".join(str(x) for x in loc) if isinstance(loc, (list, tuple)) else ""
				msg = str(item.get("msg") or "")
				parts.append(f"{prefix}: {msg}" if prefix else msg)
			else:
				parts.append(str(item))
		payload = error_body("; ".join(parts) or "validation error", "invalid_request")
	else:
		payload = error_body(str(detail), _error_type_for_status(exc.status_code))
	return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(Exception)
async def _unhandled_error(request: Request, exc: Exception):  # type: ignore[no-untyped-def]
	_ = request
	# 让 HTTPException 走专用 handler（不应到达此处）。
	if isinstance(exc, HTTPException):
		return await _http_error(request, exc)
	import traceback

	traceback.print_exc()
	return JSONResponse(
		status_code=500,
		content=error_body(friendly_error(exc), "server_error"),
	)


@app.get("/health")
def health() -> dict[str, Any]:
	payload = {"ok": True, "service": "xeyo", "cwd": _pool.cwd}
	try:
		# T30：真实引擎状态——版本 / 进程身份 / 会话租约，不再永远只回 ok。
		from server.portfile import engine_version

		payload["engine_version"] = engine_version()
		payload["pid"] = os.getpid()
	except Exception:
		pass
	try:
		payload["busy_sessions"] = _pool.busy_sessions()
		payload["sessions_loaded"] = _pool.loaded_sessions()
	except Exception:
		pass
	try:
		# L1.2：本轮 / 会话消耗（L2.5 工具可观测的前置）
		payload.update(_pool.usage_snapshot())
	except Exception:
		pass
	try:
		# P3 mid-turn inbox 观测：排队 + 累计投递（省钱的成本契约闭环）。
		from server.inbox_registry import get_inbox_registry

		payload["inbox"] = get_inbox_registry().counts()
	except Exception:
		pass
	return payload



# ---- 兼容 re-export：历史测试 / 脚本直接从 server.app 导入这些名字（勿删）----
from server.deps import (  # noqa: F401
	UPLOAD_DIR,
	_extract_bearer,
	_resolve_base_url,
	_validated_media_refs,
	api_error,
	local_model_allowed,
	local_model_enabled,
)
from server.routers.chat import (  # noqa: F401
	_MAX_USER_CHARS,
	_openai_chunk,
	_sanitize_tool_input_for_ui,
	_split_prior_and_user,
	_sse_error,
	_xy_chunk,
	ChatCompletionRequest,
	ChatMessage,
)
