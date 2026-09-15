"""本地模型域路由：设置读写 + 单实例 llama-server 的起停与切换。

与 ``/v1/settings/memory`` 同款姿势：``require_loopback`` 门禁、``{"ok": bool}`` 回执、
设置落盘 ``.xeyo/settings.json``。放在独立模块而不是往 ``control.py`` 里塞，
是为了让「本地模型」这一整块（配置 + 进程）有单一入口。

失败一律用 ``{"ok": false, "error": ...}`` 而不是 HTTP 4xx/5xx：前端在设置面板里
就地渲染原因（权重缺失 / 找不到 llama-server / 显存不足），不需要区分状态码。
参数不合法是唯一走 HTTP 400 的情况。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from server.local_gate import require_loopback

router = APIRouter(tags=["local-models"])


class LocalModelSettingsBody(BaseModel):
	"""设置写入体：只收 ``localmodels.config.FIELDS`` 里的键（未知键报 400）。"""

	workspace: str | None = Field(default=None, max_length=1024)
	settings: dict[str, Any] = Field(default_factory=dict)


class LocalModelActionBody(BaseModel):
	"""起停/切换体：``model`` 缺省 = 用已保存的 active_model。"""

	workspace: str | None = Field(default=None, max_length=1024)
	model: str | None = Field(default=None, max_length=128)


def _snapshot(workspace: str | None) -> dict[str, Any]:
	"""当前设置 + 运行态 + 登记表 + 二进制探测结果（设置面板一次拉全）。"""
	from localmodels import catalog, config, gate
	from localmodels.manager import default_manager

	ws = (workspace or "").strip() or None
	cfg = config.store(ws)
	mgr = default_manager()
	binary = config.resolve_binary(cfg)
	out_dir = config.models_dir()
	models = []
	for m in catalog.LOCAL_MODELS:
		path = out_dir / m.filename
		try:
			got = path.stat().st_size
		except OSError:
			got = 0
		# present 按"字节数精确吻合"判定。这里不能用 `>=`：续传竞态或镜像返回错体
		# 会让文件**偏大**，而偏大的权重能通过 `>=` 却在 llama.cpp 侧加载失败——
		# 那正是"文件在、却起不来"的最难查的一类。偏大偏小一律不算就绪。
		entry = catalog.to_dict(m, present=got == m.size_bytes, path=str(path))
		entry["downloaded_bytes"] = got
		models.append(entry)
	return {
		"ok": True,
		"settings": cfg,
		"status": mgr.status(),
		"models": models,
		"binary": {
			"path": str(binary) if binary else "",
			"found": binary is not None,
		},
		"models_dir": str(out_dir),
		"base_url": config.base_url(cfg),
		"gate": {
			"env": _env_flag(),
			"settings": bool(cfg.get("enabled")),
			"allowed": gate.local_model_allowed(ws),
		},
	}


def _env_flag() -> bool:
	import os

	return os.environ.get("XEYO_ALLOW_LOCAL_MODEL", "").strip().lower() in (
		"1",
		"true",
		"yes",
		"on",
	)


@router.get("/v1/local-models")
def get_local_models(
	request: Request,
	workspace: str | None = None,
) -> dict[str, Any]:
	"""本地模型全景快照（设置 + 运行态 + 可用模型 + 二进制探测）。"""
	require_loopback(request)
	return _snapshot(workspace)


@router.post("/v1/local-models")
def post_local_models(body: LocalModelSettingsBody, request: Request) -> dict[str, Any]:
	"""写本地模型设置。

	副作用是有意的：``enabled`` 落盘即同时打开执行面与
	``server/deps`` 的 SSRF 白名单（``base_url`` 由 ``config.save`` 一并落盘）。
	"""
	require_loopback(request)
	from fastapi import HTTPException

	from localmodels import config

	try:
		config.save(body.settings, body.workspace or None)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc
	except Exception as exc:  # noqa: BLE001 — 写盘失败（权限/磁盘）
		return {"ok": False, "error": f"设置写入失败: {exc}"}
	return _snapshot(body.workspace)


@router.post("/v1/local-models/start")
def start_local_model(body: LocalModelActionBody, request: Request) -> dict[str, Any]:
	"""拉起本地模型服务（立即返回，加载进度看 ``status.state``）。"""
	require_loopback(request)
	from localmodels.manager import default_manager

	res = default_manager().start(body.model)
	return {**res, **(_snapshot(body.workspace) if res.get("ok") else {})}


@router.post("/v1/local-models/stop")
def stop_local_model(request: Request) -> dict[str, Any]:
	"""停止本地模型服务（连带收掉 pid 树）。"""
	require_loopback(request)
	from localmodels.manager import default_manager

	res = default_manager().stop()
	return {**res, **(_snapshot(None) if res.get("ok") else {})}


@router.post("/v1/local-models/switch")
def switch_local_model(body: LocalModelActionBody, request: Request) -> dict[str, Any]:
	"""切换模型（单实例：运行中则停旧起新）。"""
	require_loopback(request)
	from localmodels.manager import default_manager

	res = default_manager().switch_to(body.model or "")
	return {**res, **(_snapshot(body.workspace) if res.get("ok") else {})}


@router.get("/v1/local-models/log")
def get_local_model_log(request: Request, lines: int = 40) -> dict[str, Any]:
	"""llama-server 日志末若干行（加载失败时的唯一现场）。"""
	require_loopback(request)
	from localmodels import config
	from localmodels.manager import default_manager

	return {
		"ok": True,
		"lines": default_manager().tail_log(lines),
		"path": str(config.run_dir() / "llama-server.log"),
	}
