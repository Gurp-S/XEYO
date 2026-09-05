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


def scrub_audit_fields(fields: dict[str, Any]) -> dict[str, Any]:
	"""对已知敏感字段做浅层打码（不递归改写整个 tool_input 树）。"""
	out: dict[str, Any] = {}
	for key, value in fields.items():
		if key == "command_summary" and isinstance(value, str):
			out[key] = command_summary(value)
			continue
		if key in _SENSITIVE_KEYS and isinstance(value, str):
			out[key] = redact_text(value)[:_MAX_DEFAULT]
			continue
		out[key] = value
	return out
