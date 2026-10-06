"""参数级拒绝必须带 error_kind，诊断层才分得清是谁的错。

起因：`diagnostics/rules.py` 与 `diagnostics/fault_split.py` 早就按 error_kind 分归属，
但生产侧除了 `job_tools`/`tool_registry` 之外没人填过——`tools/base_tool.py` 把
`is_error=True` 且没标的结果一律兜成 INTERNAL，而这两个模块**明写 INTERNAL 不是分类**
（2026-09-25 实测非空 error_kind 100% 是 INTERNAL）⇒ 归属表从未被真实数据读到。

这里钉四件事：
1) 参数缺失/枚举非法/形状错的拒绝 → INVALID_ARGUMENT（模型侧）；
2) 状态查不到（"unknown note <id>"）**故意不标**：NOT_FOUND 在 fault_split 里算环境侧，
   把模型写错的 id 判给环境是新的假话，留 INTERNAL=诚实的"没分类"；
3) 成功回执不许被顺手标上 error_kind；
4) （2026-10-05 摘账）Grep/Glob/Read/Edit 家族补账：参数拒绝 → INVALID_ARGUMENT、
   模型给的目标不存在 → 故意 INTERNAL、rg 正则解析错 → INVALID_ARGUMENT、
   搜索超时 → TIMEOUT。
"""

from __future__ import annotations

import pytest

from engine.abort import AbortController
from tools.catalog import build_default_registry
from tools.error_taxonomy import INTERNAL, INVALID_ARGUMENT, TIMEOUT


@pytest.fixture()
def reg(tmp_path, monkeypatch):
	monkeypatch.setenv("XEYO_HOME", str(tmp_path / "home"))
	monkeypatch.setenv("XEYO_MEMORY_DIR", str(tmp_path / "home" / "memory"))
	monkeypatch.setenv("XEYO_SESSIONS_DIR", str(tmp_path / "sessions"))
	proj = tmp_path / "proj"
	proj.mkdir()
	return build_default_registry(cwd=str(proj))


async def _run(reg, name, payload):
	return await reg.get(name).execute(dict(payload), AbortController())


@pytest.mark.asyncio
@pytest.mark.parametrize(
	"tool,payload,needle",
	[
		("Memory", {}, "unknown action"),
		("Memory", {"action": "update"}, "requires id"),
		("Memory", {"action": "search"}, "requires query"),
		("Memory", {"action": "retrieve"}, "requires id"),
		("Git", {}, "action is required"),
		("Git", {"action": "diff"}, "path is required"),
		("Diagnostics", {}, "path is required"),
		("WebSearch", {"query": "   "}, "query is required"),
	],
)
async def test_argument_rejections_are_classified(reg, tool, payload, needle):
	res = await _run(reg, tool, payload)
	assert res.is_error is True
	assert needle in res.content, res.content
	assert res.error_kind == INVALID_ARGUMENT, (
		f"{tool} 的参数拒绝被兜成 {res.error_kind}，诊断层只能记成"
		"「没分类」或误判我方引擎"
	)


@pytest.mark.asyncio
async def test_missing_note_stays_honestly_unclassified(reg):
	res = await _run(reg, "Memory", {"action": "forget", "id": "mem_deadbeef"})
	assert res.is_error is True
	assert "unknown note" in res.content
	# 故意保持 INTERNAL：NOT_FOUND 会被 fault_split 判给环境侧，
	# 而这里真正失败的是调用方给的 id；两者都不该被硬塞进对方那一栏。
	assert res.error_kind == INTERNAL


@pytest.mark.asyncio
async def test_success_receipts_are_not_labelled(reg):
	res = await _run(
		reg,
		"Memory",
		{
			"action": "write",
			"scope": "workspace",
			"title": "标注门",
			"type": "project",
			"content": "这条只用于验证成功回执不带 error_kind。",
		},
	)
	assert res.is_error is False, res.content
	assert res.error_kind is None


@pytest.mark.asyncio
async def test_websearch_provider_failure_is_classified(reg):
	"""全网关失败（超时/被墙）要记成环境侧，不能留在"没分类"里。

	可达性口径（不假装）：WebSearch 经 policy 是 `outbound_ask`，无应答者时根本进不到工具体
    （下面第二条断言把这道闸钉住）；桌面 GUI 上用户会放行，所以这一路**会**被走到。
	这里用静态断言钉标签：不联网、不造第二条通路，也不靠 monkeypatch 假装失败。
	"""
	import ast
	from pathlib import Path as _P

	from permissions.policy import PermissionDecision, evaluate_policy

	src = (
		_P(__file__).resolve().parents[1] / "tools/web_search_tool/web_search_tool.py"
	).read_text(encoding="utf-8-sig")
	found = []
	for node in ast.walk(ast.parse(src)):
		if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("ToolResult"):
			kws = {k.arg: ast.unparse(k.value) for k in node.keywords}
			if kws.get("is_error") == "True" and "search provider failed" in kws.get("content", ""):
				found.append(kws.get("error_kind"))
	assert found == ["TRANSIENT_INFRA"], f"网关失败回执的分类被改丢：{found}"

	d = evaluate_policy("WebSearch", {"query": "x"}, cwd=str(_P.cwd()))
	assert d.decision == PermissionDecision.ASK and d.matched_rule == "outbound_ask", (
		f"WebSearch 的外发审批闸形变了：{d.decision}/{d.matched_rule}"
	)


# ── 文件/搜索工具家族的补账（2026-10-05 摘账）────────────────────────────
# Grep/Glob/Read/Edit 在 10-03 普查时文件在途、整族未补；落地后按同一口径补齐。


@pytest.mark.asyncio
@pytest.mark.parametrize(
	"tool,payload,needle",
	[
		("Grep", {}, "pattern is required"),
		("Grep", {"pattern": "x", "output_mode": "bogus"}, "invalid output_mode"),
		("Grep", {"pattern": "x", "offset": -1}, "offset must be >= 0"),
		("Grep", {"pattern": "x", "head_limit": "abc"}, "invalid head_limit"),
		("Glob", {"pattern": "   "}, "pattern is required"),
		("Glob", {"pattern": "*.py", "offset": ["x"]}, "invalid offset"),
		("Read", {}, "file_path is required"),
		("Read", {"file_path": "x.py", "offset": -5}, "offset must be >= 0"),
		("Read", {"file_path": "x.py", "limit": 0}, "limit must be a positive integer"),
		("Read", {"file_path": "x.py", "limit": "abc"}, "invalid limit"),
		("Edit", {}, "file_path is required"),
	],
)
async def test_file_tool_argument_rejections_are_classified(reg, tool, payload, needle):
	res = await _run(reg, tool, payload)
	assert res.is_error is True, res.content
	assert needle in res.content, res.content
	assert res.error_kind == INVALID_ARGUMENT, (
		f"{tool} 的参数拒绝被兜成 {res.error_kind}，诊断层只能记成「没分类」"
	)


@pytest.mark.asyncio
async def test_grep_bad_regex_is_invalid_argument(reg):
	"""rg 退出码 2（正则解析失败）是模型写的 pattern 有错，不是"没分类"。"""
	res = await _run(reg, "Grep", {"pattern": "(?:forward = [", "path": "."})
	assert res.is_error is True, res.content
	assert "regex parse error" in res.content.lower(), res.content
	assert res.error_kind == INVALID_ARGUMENT, res.error_kind


@pytest.mark.asyncio
async def test_grep_timeout_is_timeout_kind(reg, monkeypatch):
	"""rg 超时是环境侧：只替换抛错点，kind 判定仍走真实 execute 包装。"""
	import tools.grep_tool.grep_tool as gt

	def _boom(*a, **k):
		raise RuntimeError(
			"Ripgrep search timed out after 1 seconds. The search may have matched "
			"files but did not complete in time."
		)

	monkeypatch.setattr(gt, "run_ripgrep", _boom)
	res = await _run(reg, "Grep", {"pattern": "x", "path": "."})
	assert res.is_error is True, res.content
	assert res.error_kind == TIMEOUT, res.error_kind


@pytest.mark.asyncio
async def test_glob_timeout_is_timeout_kind(reg, monkeypatch):
	import tools.glob_tool.glob_tool as gt

	def _boom(*a, **k):
		raise gt.RipgrepRunnerError("Glob search timed out after 30 seconds.")

	monkeypatch.setattr(gt, "run_ripgrep_lines", _boom)
	res = await _run(reg, "Glob", {"pattern": "*.py", "path": "."})
	assert res.is_error is True, res.content
	assert res.error_kind == TIMEOUT, res.error_kind


@pytest.mark.asyncio
async def test_read_directory_target_is_invalid_argument(reg):
	"""Read 指到目录：稳定事实、模型侧可自纠 ⇒ INVALID_ARGUMENT。"""
	res = await _run(reg, "Read", {"file_path": "."})
	assert res.is_error is True, res.content
	assert "is a directory" in res.content, res.content
	assert res.error_kind == INVALID_ARGUMENT, res.error_kind


@pytest.mark.asyncio
@pytest.mark.parametrize(
	"tool,payload,needle",
	[
		("Grep", {"pattern": "x", "path": "no_such_dir_xyz"}, "Path does not exist"),
		(
			"Glob",
			{"pattern": "*.py", "path": "no_such_dir_xyz"},
			"Directory does not exist",
		),
		("Read", {"file_path": "no_such_file_xyz.py"}, "File does not exist"),
	],
)
async def test_missing_targets_stay_honestly_unclassified(reg, tool, payload, needle):
	"""模型给的目标不存在：故意 INTERNAL。

	NOT_FOUND 在 fault_split 里算环境侧，而"路径不存在"可能因用户在会话中
	删改文件（不可归属），把它统一判给环境是新的假话 —— 与上面
	`test_missing_note_stays_honestly_unclassified` 同一判决。
	"""
	res = await _run(reg, tool, payload)
	assert res.is_error is True, res.content
	assert needle in res.content, res.content
	assert res.error_kind == INTERNAL, res.error_kind
