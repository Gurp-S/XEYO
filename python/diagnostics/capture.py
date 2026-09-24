"""可选的最终请求体捕获（可复现记录档）。

三件事必须成立：

1. 开关关掉时**零影响**：不写盘、不改 body、不改变模型可见消息。
2. 开关打开时也不改 body：捕获用深拷贝，凭证与认证头一律不入产物。
3. 被截断、被脱敏、写失败的一律标 ``partial`` / ``redacted``，不得冒充精确回放。

"实际请求体"指适配器交给 HTTP 客户端的 JSON，不宣称看到厂商内部最终输入。
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from diagnostics import store
from diagnostics.identity import COMPLETE, NOT_CAPTURED, PARTIAL, REDACTED, _s

_MAX_BODY_BYTES = 8 * 1024 * 1024
_CONFIG_NAME = "capture_config.json"

_SECRET_KEYS = frozenset(
	{
		"api_key",
		"apikey",
		"authorization",
		"proxy_authorization",
		"token",
		"access_token",
		"id_token",
		"refresh_token",
		"secret",
		"client_secret",
		"secret_key",
		"security_token",
		"password",
		"passwd",
	}
)
_SECRET_SUFFIXES = ("_key", "_token", "_secret", "_password", "_passwd")


def _is_secret_key(name: str) -> bool:
	"""按键名判定凭证字段。

	早先用子串匹配，``token`` 命中了每个 OpenAI/Anthropic body 的 ``max_tokens``
	⇒ 所有捕获都被打成 redacted、有效参数被抹掉，可复现记录直接失去意义。
	"""
	normalized = _s(name).lower().replace("-", "_").replace(" ", "_")
	if not normalized:
		return False
	if normalized in _SECRET_KEYS:
		return True
	return normalized.endswith(_SECRET_SUFFIXES)


def config_path() -> Path:
	return store.diagnostics_root() / _CONFIG_NAME


def _env_sessions() -> set[str]:
	raw = os.environ.get("XEYO_DIAGNOSTICS_CAPTURE_SESSIONS", "")
	return {s.strip() for s in raw.split(",") if s.strip()}


def _config() -> dict[str, Any]:
	doc = store.read_json(config_path()) or {}
	sessions = doc.get("sessions")
	return {
		"default_enabled": bool(doc.get("default_enabled", False)),
		"sessions": sessions if isinstance(sessions, dict) else {},
	}


def capture_enabled(session_id: str) -> bool:
	sid = _s(session_id)
	if sid in _env_sessions():
		return True
	cfg = _config()
	entry = cfg["sessions"].get(sid)
	if isinstance(entry, dict):
		return bool(entry.get("enabled"))
	return bool(cfg["default_enabled"])


def set_capture_enabled(
	session_id: str,
	enabled: bool,
	*,
	max_bytes: int | None = None,
	note: str = "",
) -> dict[str, Any]:
	store.ensure_dirs()
	sid = _s(session_id)
	if not sid:
		raise ValueError("set_capture_enabled 需要 session_id")
	cfg = _config()
	sessions = dict(cfg["sessions"])
	if enabled:
		sessions[sid] = {
			"enabled": True,
			"since_ts": round(time.time(), 3),
			"max_bytes": int(max_bytes or 0),
			"note": _s(note),
		}
	else:
		sessions.pop(sid, None)
	doc = {"default_enabled": cfg["default_enabled"], "sessions": sessions}
	store.write_json(config_path(), doc)
	return doc


def _hash_body(payload: Any) -> tuple[str, str | None]:
	"""规范化 JSON hash。返回 ``(hash, error)``；序列化失败不得伪装成 hash。"""
	try:
		serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
	except (TypeError, ValueError) as exc:  # noqa: BLE001
		return "", f"{type(exc).__name__}: {exc}"
	return hashlib.sha256(serialized.encode("utf-8", "replace")).hexdigest(), None


_SCHEME_RX = re.compile(r"(?i)\b(bearer|basic)\s+([A-Za-z0-9._\-/+=]{6,})")
_ASSIGN_RX = re.compile(
	r"(?i)(\b(?:authorization|proxy-authorization|api[_-]?key|x-api-key|token|secret|password)\b\s*[=:]\s*)"
	r"(?:(?:bearer|basic)\s+)?([^\s\"',;]+)"
)


def _scrub_value(text: str) -> str:
	"""值级打码。

	必须先于 ``audit.redact.redact_text``：后者的 authorization 分支只吃到第一个
	空格，会把 ``Authorization: Bearer <token>`` 打成 ``*** <token>``，剩下的半截
	反而再没有可匹配的形状。捕获的是完整请求正文，敏感度高于审计字段。
	"""
	text = _ASSIGN_RX.sub(lambda m: f"{m.group(1)}[redacted]", text)
	text = _SCHEME_RX.sub(lambda m: f"{m.group(1)} [redacted]", text)
	try:
		from audit.redact import redact_text

		return redact_text(text)
	except Exception:  # noqa: BLE001 — 打码器不可用时保守拒绝入库
		return "[redacted]"


def _scrub(value: Any) -> tuple[Any, bool]:
	"""把疑似凭证替换掉；返回 (新值, 是否改动过)。"""
	changed = False
	if isinstance(value, dict):
		out: dict[str, Any] = {}
		for key, item in value.items():
			if _is_secret_key(_s(key)):
				out[key] = "[redacted]"
				changed = True
				continue
			cleaned, did = _scrub(item)
			out[key] = cleaned
			changed = changed or did
		return out, changed
	if isinstance(value, list):
		items: list[Any] = []
		for item in value:
			cleaned, did = _scrub(item)
			items.append(cleaned)
			changed = changed or did
		return items, changed
	if isinstance(value, str):
		cleaned = _scrub_value(value)
		return cleaned, cleaned != value
	return value, False


def _capture_locator(body_hash: str) -> Path:
	return store.captures_dir() / body_hash[:2] / f"{body_hash}.json.gz"


def index_path() -> Path:
	return store.captures_dir() / "index.jsonl"


def _append_index(row: dict[str, Any]) -> None:
	store.append_jsonl(index_path(), row)


def capture_request(
	*,
	session_id: str,
	turn_id: str = "",
	model_request_id: str = "",
	attempt: int | None = None,
	provider: str = "",
	model: str = "",
	body: Any,
	params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
	"""适配器发送前调用。热路径必须便宜：未开启时只做一次字典判断。

	任何写入失败都只记进索引，绝不向上抛——诊断不得改变任务结果。
	"""
	sid = _s(session_id)
	if not sid or not capture_enabled(sid):
		return None
	try:
		return _capture(
			session_id=sid,
			turn_id=turn_id,
			model_request_id=model_request_id,
			attempt=attempt,
			provider=provider,
			model=model,
			body=body,
			params=params,
		)
	except Exception as exc:  # noqa: BLE001 — 捕获故障不得阻断采样
		logging.getLogger(__name__).debug("request capture failed", exc_info=True)
		return {"state": PARTIAL, "error": f"{type(exc).__name__}: {exc}"[:200]}


def _capture(
	*,
	session_id: str,
	turn_id: str,
	model_request_id: str,
	attempt: int | None,
	provider: str,
	model: str,
	body: Any,
	params: dict[str, Any] | None,
) -> dict[str, Any]:
	store.ensure_dirs()
	payload = copy.deepcopy(body)
	scrubbed, redacted = _scrub(payload)
	hashed, error = _hash_body(scrubbed)
	ts = round(time.time(), 3)
	row: dict[str, Any] = {
		"ts": ts,
		"session_id": session_id,
		"turn_id": _s(turn_id),
		"model_request_id": _s(model_request_id),
		"attempt": attempt,
		"provider": _s(provider),
		"model": _s(model),
		"state": REDACTED if redacted else COMPLETE,
		"body_hash": hashed,
	}
	if error:
		row["state"] = PARTIAL
		row["error"] = error
		row["body_hash"] = "unserializable_" + hashlib.sha256(repr(body).encode("utf-8", "replace")).hexdigest()[:16]
		_append_index(row)
		return row
	_BODY_CONTENT_KEYS = frozenset({"messages", "system", "tools", "input"})
	derived_params = dict(params or {})
	if not derived_params and isinstance(scrubbed, dict):
		# 有效参数就在 body 本身；不在发送点序列化，只在真正落盘时派生。
		derived_params = {
			key: value
			for key, value in scrubbed.items()
			if key not in _BODY_CONTENT_KEYS
		}
	doc = {
		"schema_version": 1,
		"captured_at": ts,
		"session_id": session_id,
		"turn_id": _s(turn_id),
		"model_request_id": _s(model_request_id),
		"attempt": attempt,
		"provider": _s(provider),
		"model": _s(model),
		"request_body_hash": hashed,
		"state": row["state"],
		"effective_params": derived_params,
		"effective_params_source": "caller" if params else "derived_from_body",
		"body": scrubbed,
	}
	serialized = json.dumps(doc, ensure_ascii=False, sort_keys=True).encode("utf-8")
	row["bytes"] = len(serialized)
	if len(serialized) > _MAX_BODY_BYTES:
		row["state"] = PARTIAL
		row["note"] = f"超过 {_MAX_BODY_BYTES} 字节上限，正文未落盘，仅留 hash"
		_append_index(row)
		store.enforce_quota()
		return row
	target = _capture_locator(hashed)
	existed = target.is_file()
	row["deduped"] = existed
	if not existed:
		tmp = target.with_name(target.name + ".tmp")
		try:
			target.parent.mkdir(parents=True, exist_ok=True)
			with tmp.open("wb") as handle:
				handle.write(gzip.compress(serialized, compresslevel=6))
			os.replace(tmp, target)
		except OSError as exc:
			row["state"] = PARTIAL
			row["note"] = f"写入失败：{type(exc).__name__}"
			try:
				tmp.unlink()  # 写失败的残片不会被配额清理再次回收
			except OSError:
				pass
	_append_index(dict(row))
	quota = store.enforce_quota()
	if quota.get("shortfall"):
		row["quota_shortfall"] = quota["shortfall"]
	return row


def record_response(
	*,
	session_id: str,
	model_request_id: str,
	attempt: int | None,
	body_hash: str = "",
	provider_request_id: str = "",
	http_status: int | None = None,
	usage: dict[str, Any] | None = None,
) -> None:
	"""把厂商侧响应身份挂到同一 attempt 的捕获上（拿不到就留空，不编造）。"""
	sid = _s(session_id)
	if not sid or not capture_enabled(sid):
		return
	try:
		_append_index(
			{
				"ts": round(time.time(), 3),
				"type": "response",
				"session_id": sid,
				"model_request_id": _s(model_request_id),
				"attempt": attempt,
				"body_hash": _s(body_hash),
				"provider_request_id": _s(provider_request_id),
				"http_status": http_status,
				"usage_present": bool(usage),
			}
		)
	except Exception:  # noqa: BLE001
		logging.getLogger(__name__).debug("response identity capture failed", exc_info=True)


def _index_rows(*, session_id: str = "") -> list[dict[str, Any]]:
	rows = store.read_jsonl(index_path(), limit=20000)
	sid = _s(session_id)
	if not sid:
		return rows
	return [row for row in rows if _s(row.get("session_id")) == sid]


def captures_for_run(session_id: str, turn_id: str = "") -> list[dict[str, Any]]:
	"""按 (model_request_id, attempt) 把请求捕获与响应身份配成一行。"""
	rows = _index_rows(session_id=session_id)
	requests = [r for r in rows if r.get("body_hash") and r.get("type") != "response"]
	responses: dict[str, dict[str, Any]] = {}
	for row in rows:
		if row.get("type") == "response":
			responses[f"{_s(row.get('model_request_id'))}|{row.get('attempt')}"] = row
	out: list[dict[str, Any]] = []
	for row in requests:
		if turn_id and _s(row.get("turn_id")) and _s(row.get("turn_id")) != turn_id:
			continue
		resp = responses.get(f"{_s(row.get('model_request_id'))}|{row.get('attempt')}") or {}
		hashed = _s(row.get("body_hash"))
		target = _capture_locator(hashed)
		out.append(
			dict(row)
			| {
				"locator": str(target) if target.is_file() else "",
				"blob_present": target.is_file(),
				"provider_request_id": _s(resp.get("provider_request_id")),
				"http_status": resp.get("http_status"),
			}
		)
	if not out:
		return []
	return out


def resolve_capture(body_hash: str) -> dict[str, Any]:
	"""取回捕获正文。缺 blob 或被标 partial 时必须说出来，不返回空 body 冒充成功。"""
	hashed = _s(body_hash)
	if not hashed:
		return {"state": NOT_CAPTURED, "error": "缺 body_hash"}
	target = _capture_locator(hashed)
	if not target.is_file():
		expired = any(r.get("body_hash") == hashed for r in _index_rows())
		return {
			"state": "expired" if expired else NOT_CAPTURED,
			"body_hash": hashed,
			"error": "索引里有该 hash，正文已不在盘上（配额清理或从未写入）" if expired else "无此捕获",
		}
	try:
		with gzip.open(target, "rb") as handle:
			doc = json.loads(handle.read().decode("utf-8", "replace"))
	except Exception as exc:  # noqa: BLE001
		return {"state": PARTIAL, "body_hash": hashed, "error": f"{type(exc).__name__}: {exc}"[:200]}
	if not isinstance(doc, dict):
		return {"state": PARTIAL, "body_hash": hashed, "error": "产物不是对象"}
	verified, _err = _hash_body(doc.get("body"))
	return doc | {
		"hash_matches": verified == hashed,
		"locator": str(target),
	}


def capture_disk_bytes() -> int:
	return store.dir_size(store.captures_dir())


__all__ = [
	"capture_disk_bytes",
	"capture_enabled",
	"capture_request",
	"captures_for_run",
	"config_path",
	"record_response",
	"resolve_capture",
	"set_capture_enabled",
]
