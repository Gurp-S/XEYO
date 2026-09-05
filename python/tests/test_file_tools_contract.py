"""核心文件工具合同：成功 / 错误 / abort / 越权。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from engine.abort import AbortController
from msgtypes.message import ToolUse
from permissions.filesystem import PermissionDecision
from permissions.policy import evaluate_policy
from tools.catalog import build_default_registry
from tools.file_edit_tool.file_edit_tool import FileEditTool
from tools.file_read_tool.file_read_tool import FileReadTool
from tools.file_write_tool.file_write_tool import FileWriteTool
from tools.fileio.read_state import FileStateEntry, ReadFileState
from tools.glob_tool.glob_tool import GlobTool
from tools.grep_tool.grep_tool import GrepTool


@pytest.fixture
def work(tmp_path: Path) -> Path:
	(tmp_path / "src").mkdir()
	(tmp_path / "src" / "a.py").write_text("hello_marker = 1\n", encoding="utf-8")
	(tmp_path / "src" / "b.txt").write_text("bbb\n", encoding="utf-8")
	return tmp_path


@pytest.mark.asyncio
async def test_read_success_and_missing(work: Path) -> None:
	tool = FileReadTool(cwd=str(work))
	ok = await tool.execute(
		{"file_path": str(work / "src" / "a.py")}, AbortController()
	)
	assert not ok.is_error
	assert "hello_marker" in ok.content

	missing = await tool.execute(
		{"file_path": str(work / "nope.py")}, AbortController()
	)
	assert missing.is_error


@pytest.mark.asyncio
async def test_read_rejects_image_and_outside(work: Path) -> None:
	tool = FileReadTool(cwd=str(work))
	img = work / "pic.png"
	img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 20)
	bad = await tool.execute({"file_path": str(img)}, AbortController())
	assert bad.is_error
	assert "text-only" in bad.content.lower() or "image" in bad.content.lower()

	outside = work.parent / "secret.txt"
	outside.write_text("secret", encoding="utf-8")
	# 工具内权限：工作区外应拒绝
	denied = await tool.execute({"file_path": str(outside)}, AbortController())
	assert denied.is_error


@pytest.mark.asyncio
async def test_read_aborts_before_execute(work: Path) -> None:
	tool = FileReadTool(cwd=str(work))
	abort = AbortController()
	abort.abort()
	with pytest.raises(Exception):
		await tool.execute(
			{"file_path": str(work / "src" / "a.py")}, abort
		)


@pytest.mark.asyncio
async def test_grep_success_empty_and_abort(work: Path) -> None:
	tool = GrepTool(cwd=str(work))
	hit = await tool.execute(
		{"pattern": "hello_marker", "path": str(work / "src")},
		AbortController(),
	)
	assert not hit.is_error
	assert "a.py" in hit.content or "hello_marker" in hit.content

	miss = await tool.execute(
		{"pattern": "zzz_no_match_xxx", "path": str(work / "src")},
		AbortController(),
	)
	assert not miss.is_error

	abort = AbortController()
	abort.abort()
	with pytest.raises(Exception):
		await tool.execute({"pattern": "x", "path": str(work)}, abort)


@pytest.mark.asyncio
async def test_glob_success_and_outside(work: Path) -> None:
	tool = GlobTool(cwd=str(work))
	ok = await tool.execute({"pattern": "**/*.py"}, AbortController())
	assert not ok.is_error
	assert "a.py" in ok.content

	outside = str(work.parent)
	# policy 层：path 在工作区外应 deny/ask
	dec = evaluate_policy(
		"Glob", {"pattern": "**/*", "path": outside}, cwd=str(work)
	)
	assert dec.decision in (PermissionDecision.DENY, PermissionDecision.ASK)


@pytest.mark.asyncio
async def test_write_edit_success_error_abort(work: Path) -> None:
	state = ReadFileState()
	reader = FileReadTool(cwd=str(work))
	reader.set_read_file_state(state)
	writer = FileWriteTool(cwd=str(work))
	writer.set_read_file_state(state)
	editor = FileEditTool(cwd=str(work))
	editor.set_read_file_state(state)

	target = work / "src" / "a.py"
	# 先读再写
	await reader.execute({"file_path": str(target)}, AbortController())
	w = await writer.execute(
		{"file_path": str(target), "content": "hello_marker = 2\n"},
		AbortController(),
	)
	assert not w.is_error
	assert target.read_text(encoding="utf-8") == "hello_marker = 2\n"

	await reader.execute({"file_path": str(target)}, AbortController())
	e = await editor.execute(
		{
			"file_path": str(target),
			"old_string": "hello_marker = 2",
			"new_string": "hello_marker = 3",
		},
		AbortController(),
	)
	assert not e.is_error
	assert "hello_marker = 3" in target.read_text(encoding="utf-8")

	# 未读先写应失败
	fresh = FileWriteTool(cwd=str(work))
	fresh.set_read_file_state(ReadFileState())
	bad = await fresh.execute(
		{"file_path": str(work / "src" / "b.txt"), "content": "x"},
		AbortController(),
	)
	assert bad.is_error

	abort = AbortController()
	abort.abort()
	with pytest.raises(Exception):
		await writer.execute(
			{"file_path": str(target), "content": "x"}, abort
		)


@pytest.mark.asyncio
async def test_registry_denies_write_outside(work: Path) -> None:
	reg = build_default_registry(cwd=str(work))
	outside = str(work.parent / "out.txt")
	result = await reg.run(
		ToolUse(
			id="1",
			name="Write",
			input={"file_path": outside, "content": "x"},
		),
		AbortController(),
		skip_ask=True,
	)
	assert result.is_error


@pytest.mark.asyncio
async def test_write_edit_execute_denies_outside(work: Path) -> None:
	"""工具内 check_permissions：区外路径直接 permission denied（不依赖 registry）。"""
	state = ReadFileState()
	outside = work.parent / "outside_write.txt"
	outside.write_text("hello\n", encoding="utf-8")
	# 先登记 read_state，让 validate 过关，从而打到 check_permissions
	from tools.fileio.read_state import FileStateEntry
	from tools.fileio.text import get_mtime_ms

	full = str(outside.resolve())
	state.set(
		full,
		FileStateEntry(
			content="hello\n",
			timestamp=get_mtime_ms(full),
			offset=None,
			limit=None,
		),
	)

	writer = FileWriteTool(cwd=str(work))
	writer.set_read_file_state(state)
	w = await writer.execute(
		{"file_path": str(outside), "content": "x"},
		AbortController(),
	)
	assert w.is_error
	assert "permission" in w.content.lower()

	editor = FileEditTool(cwd=str(work))
	editor.set_read_file_state(state)
	e = await editor.execute(
		{
			"file_path": str(outside),
			"old_string": "hello",
			"new_string": "bye",
		},
		AbortController(),
	)
	assert e.is_error
	assert "permission" in e.content.lower()


@pytest.mark.asyncio
async def test_write_denies_dotdot_escape(work: Path) -> None:
	"""相对 .. 逃出工作区根时，工具内写拒绝。"""
	state = ReadFileState()
	writer = FileWriteTool(cwd=str(work / "src"))
	writer.set_read_file_state(state)
	# work/src/../../outside → work 的父目录
	escaped = str(work.parent / "escaped.txt")
	# 用相对路径形式：从 src 出发 ../../escaped.txt
	rel = os.path.join("..", "..", "escaped.txt")
	denied = await writer.execute(
		{"file_path": rel, "content": "nope"},
		AbortController(),
	)
	assert denied.is_error
	assert "permission" in denied.content.lower()
	assert not Path(escaped).exists() or Path(escaped).read_text(encoding="utf-8") != "nope"


@pytest.mark.asyncio
async def test_edit_after_sidecar_restore_does_not_false_positive(work: Path) -> None:
	"""engine 重建后 read_state 只有 mtime 没有正文（load_meta）：即使 mtime
	前进了也不得误报 modified-since-read——由 old_string 匹配兜底。"""
	target = work / "src" / "a.py"
	edit = FileEditTool(cwd=str(work))
	# 模拟 sidecar 恢复：条目存在、正文未知（content=""），且 mtime 已前进。
	edit._read_state.set(
		str(target),
		FileStateEntry(
			content="",
			timestamp=1,  # 远古 mtime → 任何现存文件都"更新"
			offset=None,
			limit=None,
			is_partial_view=False,
			content_known=False,
		),
	)
	result = await edit.execute(
		{
			"file_path": str(target),
			"old_string": "hello_marker = 1",
			"new_string": "hello_marker = 2",
		},
		AbortController(),
	)
	assert "modified since read" not in str(result.content)


def test_read_state_lru_env_override(monkeypatch) -> None:
	monkeypatch.setenv("XEYO_READ_STATE_MAX_ENTRIES", "16")
	state = ReadFileState()
	for i in range(20):
		state.set(f"f{i}.txt", FileStateEntry(content="x", timestamp=i))
	assert len(state._entries) == 16
	# 最旧的被淘汰，最新的保留
	assert state.get("f0.txt") is None
	assert state.get("f19.txt") is not None


@pytest.mark.asyncio
async def test_edit_validation_cache_not_leaked_across_calls(work: Path) -> None:
	"""_last_* 校验缓存不得跨调用泄漏：call 失败后残留内容可能被下一次
	「向空文件创建」分支读到，把上一个文件的内容写进当前文件。"""
	src_a = work / "src" / "a.py"
	src_b = work / "src" / "leak_target.txt"
	src_b.write_text("", encoding="utf-8")
	shared = ReadFileState()
	reader = FileReadTool(cwd=str(work), read_state=shared)
	edit = FileEditTool(cwd=str(work), read_state=shared)

	# 先 Read 两个文件（空文件也登记 read_state，允许后续"创建内容"）
	r1 = await reader.execute({"file_path": str(src_a)}, AbortController())
	r2 = await reader.execute({"file_path": str(src_b)}, AbortController())
	assert not r1.is_error and not r2.is_error

	# 第一次：对 a.py 的合法 Edit —— validate 成功后在实例上留下 a.py 的内容
	result = await edit.execute(
		{
			"file_path": str(src_a),
			"old_string": "hello_marker = 1",
			"new_string": "hello_marker = 2",
		},
		AbortController(),
	)
	assert not result.is_error

	# 第二次：向空文件写入内容（old_string="" 走提前放行分支）
	result = await edit.execute(
		{
			"file_path": str(src_b),
			"old_string": "",
			"new_string": "fresh content",
		},
		AbortController(),
	)
	assert not result.is_error, result.content
	# 关键断言：b.txt 里只能是 fresh content，不得混入 a.py 的旧内容
	assert src_b.read_text(encoding="utf-8") == "fresh content"


@pytest.mark.asyncio
async def test_edit_failed_call_does_not_poison_next_new_file(work: Path) -> None:
	"""call 抛错（write 冲突等）后 _last_* 残留：下一次新建文件必须干净。"""
	src_a = work / "src" / "a.py"
	src_b = work / "src" / "poison_target.txt"
	edit = FileEditTool(cwd=str(work))

	# 第一次：validate 通过但 call 失败 —— 用 read_state 时间戳伪造冲突：
	# 先成功 validate（execute 内部），再让落盘抛错。这里用只读目录模拟
	# _persist 失败：把 b 的父目录改成不可写不现实，改为直接注入 _last_*
	# 模拟「上一次校验残留」——execute 路径上 validate 会重置缓存，
	# 所以等价验证是：手工塞入残留属性后走新建文件分支。
	edit._last_file_content = "POISON_FROM_A"
	edit._last_actual_old = "hello_marker = 1"
	edit_b_new = work / "src" / "poison_target2.txt"
	edit_b_new.write_text("", encoding="utf-8")
	result = await edit.execute(
		{
			"file_path": str(edit_b_new),
			"old_string": "",
			"new_string": "clean content",
		},
		AbortController(),
	)
	assert not result.is_error, result.content
	assert edit_b_new.read_text(encoding="utf-8") == "clean content"
	_ = src_a
	_ = src_b
