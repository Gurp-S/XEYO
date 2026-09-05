"""T34 错误人话化测试：内部异常痕迹不出 API / 通道；有意人话保留。"""

from __future__ import annotations

from common.errors import (
	friendly_error,
	is_internal_error_text,
	safe_error_detail,
	safe_error_text,
)


# ---------- is_internal_error_text ----------


def test_internal_markers_detected() -> None:
	assert is_internal_error_text("Traceback (most recent call last):")
	assert is_internal_error_text('File "D:\\x\\y.py", line 12, in f')
	assert is_internal_error_text("KeyError: '_cwd'")
	assert is_internal_error_text("AttributeError: 'SessionPool' object has no attribute '_cwd'")
	assert is_internal_error_text("<SessionPool object at 0x1a2b3c4d5e>")


def test_user_facing_one_liners_not_flagged() -> None:
	assert not is_internal_error_text("conflict with running turn")
	assert not is_internal_error_text("target message not found")
	assert not is_internal_error_text("image too large (max 8 bytes)")
	assert not is_internal_error_text("会话正忙，请稍候")


# ---------- safe_error_detail / safe_error_text ----------


def test_safe_error_detail_hides_internal_trace() -> None:
	out = safe_error_detail(AttributeError("'SessionPool' object has no attribute '_cwd'"))
	assert "_cwd" not in out
	assert "AttributeError" not in out
	assert out  # 通用人话兜底


def test_safe_error_detail_keeps_intentional_message() -> None:
	class RollbackConflictError(Exception):
		pass

	out = safe_error_detail(RollbackConflictError("conflict with running turn"))
	assert out == "conflict with running turn"


def test_safe_error_text_empty_fallback() -> None:
	assert safe_error_text("", fallback="") == ""
	assert safe_error_text("  ", fallback="x") == "x"


def test_safe_error_text_multiline_takes_first_line() -> None:
	out = safe_error_text("first line for user\nINTERNAL DETAILS: KeyError: boom")
	assert out.startswith("first line for user")


# ---------- friendly_error 兜底不再裸出 ----------


def test_friendly_error_unknown_exception_no_internal_text() -> None:
	out = friendly_error(KeyError("_cwd"))
	assert "_cwd" not in out
	assert "KeyError" not in out


def test_friendly_error_keeps_known_patterns() -> None:
	assert "ripgrep" in friendly_error(RuntimeError("please check ripgrep install"))
	assert "正忙" in friendly_error(RuntimeError("session is busy"))
	assert "微信" in friendly_error(RuntimeError("connection has been closed"))


def test_friendly_error_provider_unchanged() -> None:
	from common.errors import ProviderError

	assert "429" in friendly_error(ProviderError("rate limited", status_code=429))


def test_friendly_error_default_precedence() -> None:
	out = friendly_error(KeyError("_cwd"), default="自定义默认话术")
	assert out == "自定义默认话术"
