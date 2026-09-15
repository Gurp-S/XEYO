"""跨域共享依赖：单例池、统一错误构造、鉴权/供应商解析、媒体引用校验。

依赖方向约束：本模块不得 import 任何 router / app（app → routers → deps）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from model.openai_compat import PROVIDER_PRESETS
from session.workspace_path import boot_ui_cwd, xeyo_data_root
from server.session_pool import SessionPool

# hydrate 前限制客户端提供的先前回合（字符数 / 消息数）。
_MAX_PRIOR_MESSAGES = 80
_MAX_PRIOR_CHARS = 100_000
# 限制最新用户回合（#9）。
_MAX_USER_CHARS = 100_000

CWD = boot_ui_cwd()
UPLOAD_DIR = Path(os.environ.get("XEYO_UPLOAD_DIR") or (xeyo_data_root() / "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_pool = SessionPool(cwd=CWD)

_STATUS_ERROR_TYPE = {
	400: "invalid_request",
	401: "authentication_error",
	403: "permission_error",
	404: "not_found",
	409: "session_busy",
	413: "invalid_request",
	502: "model_error",
	503: "server_error",
	500: "server_error",
}


def error_body(message: str, err_type: str) -> dict[str, Any]:
	"""统一 API / SSE 错误结构：{error:{message,type}}。"""
	return {"error": {"message": message, "type": err_type}}


def _error_type_for_status(status: int) -> str:
	return _STATUS_ERROR_TYPE.get(status, "server_error")


def api_error(status: int, message: str, err_type: str | None = None) -> HTTPException:
	"""抛出 HTTPException，其 handler 输出统一错误体。"""
	return HTTPException(
		status_code=status,
		detail={
			"message": message,
			"type": err_type or _error_type_for_status(status),
		},
	)


def _extract_bearer(authorization: str | None) -> str:
	if not authorization:
		return ""
	parts = authorization.split(" ", 1)
	if len(parts) == 2 and parts[0].lower() == "bearer":
		return parts[1].strip()
	return authorization.strip()


def _resolve_base_url(provider: str, base_url: str | None) -> str:
	"""解析厂商 base_url 并做 SSRF 校验。

`X-Base-Url` 的合法用途是指向自建代理/中转站（one-api、new-api 等），
	但此前是"任意请求头原样透传"——本机任何进程都能让服务端**带着用户的
	API key** 请求任意地址（凭据外泄 + 内网探测）。

	放行口径（两条任一即可）：
	  ① 厂商 preset 自带的官方地址；
	  ② 用户在 provider/设置里显式配置过的地址（`_user_configured_base_urls`）。
	其余一律按 `tools/web_common.is_blocked_url` 判定——该函数已覆盖
	scheme 白名单、私网/环回/link-local、云元数据 IP、DNS 解析后复查，
	直接复用而不另写一份，避免"两套 SSRF 逻辑"的新双轨。
	"""
	preset = PROVIDER_PRESETS.get(provider, {})
	preset_url = preset.get("base_url", "https://api.openai.com/v1").rstrip("/")
	if not (base_url and base_url.strip()):
		return preset_url
	candidate = base_url.strip().rstrip("/")

	# 官方 preset（含同源变体，如带 /v1 后缀与否）直接放行。
	if candidate.rstrip("/") == preset_url.rstrip("/"):
		return candidate

	# 用户显式配置过的地址放行（含本地推理服务的环回地址）。
	if _is_user_configured_base_url(provider, candidate):
		return candidate

	# provider=local 且本地模型已授权：允许环回/私网（本地 llama.cpp 等）。
	if provider == "local" and local_model_allowed():
		return candidate

	from tools.web_common import is_blocked_url

	blocked = is_blocked_url(candidate)
	if blocked:
		raise api_error(
			403,
			f"base_url rejected by SSRF guard: {blocked}",
			"permission_error",
		)
	return candidate


def _is_user_configured_base_url(provider: str, candidate: str) -> bool:
	"""候选地址是否等于用户在设置中保存过的 base_url。

	设置来源：home 级 `~/.xeyo/settings.json` 与工作区级
	`<ws>/.xeyo/settings.json`（workspace 更具体者优先），字段形如
	`providers.<name>.base_url` 或 `profiles[].base_url`。读取失败一律
	视为"未配置"（fail-closed，不放行任意地址）。
	"""
	target = candidate.strip().rstrip("/")
	if not target:
		return False
	for path in _settings_paths():
		try:
			raw = json.loads(path.read_text(encoding="utf-8"))
		except Exception:  # noqa: BLE001 — 坏 JSON / 无文件 = 未配置
			continue
		for url in _iter_configured_base_urls(raw):
			if url.strip().rstrip("/") == target:
				return True
	return False


def _settings_paths() -> list[Path]:
	"""设置文件路径：workspace 级在前（更具体者优先），home 级在后。"""
	from coord.config import home_settings_path, workspace_settings_path

	paths: list[Path] = []
	try:
		ws = workspace_settings_path(_pool.cwd)
	except Exception:  # noqa: BLE001
		ws = None
	if ws is not None:
		paths.append(ws)
	try:
		paths.append(home_settings_path())
	except Exception:  # noqa: BLE001
		pass
	return paths


def _iter_configured_base_urls(node: Any) -> list[str]:
	"""递归收集设置树里所有 base_url 字符串值。"""
	found: list[str] = []
	stack: list[Any] = [node]
	while stack:
		cur = stack.pop()
		if isinstance(cur, dict):
			for key, val in cur.items():
				if isinstance(val, str) and key == "base_url":
					found.append(val)
				elif isinstance(val, (dict, list)):
					stack.append(val)
		elif isinstance(cur, list):
			stack.extend(cur)
	return found


def local_model_enabled() -> bool:
	"""provider="local"（本地 llama.cpp 等）需显式开启：XEYO_ALLOW_LOCAL_MODEL=1。

	开启后仍允许空 API key（本地推理服务通常不校验）。默认关闭，
	避免生产环境残留免鉴权的本地通道。

	注意：这是**环境变量口径**（评测 / 脚本 / CI 用）。产品路径请用
	:func:`local_model_allowed`——它把「设置面板里启用本地模型」也算作授权。
	"""
	return os.environ.get("XEYO_ALLOW_LOCAL_MODEL", "").strip().lower() in (
		"1",
		"true",
		"yes",
		"on",
	)


def local_model_allowed() -> bool:
	"""provider="local" 是否被接受：环境变量 **或** 设置面板启用本地模型。

	判定实现在 ``localmodels.gate``（单一权威）；此处只做惰性转发，避免
	模块级 import 把 ``localmodels``（会读 settings.json）拖进启动路径。
	"""
	from localmodels.gate import local_model_allowed as _allowed

	return _allowed()


def fake_model_enabled() -> bool:
	"""provider="fake"（FakeModelClient，HTTP 全栈测试用）需显式开启。

	与 ``local_model_enabled`` 同款门禁：``XEYO_ALLOW_FAKE_MODEL=1`` 才放行，
	默认关闭，避免生产环境残留免鉴权的 fake 通道。
	"""
	return os.environ.get("XEYO_ALLOW_FAKE_MODEL", "").strip().lower() in (
		"1",
		"true",
		"yes",
		"on",
	)


def _validated_media_refs(raw: list[str] | None) -> list[str]:
	"""只接受本机媒体存储生成的引用，禁止客户端伪造任意路径 URL。"""
	if not raw:
		return []
	from media_store import media_exists

	refs: list[str] = []
	for value in raw:
		ref = str(value or "").strip()
		if not ref:
			continue
		if not media_exists(ref):
			raise api_error(400, f"media_ref not found: {ref}")
		refs.append(ref)
	return refs
