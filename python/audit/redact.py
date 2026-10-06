"""审计字段打码：命令摘要截断 + 简单密钥/token 遮罩。"""

from __future__ import annotations

import re
from typing import Any

_MAX_DEFAULT = 200

# 常见密钥形态：Bearer / API key / 长 hex / 密码赋值
_SECRET_RX = re.compile(
	r"(?i)("
	r"(?:bearer\s+)[a-z0-9._\-]{8,}"
	r"|(?:api[_-]?key|token|secret|password|passwd|authorization)"
	r"\s*[=:]\s*['\"]?[^\s'\"]{6,}"
	r"|(?:sk|pk|ghp|glpat|xox[baprs])-[a-z0-9\-_]{10,}"
	r"|akia[0-9a-z]{16}"  # AWS Access Key (AKIA...)
	r"|aiza[0-9a-z_\-]{35}"  # GCP API key (AIza...)
	r"|eyj[a-z0-9_\-]{10,}\.[a-z0-9_\-]{10,}\.[a-z0-9_\-]{8,}"  # JWT
	r"|-----begin[^-]+-----[\s\S]*?-----end[^-]+-----"  # PEM 私钥块
	r"|[a-f0-9]{32,}"
	r")"
)

_SENSITIVE_KEYS = frozenset(
	{
		"command",
		"prompt",
		"tool_input",
		"content",
		"password",
		"token",
		"api_key",
		"authorization",
	}
)


def redact_text(text: str) -> str:
	"""遮罩文本中的疑似密钥片段。"""
	if not text:
		return ""
	return _SECRET_RX.sub("***", text)


def command_summary(command: str | None, *, max_len: int = _MAX_DEFAULT) -> str:
	"""Bash 命令审计/推送摘要：打码后截断。"""
	raw = (command or "").strip().replace("\r\n", "\n").replace("\r", "\n")
	raw = re.sub(r"[ \t\f\v]+", " ", raw)
	redacted = redact_text(raw)
	if len(redacted) <= max_len:
		return redacted
	return redacted[: max(0, max_len - 1)] + "…"


#: 嵌套扫描深度上限：真实工具入参远达不到；上限只为把恶意深嵌套的遍历成本变得有界。
_SCRUB_MAX_DEPTH = 8


def scrub_audit_fields(fields: dict[str, Any]) -> dict[str, Any]:
	"""对已知敏感字段打码；嵌套 dict/list **逐层同规则**。

	此前浅层实现只打码顶层字符串，`tool_input` 树内嵌套的
	`headers.authorization` / `token` 等敏感键会**明文落审计**（2026-10-05
	复核 09-10 P1-16）。递归后语义与顶层一致：敏感键名命中才打码，中性键原样。
	"""
	return {key: _scrub_value(key, value, _SCRUB_MAX_DEPTH) for key, value in fields.items()}


def _scrub_value(key: str, value: Any, depth: int) -> Any:
	if isinstance(value, str):
		if key == "command_summary":
			return command_summary(value)
		if key in _SENSITIVE_KEYS:
			return redact_text(value)[:_MAX_DEFAULT]
		return value
	if depth <= 0:
		return value
	if isinstance(value, dict):
		return {str(k): _scrub_value(str(k), v, depth - 1) for k, v in value.items()}
	if isinstance(value, list):
		return [_scrub_value(key, v, depth - 1) for v in value]
	return value
