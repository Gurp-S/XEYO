"""错误人话：把底层异常翻译成给用户看的中文一句话（L1.3）。

模型 401/429、缺 rg、微信掉线、lease busy —— UI 与微信展示同一句中文，
不出现 traceback。所有面向用户的出口（server SSE / bridge / channels）
统一走 ``friendly_error()``；模型客户端抛 ``ProviderError`` / ``NetworkError``
携带厂商 HTTP 状态码，避免下游靠字符串猜。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.error import URLError


class ProviderError(Exception):
	"""厂商 HTTP 错误：status_code 为厂商返回的状态码。"""

	def __init__(
		self,
		message: str,
		*,
		status_code: int | None = None,
		retry_after_ms: int | None = None,
	) -> None:
		super().__init__(message)
		self.status_code = status_code
		# 44 号：厂商 Retry-After（429/503 等），供重试环替换本地退避。
		self.retry_after_ms = retry_after_ms


class NetworkError(ProviderError):
	"""连不上模型服务（DNS / 超时 / 连接被拒）。"""

	def __init__(self, message: str) -> None:
		super().__init__(message, status_code=None)


class EmptyResponseError(ProviderError):
	"""44 号：模型返回空响应（零 chunk 正常结束）——默认可重试。"""

	def __init__(self, message: str = "model returned an empty response") -> None:
		super().__init__(message, status_code=None)


# --- 44 号：LLM 失败语义协议化（错误码归一，唯一权威分类） ---

LlmFailureCode = Literal[
	"no_adapter",
	"auth",
	"invalid_credential",
	"rate_limit",
	"context_window_exceeded",
	"empty_response",
	"timeout",
	"network",
	"provider_error",
	"unknown",
]


@dataclass(frozen=True)
class LlmFailure:
	"""LLM 调用的结构化失败事实（44 号）。

	- ``code``：稳定错误码（供引擎重试决策 / SSE 帧 / 审计 / UI 分支，不靠字符串猜）；
	- ``retryable``：是否允许同 turn 重建重试；
	- ``retry_after_ms``：厂商明示的等待时长（无则为 None，走本地退避）。
	"""

	code: LlmFailureCode
	retryable: bool
	retry_after_ms: int | None = None


def classify_llm_failure(exc: BaseException) -> LlmFailure:
	"""把 LLM 层异常归一为结构化失败（44 号分类器，唯一权威）。

	顺序：网络/超时类 → ProviderError 按状态码 → 其余 unknown（不重试）。
	忽略异常消息本体（不分析文案，避免下游猜）；只有 400 的「上下文超长」
	判定读消息——因为它不体现在状态码上。
	"""
	if isinstance(exc, NetworkError):
		return LlmFailure("network", retryable=True)
	if isinstance(exc, EmptyResponseError):
		return empty_response_failure()
	if isinstance(exc, (TimeoutError, URLError, ConnectionError)):
		# TimeoutError 与 ConnectionError 同为 OSError 子类；URLError 为 urllib 包装。
		return LlmFailure("timeout", retryable=True) if isinstance(exc, TimeoutError) else LlmFailure("network", retryable=True)
	if isinstance(exc, OSError):
		msg = str(exc).lower()
		if "connect" in msg or "timeout" in msg or "unreachable" in msg:
			return LlmFailure("network", retryable=True)
		return LlmFailure("unknown", retryable=False)
	if isinstance(exc, ProviderError):
		status = exc.status_code or 0
		retry_after = exc.retry_after_ms
		if status == 401:
			return LlmFailure("auth", retryable=False)
		if status == 403:
			return LlmFailure("invalid_credential", retryable=False)
		if status == 429:
			return LlmFailure("rate_limit", retryable=True, retry_after_ms=retry_after)
		if status == 408:
			return LlmFailure("timeout", retryable=True, retry_after_ms=retry_after)
		if 500 <= status < 600:
			return LlmFailure("provider_error", retryable=True, retry_after_ms=retry_after)
		if status == 400 and _looks_like_context_window(str(exc)):
			return LlmFailure("context_window_exceeded", retryable=False)
		return LlmFailure("provider_error", retryable=False, retry_after_ms=retry_after)
	return LlmFailure("unknown", retryable=False)


#: 400 类「上下文超长」特征（OpenAI 兼容各厂商常见措辞，覆盖常见变体）。
def _looks_like_context_window(text: str) -> bool:
	"""400 错误是否指向上下文超长（保守匹配：只认同时含 length/limit 语义的词组）。"""
	low = (text or "").lower()
	if (
		("context" in low and ("length" in low or "exceed" in low or "too long" in low))
		or ("maximum" in low and "length" in low)
		or ("too many tokens" in low)
	):
		return True
	return False


def empty_response_failure() -> LlmFailure:
	"""流完整结束但零 chunk 的失败事实（44 号：EMPTY_RESPONSE，默认可重试）。"""
	return LlmFailure("empty_response", retryable=True)


def parse_retry_after(header_value: str | None, *, now: float | None = None) -> int | None:
	"""解析 Retry-After 响应头 → 毫秒（44 号）。

	两种合法格式：delta-seconds（纯数字秒）与 HTTP-date（RFC 7231）。
	- 数字 → 秒 × 1000；
	- 日期在过去（含解析失败/空值）→ None（走本地退避）。
	"""
	if not header_value:
		return None
	raw = (header_value or "").strip()
	if not raw:
		return None
	if raw.isdigit():
		return int(raw) * 1000
	try:
		from datetime import datetime, timezone
		from email.utils import parsedate_to_datetime

		when = parsedate_to_datetime(raw)
		if when.tzinfo is None:
			when = when.replace(tzinfo=timezone.utc)
		now_f = now if now is not None else datetime.now(timezone.utc).timestamp()
		delta_s = when.timestamp() - now_f
		return int(round(delta_s * 1000)) if delta_s > 0 else None
	except Exception:  # noqa: BLE001
		return None


_STATUS_MESSAGES: dict[int, str] = {
	400: "请求参数有误（400），请检查输入后重试",
	401: "API Key 无效或已过期（401），请在设置中检查密钥后重试",
	402: "账户余额不足或需要充值（402）",
	403: "没有权限访问该模型或接口（403），请检查密钥与模型名",
	404: "模型不存在或接口地址不对（404），请检查模型名与 Base URL",
	409: "请求冲突（409），请稍后重试",
	413: "请求内容过大（413），请缩短输入",
	422: "请求参数不合法（422），请检查输入",
	429: "请求太频繁，被限流了（429），请稍等片刻再试",
	502: "网关错误（502），上游服务暂时不可用，请稍后重试",
	503: "服务暂时不可用（503），请稍后重试",
	504: "网关超时（504），模型响应过慢，请稍后重试或缩小任务范围",
}


def _first_line(text: str) -> str:
	if not text:
		return ""
	return text.strip().splitlines()[0][:400]


# 内部异常痕迹特征（T34）：出现即视为「写给开发者的消息」，不得直出给用户。
_INTERNAL_MARKERS_RE = re.compile(
	r"Traceback \(most recent call last\)"
	r'|File "[^"]+\.py"'
	r'|\.py", line \d+'
	r"|\b(?:KeyError|TypeError|AttributeError|NameError|IndexError|RuntimeError"
	r"|ValueError|OSError|JSONDecodeError|UnicodeDecodeError|RecursionError"
	r"|AssertionError|StopIteration|NotImplementedError)\b\s*:"
	r"|has no attribute"
	r"|<[^>]*?object at 0x[0-9a-fA-F]+"
	r"|\b0x[0-9a-fA-F]{8,}\b"
)
# 裸 repr：整个消息就是一个单引号字符串（如 str(KeyError("_cwd")) == "'_cwd'"）。
_BARE_REPR_RE = re.compile(r"^'[^']*'$")


def is_internal_error_text(text: str) -> bool:
	"""消息是否像内部异常痕迹（traceback / 异常类名前缀 / 对象 repr），而非人话。"""
	t = text or ""
	if _BARE_REPR_RE.fullmatch(t.strip()):
		return True
	return bool(_INTERNAL_MARKERS_RE.search(t))


def safe_error_text(text: str, *, fallback: str = "操作失败，请稍后重试；详情见服务日志") -> str:
	"""面向用户/API 的错误串安全化（T34）。

	- 内部痕迹（traceback、``KeyError: …``、对象 repr、``.py`` 路径）→ 换通用人话；
	- 有意写给用户的一句话（如 ``conflict with running turn``）→ 原样保留（首行、≤400 字）；
	- 空 → fallback（调用方可传 ``""`` 表示不追加说明）。
	"""
	raw = str(text or "").strip()
	if not raw:
		return fallback
	first = _first_line(raw)
	if is_internal_error_text(first):
		return fallback
	return sanitize_user_facing_text(first) or fallback


def safe_error_detail(exc: BaseException, *, fallback: str = "操作失败，请稍后重试；详情见服务日志") -> str:
	"""``safe_error_text`` 的异常入口：API 响应里替代裸 ``str(exc)``（T34）。"""
	return safe_error_text(str(exc), fallback=fallback)


_HTML_TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)
_HTML_H1_RE = re.compile(r"<h1[^>]*>([^<]+)</h1>", re.IGNORECASE)


def sanitize_http_body(body: str) -> str:
	"""从 HTML/JSON 错误体提取一行可读摘要，避免把整页 HTML 展示给用户。"""
	text = (body or "").strip()
	if not text:
		return ""
	lower = text.lower()
	if "<html" in lower or "<!doctype" in lower or "<body" in lower:
		title = _HTML_TITLE_RE.search(text)
		if title:
			return title.group(1).strip()
		h1 = _HTML_H1_RE.search(text)
		if h1:
			return h1.group(1).strip()
		return "HTTP 错误响应"
	if text.startswith("{") and text.endswith("}"):
		try:
			import json

			obj = json.loads(text)
		except Exception:
			return _first_line(text)
		if isinstance(obj, dict):
			err = obj.get("error")
			if isinstance(err, dict):
				msg = err.get("message")
				if isinstance(msg, str) and msg.strip():
					return msg.strip()
			msg = obj.get("message")
			if isinstance(msg, str) and msg.strip():
				return msg.strip()
		return _first_line(text)
	return _first_line(text)


def sanitize_user_facing_text(text: str) -> str:
	"""把已序列化的错误字符串（可能含 HTML）清理成一行人话。"""
	raw = sanitize_http_body(str(text or "").strip())
	if not raw:
		return ""
	lower = raw.lower()
	if "gateway time-out" in lower or "gateway timeout" in lower:
		return _STATUS_MESSAGES.get(504, "网关超时（504），请稍后重试")
	status = re.search(r"\b(4\d{2}|5\d{2})\b", raw)
	if status:
		code = int(status.group(1))
		if code in _STATUS_MESSAGES:
			return _STATUS_MESSAGES[code]
		if 500 <= code < 600:
			return f"模型服务暂时不可用（{code}），请稍后重试"
	return raw[:400]


def sanitize_agent_prose(text: str, *, limit: int = 4096) -> str:
	"""Agent 正常结论/摘要：保留多行正文；``limit`` 仅防异常膨胀，不是业务截断。

	与 ``sanitize_user_facing_text`` 不同——后者面向**错误串**，经 ``sanitize_http_body``
	会压成**首行**且再截断至 400 字，不适用于子 Agent 结论。
	若输入明显是 HTML/JSON 错误页，仍走错误消毒路径。
	"""
	raw = str(text or "").strip()
	if not raw:
		return ""
	lower = raw.lower()
	if (
		"<html" in lower
		or "<!doctype" in lower
		or "<body" in lower
		or (raw.startswith("{") and raw.endswith("}"))
	):
		cleaned = sanitize_user_facing_text(raw)
		return cleaned[:limit] if cleaned else ""
	return raw[:limit]


def provider_error_message(status_code: int, vendor_message: str = "") -> str:
	"""把厂商 HTTP 状态码翻译成中文一句话；vendor_message 仅用于补充 4xx 细节。"""
	code = int(status_code) if status_code else 0
	vendor = sanitize_http_body(vendor_message)
	base = _STATUS_MESSAGES.get(code)
	if base is not None:
		if code in (401, 402, 403, 429, 502, 503, 504):
			return base
		extra = _first_line(vendor)
		return f"{base}（{extra}）" if extra else base
	if 500 <= code < 600:
		return f"模型服务暂时不可用（{code}），请稍后重试"
	return f"模型服务返回错误（{code}）：{_first_line(vendor) or '未知错误'}"


def friendly_error(exc: BaseException, *, default: str | None = None) -> str:
	"""把异常翻译成中文一句话；未知异常保留原文（绝不出 traceback）。"""
	if isinstance(exc, NetworkError):
		return "连不上模型服务，请检查网络连接或服务地址"
	if isinstance(exc, ProviderError):
		return provider_error_message(exc.status_code or 0, str(exc))
	if isinstance(exc, URLError):
		return "连不上模型服务，请检查网络连接或服务地址"
	if isinstance(exc, TimeoutError):
		return "操作超时，请稍后重试"
	if isinstance(exc, ConnectionError):
		return "连接失败，请检查网络后重试"
	if isinstance(exc, FileNotFoundError):
		return "文件或命令不存在，请检查路径是否正确"
	msg = str(exc) or ""
	low = msg.lower()
	if "<html" in low or "<!doctype" in low or "<body" in low:
		clean = sanitize_user_facing_text(msg)
		if clean:
			return clean
	if low.startswith("error:"):
		clean = sanitize_user_facing_text(msg[6:])
		if clean:
			return clean
	if "ripgrep" in low or "check ripgrep" in low:
		return "未找到 rg（ripgrep）命令，请先安装 ripgrep 并加入 PATH"
	if "busy" in low or "lease" in low:
		return "会话正忙，请稍候或点停止后重试"
	if "has been closed" in low or "connection closed" in low:
		return "微信连接已断开，请检查微信是否正常打开，必要时重新登录"
	if "playwright" in low or "launch browser" in low:
		return "微信浏览器启动失败，请检查 Playwright 环境后重试"
	if isinstance(exc, OSError):
		if "connect" in low or "timeout" in low or "unreachable" in low:
			return "连不上模型服务，请检查网络连接或服务地址"
		detail = sanitize_user_facing_text(msg)
		if detail and not is_internal_error_text(detail):
			return f"系统错误：{detail}"
		return default if default is not None else "系统错误，请稍后重试；详情见服务日志"
	# 未知异常（T34）：不得裸出 str(exc)——内部痕迹换通用人话；
	# 有意的单行人话（≤400 字、无内部特征）仍保留。
	detail = sanitize_user_facing_text(msg)
	if detail and not is_internal_error_text(detail):
		return detail
	return default if default is not None else "操作失败，请稍后重试；详情见服务日志"
