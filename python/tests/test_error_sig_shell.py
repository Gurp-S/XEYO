"""错误签名不得把分隔线当签名（#21）：短摘要要能看出是哪条断言。

现场（本会话热摘要实测）：``[UNRESOLVED] 未解决: AssertionError: ======= short test summary info =======``
——签名里唯一内容是分隔线，恢复后看不出失败在哪。
根因：签名模式把异常类之后的"前 120 字符"当片段，而 pytest 失败块首行常是分隔线。
"""

from __future__ import annotations

from synaptic.textutil import extract_error_sig

_SHELL = "=" * 27


def test_shell_fragment_is_replaced_by_pytest_assert_line() -> None:
	"""片段是分隔线 ⇒ 换成 `E   AssertionError: …` 那行的实质内容。"""
	text = (
		f"AssertionError: {_SHELL} short test summary info {_SHELL}\n"
		"____________ test_x ____________\n"
		"E   AssertionError: assert 'a' == 'b'\n"
	)
	sig = extract_error_sig(text)
	assert "====" not in sig, sig
	assert "'a' == 'b'" in sig, sig


def test_shell_fragment_falls_back_to_short_summary_failed_line() -> None:
	"""没有断言行时，用 short summary 的 `FAILED <nodeid> - …`（那句带用例名与期望值）。"""
	text = (
		f"AssertionError: {_SHELL} short test summary info {_SHELL}\n"
		"FAILED python/tests/test_x.py::test_alpha - AssertionError: expected 1000 got 3000\n"
	)
	sig = extract_error_sig(text)
	assert "====" not in sig, sig
	assert "test_alpha" in sig, sig
	assert "expected 1000 got 3000" in sig, sig


def test_shell_only_fragment_keeps_exception_class_alone() -> None:
	"""实在没别的 ⇒ 只留异常类：`AssertionError` 比 `AssertionError: ====…` 有信息量。"""
	sig = extract_error_sig(f"AssertionError: {_SHELL} short test summary info {_SHELL}\n")
	assert sig == "AssertionError", sig


def test_plain_signature_is_unchanged() -> None:
	"""正控：普通签名逐字节不变（新逻辑只作用于"片段是空壳"那一支）。"""
	assert extract_error_sig("ValueError: boom") == "ValueError: boom"
	assert extract_error_sig("AssertionError: assert 1 == 2") == "AssertionError: assert 1 == 2"


def test_underscored_test_name_is_not_treated_as_shell() -> None:
	"""正控：`______ test_name ______` 带着用例名 ⇒ 是真信息，不许被当空壳剔除。"""
	text = "AssertionError: ______________ test_denial_renders_under_constraints ______________\n"
	sig = extract_error_sig(text)
	assert "test_denial_renders_under_constraints" in sig, sig
