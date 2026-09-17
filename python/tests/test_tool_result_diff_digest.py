"""工具结果 diff 摘要化契约测试（旁路档，``XEYO_TOOL_RESULT_DIFF``）。

守三件事：
1. 旁路档（默认）逐字节等于既有行为——投影不被触碰（零拷贝同一对象）。
2. digest 档只剥文件改动类工具结果里的 ```diff 围栏；确认行 / ``+N -M`` /
   Diagnostics 提示全留，非文件工具（Bash 里恰好打印 ```diff）绝不误伤。
3. 幂等 + fail-safe：重复应用结果不变；非法档位落回 full。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prompt import tool_result_diff_digest as digest
from prompt.fence import fence_tool_output


def _tool_msg(name: str, content: str, *, uid: str = "c1") -> dict:
	return {
		"role": "tool",
		"name": name,
		"tool_call_id": uid,
		"content": [{"type": "tool_result", "tool_use_id": uid, "content": content}],
	}


EDIT_RESULT = (
	"The file D:\\lea\\XenYon code\\python\\prompt\\inject_store.py has been updated "
	"successfully. +25 -7\n"
	"\n"
	"```diff\n"
	"--- a/inject_store.py\n"
	"+++ b/inject_store.py\n"
	"@@ -96,7 +96,7 @@\n"
	"-	old line\n"
	"+	new line\n"
	"```\n"
	"Hint: Diagnostics path=D:\\lea\\XenYon code\\python\\prompt\\inject_store.py"
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
	monkeypatch.delenv(digest.MODE_ENV, raising=False)
	yield
	monkeypatch.delenv(digest.MODE_ENV, raising=False)


# ---------------------------------------------------------------- 默认档（digest）


def test_default_mode_is_digest():
	assert digest.mode() == digest.MODE_DIGEST
	assert digest.digest_enabled() is True


def test_default_mode_strips_diff_without_env():
	"""未设置开关 = 主链路档：投影里不再带 diff。"""
	out = digest.apply_tool_result_digest([_tool_msg("Edit", EDIT_RESULT)])
	assert "```diff" not in out[0]["content"][0]["content"]


@pytest.mark.parametrize("bad", ["", "on", "digest_", "1", "digest2"])
def test_illegal_mode_falls_back_to_default(monkeypatch, bad):
	monkeypatch.setenv(digest.MODE_ENV, bad)
	assert digest.mode() == digest.MODE_DIGEST


@pytest.mark.parametrize("written", ["digest", "DIGEST", "  Digest  "])
def test_mode_tolerates_case_and_padding(monkeypatch, written):
	monkeypatch.setenv(digest.MODE_ENV, written)
	assert digest.mode() == digest.MODE_DIGEST


# ---------------------------------------------------------------- 逃生门（full）


def test_full_mode_is_escape_hatch(monkeypatch):
	monkeypatch.setenv(digest.MODE_ENV, digest.MODE_FULL)
	assert digest.digest_enabled() is False
	msgs = [_tool_msg("Edit", EDIT_RESULT)]
	out = digest.apply_tool_result_digest(msgs)
	assert out is msgs
	assert out[0]["content"][0]["content"] == EDIT_RESULT


# ---------------------------------------------------------------- digest 档


def test_digest_strips_diff_keeps_facts(monkeypatch):
	monkeypatch.setenv(digest.MODE_ENV, digest.MODE_DIGEST)
	out = digest.apply_tool_result_digest([_tool_msg("Edit", EDIT_RESULT)])
	body = out[0]["content"][0]["content"]
	assert "```diff" not in body
	assert "has been updated successfully. +25 -7" in body
	assert "Hint: Diagnostics path=" in body


def test_digest_is_idempotent(monkeypatch):
	monkeypatch.setenv(digest.MODE_ENV, digest.MODE_DIGEST)
	once = digest.apply_tool_result_digest([_tool_msg("Edit", EDIT_RESULT)])
	twice = digest.apply_tool_result_digest(once)
	assert twice[0]["content"][0]["content"] == once[0]["content"][0]["content"]


def test_digest_leaves_non_file_tools_alone(monkeypatch):
	"""Bash 输出里的 ```diff 是真实数据，不是展示围栏。"""
	monkeypatch.setenv(digest.MODE_ENV, digest.MODE_DIGEST)
	raw = "git diff output:\n```diff\n-x\n+y\n```"
	out = digest.apply_tool_result_digest([_tool_msg("Bash", raw)])
	assert out[0]["content"][0]["content"] == raw


def test_digest_targets_write_and_notebook(monkeypatch):
	monkeypatch.setenv(digest.MODE_ENV, digest.MODE_DIGEST)
	for name in ("Write", "NotebookEdit"):
		out = digest.apply_tool_result_digest([_tool_msg(name, EDIT_RESULT)])
		assert "```diff" not in out[0]["content"][0]["content"]


def test_digest_reads_tool_name_from_gamma4_fence(monkeypatch):
	"""投影里 msg["name"] 缺失时，靠 γ4 围栏自带的 tool 属性识别。"""
	monkeypatch.setenv(digest.MODE_ENV, digest.MODE_DIGEST)
	fenced = fence_tool_output("Edit", EDIT_RESULT)
	msg = _tool_msg("", fenced)
	out = digest.apply_tool_result_digest([msg], id_to_name={"c1": "Edit"})
	body = out[0]["content"][0]["content"]
	assert "```diff" not in body
	assert body.startswith('<tool_output tool="Edit"')


def test_unknown_tool_name_keeps_content(monkeypatch):
	monkeypatch.setenv(digest.MODE_ENV, digest.MODE_DIGEST)
	out = digest.apply_tool_result_digest([_tool_msg("", EDIT_RESULT)])
	assert out[0]["content"][0]["content"] == EDIT_RESULT


def test_digest_ignores_non_tool_result_shapes(monkeypatch):
	monkeypatch.setenv(digest.MODE_ENV, digest.MODE_DIGEST)
	msgs = [
		{"role": "user", "content": EDIT_RESULT},
		_tool_msg("Edit", "plain text without fence"),
		{"role": "tool", "name": "Edit", "content": "not-a-list"},
	]
	out = digest.apply_tool_result_digest(msgs)
	assert out[0] is msgs[0]
	assert out[1]["content"][0]["content"] == "plain text without fence"
	assert out[2] is msgs[2]


def test_strip_diff_fence_noop_without_fence():
	assert digest.strip_diff_fence("nothing here") == "nothing here"
	assert digest.strip_diff_fence("") == ""
