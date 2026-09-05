"""44 号 A1：LLM 失败语义协议化——错误码分类器矩阵。

覆盖：ProviderError 状态码 × 类型分类；retry_after_ms 透传；网络/超时类；
400 上下文超长识别；EMPTY_RESPONSE 事实；未知异常 fail-closed 不重试。
"""

from __future__ import annotations

from urllib.error import URLError

from common.errors import (
	LlmFailure,
	NetworkError,
	ProviderError,
	classify_llm_failure,
	empty_response_failure,
	parse_retry_after,
)


def test_network_error_classified_retryable() -> None:
	f = classify_llm_failure(NetworkError("connection refused"))
	assert f.code == "network"
	assert f.retryable is True
	assert f.retry_after_ms is None


def test_urlerror_classified_network() -> None:
	f = classify_llm_failure(URLError("timed out"))
	assert f.code == "network"
	assert f.retryable is True


def test_timeout_classified() -> None:
	f = classify_llm_failure(TimeoutError("read timed out"))
	assert f.code == "timeout"
	assert f.retryable is True


def test_401_auth_not_retryable() -> None:
	f = classify_llm_failure(ProviderError("invalid api key", status_code=401))
	assert f.code == "auth"
	assert f.retryable is False


def test_403_invalid_credential() -> None:
	f = classify_llm_failure(ProviderError("no permission", status_code=403))
	assert f.code == "invalid_credential"
	assert f.retryable is False


def test_429_rate_limit_retryable_with_retry_after() -> None:
	f = classify_llm_failure(
		ProviderError("rate limited", status_code=429, retry_after_ms=2500)
	)
	assert f.code == "rate_limit"
	assert f.retryable is True
	assert f.retry_after_ms == 2500


def test_429_without_retry_after_falls_back_local_backoff() -> None:
	f = classify_llm_failure(ProviderError("rate limited", status_code=429))
	assert f.code == "rate_limit"
	assert f.retryable is True
	assert f.retry_after_ms is None


def test_5xx_provider_error_retryable() -> None:
	for status in (500, 502, 503, 504):
		f = classify_llm_failure(ProviderError("upstream error", status_code=status))
		assert f.code == "provider_error", status
		assert f.retryable is True, status


def test_400_context_window_exceeded_not_retryable() -> None:
	f = classify_llm_failure(
		ProviderError("This model's maximum context length is 65536 tokens", status_code=400)
	)
	assert f.code == "context_window_exceeded"
	assert f.retryable is False


def test_400_generic_provider_error_not_retryable() -> None:
	f = classify_llm_failure(ProviderError("bad request shape", status_code=400))
	assert f.code == "provider_error"
	assert f.retryable is False


def test_402_not_retryable() -> None:
	f = classify_llm_failure(ProviderError("insufficient balance", status_code=402))
	assert f.code == "provider_error"
	assert f.retryable is False


def test_unknown_exception_fail_closed() -> None:
	f = classify_llm_failure(PermissionError("boom"))
	assert f.code == "unknown"
	assert f.retryable is False


def test_oserror_connect_network() -> None:
	f = classify_llm_failure(OSError("Failed to connect to api"))
	assert f.code == "network"
	assert f.retryable is True


def test_empty_response_failure() -> None:
	f = empty_response_failure()
	assert isinstance(f, LlmFailure)
	assert f.code == "empty_response"
	assert f.retryable is True
	assert f.retry_after_ms is None


def test_provider_error_retry_after_passthrough_on_503() -> None:
	f = classify_llm_failure(
		ProviderError("overloaded", status_code=503, retry_after_ms=5000)
	)
	assert f.retry_after_ms == 5000
	assert f.retryable is True


# --- 44 号：Retry-After 头解析（适配器 → ProviderError.retry_after_ms） ---

def test_retry_after_delta_seconds() -> None:
	assert parse_retry_after("120") == 120000


def test_retry_after_http_date_future() -> None:
	# RFC 7231 日期：now=2026-10-01T00:00:00Z，头给 00:10:00Z → +600s。
	fixed = 1790812800.0  # 2026-10-01T00:00:00Z
	header = "Thu, 01 Oct 2026 00:10:00 GMT"
	d = parse_retry_after(header, now=fixed)
	assert d is not None
	assert 590_000 <= d <= 610_000


def test_retry_after_http_date_past_returns_none() -> None:
	fixed = 1790812800.0
	header = "Thu, 01 Oct 2026 00:00:00 GMT"  # 与 now 相同 → delta 0 → None
	assert parse_retry_after(header, now=fixed) is None


def test_retry_after_empty_or_garbage_none() -> None:
	assert parse_retry_after(None) is None
	assert parse_retry_after("") is None
	assert parse_retry_after("not-a-date") is None
