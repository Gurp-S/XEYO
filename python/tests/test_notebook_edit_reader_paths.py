"""NotebookEdit 的两处磁盘读必须走共用 reader（`read_text_file`），不能自己 `open()`。

缺陷（2026-10-03 实测复现并修复）：`notebook_edit_tool.execute()` 里
新鲜度比对与 JSON 解析两处都用 `open(full, encoding="utf-8").read()`，而同一文件的
`_persist()` 早就用 `read_text_file` 算 base hash ⇒ 同一工具两套读法，reader 的
三件事（剥 BOM / 容错解码 / 容器路由）在读取侧一件都没拿到。后果逐条实测：

1. 非 UTF-8 字节的 `.ipynb`（模型只要把路径给成二进制文件就会命中）：
   `except OSError` 抓不到 `UnicodeDecodeError`（它是 ValueError 的子类，不是 OSError）
   ⇒ 异常**逃出 `execute()`**，穿过 `ToolRegistry.run()`（那里只记审计然后 re-raise）
   ⇒ 一次工具调用打断整个回合，而不是回一条中性错误。
2. 带 UTF-8 BOM 的 notebook：`json.loads("\ufeff{...}")` 直接
   `invalid notebook JSON: Unexpected UTF-8 BOM` ⇒ 这个工具对 BOM notebook 完全失明
   （与代码索引那批 BOM 失明同族）。
3. 同一 BOM 文件在 `mtime` 前移后（git checkout / 编辑器重新保存，内容一字未改）：
   台账里的正文是 reader 剥过 BOM 的，磁盘原文带着 `\ufeff` ⇒ 比对必然不等
   ⇒ 假报 "Notebook modified since Read"，把明明没被改的文件永久拒掉。

反向门槛同样钉在这里：新鲜度校验不许因为这次改动而失效（真被改过必须仍判 stale）。
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

from msgtypes.message import ToolUse
from tools.file_read_tool.file_read_tool import FileReadTool
from tools.fileio.read_state import ReadFileState
from tools.fileio.text import read_text_file
from tools.notebook_edit_tool.notebook_edit_tool import NotebookEditTool
from tools.tool_registry import ToolRegistry

NB = {
	"cells": [
		{
			"cell_type": "code",
			"source": ["print(1)\n"],
			"metadata": {},
			"outputs": [],
			"execution_count": None,
		}
	],
	"metadata": {},
	"nbformat": 4,
	"nbformat_minor": 5,
}
GOOD = json.dumps(NB, indent=1)


class _Abort:
	def raise_if_aborted(self) -> None:
		return None

	def is_aborted(self) -> bool:
		return False


def _touch(path: Path, ms: int = 5000) -> None:
	"""只动 mtime，内容一字不改（git checkout / 另存为的真实形状）。"""
	st = path.stat()
	os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + ms * 1_000_000))


def _edit(tmp: Path, name: str, state: ReadFileState | None = None) -> object:
	tool = NotebookEditTool(cwd=str(tmp), read_state=state or ReadFileState())
	return tool.execute(
		{
			"notebook_path": str(tmp / name),
			"edit_mode": "replace",
			"cell_idx": 0,
			"new_source": "print(2)",
		},
		_Abort(),
	)


async def test_non_utf8_notebook_returns_error_instead_of_raising(tmp_path: Path) -> None:
	(tmp_path / "a.ipynb").write_bytes(b"\xff\x41\x42\x43 not utf-8")
	res = await _edit(tmp_path, "a.ipynb")  # type: ignore[call-arg]
	assert res.is_error is True
	assert res.content


async def test_non_utf8_notebook_does_not_escape_registry_run(tmp_path: Path) -> None:
	"""判据落在消费点上：`ToolRegistry.run()` 只做审计后 re-raise，所以异常必须死在工具里。"""
	bad = tmp_path / "a.ipynb"
	bad.write_bytes(b"\xff\x41\x42\x43 not utf-8")
	reg = ToolRegistry(cwd=str(tmp_path))
	reg.register(NotebookEditTool(cwd=str(tmp_path)))
	use = ToolUse(
		id="tu_1",
		name="NotebookEdit",
		input={
			"notebook_path": str(bad),
			"edit_mode": "replace",
			"cell_idx": 0,
			"new_source": "print(2)",
		},
	)
	res = await reg.run(use, _Abort(), skip_ask=True)  # 异常逃逸会在这里炸
	assert res.is_error is True


async def test_bom_notebook_is_editable(tmp_path: Path) -> None:
	(tmp_path / "b.ipynb").write_bytes(GOOD.encode("utf-8-sig"))
	res = await _edit(tmp_path, "b.ipynb")  # type: ignore[call-arg]
	assert res.is_error is False, f"BOM notebook 被当成非法 JSON：{res.content[:120]!r}"
	assert "Unexpected UTF-8 BOM" not in res.content
	# 写回仍是合法 notebook JSON
	assert json.loads(read_text_file(str(tmp_path / "b.ipynb"))[0])["cells"][0]["source"] == ["print(2)"]


async def test_bom_notebook_after_touch_is_not_falsely_stale(tmp_path: Path) -> None:
	path = tmp_path / "e.ipynb"
	path.write_bytes(GOOD.encode("utf-8-sig"))
	state = ReadFileState()
	read = await FileReadTool(cwd=str(tmp_path), read_state=state).execute(
		{"file_path": str(path)}, _Abort()
	)
	assert read.is_error is False
	entry = state.get(os.path.abspath(str(path)))
	assert entry is not None and entry.content, "read_state 未命中 ⇒ 本用例根本没走到新鲜度分支"
	_touch(path)
	# 前置：旧读法（裸 open）与台账必然不等——这条不等就是被修掉的假阳性
	assert open(path, encoding="utf-8").read() != entry.content
	res = await _edit(tmp_path, "e.ipynb", state)  # type: ignore[call-arg]
	assert res.is_error is False, f"内容一字未改却被判 stale：{res.content[:160]!r}"
	assert "modified since Read" not in res.content


async def test_truncated_utf16_notebook_is_contained(tmp_path: Path) -> None:
	"""共用 reader 的 utf-16-le 分支自己会抛 UnicodeDecodeError ⇒ 证明 except 子句不是装饰。"""
	path = tmp_path / "c.ipynb"
	path.write_bytes(b"\xff\xfeA")
	with pytest.raises(UnicodeDecodeError):
		read_text_file(str(path))
	res = await _edit(tmp_path, "c.ipynb")  # type: ignore[call-arg]
	assert res.is_error is True


async def test_genuine_modification_is_still_rejected(tmp_path: Path) -> None:
	"""反向对照：修读取口径不许把新鲜度门一起关掉。"""
	path = tmp_path / "f.ipynb"
	path.write_bytes(GOOD.encode("utf-8"))
	state = ReadFileState()
	await FileReadTool(cwd=str(tmp_path), read_state=state).execute(
		{"file_path": str(path)}, _Abort()
	)
	assert state.get(os.path.abspath(str(path))) is not None
	# 真的有人改了内容（另一个 cell 被替换），再动 mtime
	path.write_bytes(json.dumps({**NB, "cells": []}, indent=1).encode("utf-8"))
	_touch(path, ms=100)
	res = await _edit(tmp_path, "f.ipynb", state)  # type: ignore[call-arg]
	assert res.is_error is True
	assert "modified since Read" in res.content


def test_no_bare_open_read_bypasses_the_shared_reader() -> None:
	"""结构门：工具层不许出现 `open(...).read()` 这种绕过共用 reader 的文本读。

	`read_text_file` 是 Read/Edit/Write/NotebookEdit 的汇聚点（剥 BOM、容错解码、
	容器路由都在里面）；任何就地 `open()` 读全文都会静默丢掉这三件事——本次缺陷就是它。
	长期流式句柄（如后台任务日志）不在此列：那条不读正文。
	"""
	root = Path(__file__).resolve().parents[1]
	offenders: list[str] = []
	scanned = 0
	for py in sorted((root / "tools").rglob("*.py")):
		if "__pycache__" in py.parts:
			continue
		scanned += 1
		tree = ast.parse(py.read_text(encoding="utf-8-sig"))
		for node in ast.walk(tree):
			if not isinstance(node, ast.Call):
				continue
			base = node.func
			if isinstance(base, ast.Attribute) and base.attr in ("read", "readlines"):
				inner = base.value
				if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) and inner.func.id == "open":
					offenders.append(f"{py.relative_to(root)}:{node.lineno}")
	assert scanned > 50, f"扫描文件数异常（{scanned}）⇒ 门的作用域没生效"
	assert not offenders, "绕过共用 reader 的文本读：" + ", ".join(offenders)
