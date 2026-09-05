"""Read symbol 参数用例（33号计划 Step 2）。

覆盖：符号体截取、歧义引导、未命中引导、与 offset/limit 互斥、
绕过 unchanged-stub 去重、metadata 附带。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.abort import AbortController
from tools.file_read_tool.file_read_tool import FileReadTool
from tools.fileio.read_state import FileStateEntry, ReadFileState


PY_SRC = (
	"import os\n"
	"from pathlib import Path\n"
	"\n"
	"\n"
	"class Store:\n"
	"	def apply(self, x):\n"
	"		\"\"\"Apply increment.\"\"\"\n"
	"		Path('.').exists()\n"
	"		return helper(x) + 1\n"
	"\n"
	"	def other(self):\n"
	"		return self.apply(2)\n"
	"\n"
	"\n"
	"def helper(x):\n"
	"	return x * 2\n"
	"\n"
	"\n"
	"def apply(x):\n"
	"	return x * 2\n"
)


@pytest.fixture
def work(tmp_path: Path) -> Path:
	f = tmp_path / "mod.py"
	f.write_text(PY_SRC, encoding="utf-8")
	return tmp_path


@pytest.mark.asyncio
async def test_read_symbol_returns_only_body(work: Path) -> None:
	tool = FileReadTool(cwd=str(work))
	r = await tool.execute(
		{"file_path": str(work / "mod.py"), "symbol": "Store.apply"},
		AbortController(),
	)
	assert not r.is_error
	lines = r.content.strip().split("\n")
	assert any("return helper(x) + 1" in ln for ln in lines)
	assert all("def helper" not in ln for ln in lines)
	assert r.metadata and r.metadata["read_kind"] == "symbol"
	assert r.metadata["symbol"] == "apply"
	assert r.metadata["range"] == [6, 9]


@pytest.mark.asyncio
async def test_read_symbol_ambiguous_guides_to_qualified_path(work: Path) -> None:
	tool = FileReadTool(cwd=str(work))
	r = await tool.execute(
		{"file_path": str(work / "mod.py"), "symbol": "apply"},
		AbortController(),
	)
	assert r.is_error
	assert "ambiguous" in r.content
	# 候选列表里两个 apply 都在，引导模型用限定路径
	assert "Store.apply" in r.content or "(in Store)" in r.content


@pytest.mark.asyncio
async def test_read_symbol_not_found_guides_to_grep(work: Path) -> None:
	tool = FileReadTool(cwd=str(work))
	r = await tool.execute(
		{"file_path": str(work / "mod.py"), "symbol": "NoSuch.thing"},
		AbortController(),
	)
	assert r.is_error
	assert "output_mode" in r.content and "symbols" in r.content


@pytest.mark.asyncio
async def test_read_symbol_conflicts_with_offset_limit(work: Path) -> None:
	tool = FileReadTool(cwd=str(work))
	r = await tool.execute(
		{"file_path": str(work / "mod.py"), "symbol": "Store.apply", "offset": 1},
		AbortController(),
	)
	assert r.is_error
	assert "cannot be combined" in r.content


@pytest.mark.asyncio
async def test_read_symbol_bypasses_unchanged_stub(work: Path) -> None:
	# 先做过一次同路径全文件读取，read_state 里留有记录
	tool = FileReadTool(cwd=str(work))
	full = str(work / "mod.py")
	first = await tool.execute({"file_path": full}, AbortController())
	assert not first.is_error
	# 手工放一条 offset=1/limit=None 的记录模拟"刚读过全文件"
	tool._read_state.set(
		full,
		FileStateEntry(content=PY_SRC, timestamp=9_999_999, offset=1, limit=None),
	)
	r = await tool.execute(
		{"file_path": full, "symbol": "Store.other"},
		AbortController(),
	)
	# 若未绕过去重，这里会返回 file_unchanged stub
	assert not r.is_error
	assert "FILE_UNCHANGED" not in r.content
	assert "self.apply(2)" in r.content


@pytest.mark.asyncio
async def test_read_symbol_rejects_image(work: Path) -> None:
	img = work / "pic.png"
	img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 20)
	tool = FileReadTool(cwd=str(work))
	r = await tool.execute(
		{"file_path": str(img), "symbol": "Whatever"}, AbortController()
	)
	assert r.is_error
	# 图片在 text-only 校验前段即被拒绝（文案可能是 text-only 或 symbol 专属提示），
	# 关键是不进入 vision 分支、不返回成功
	assert "Read is text-only" in r.content or "text source files" in r.content


@pytest.mark.asyncio
async def test_read_pack_includes_context(work: Path) -> None:
	tool = FileReadTool(cwd=str(work))
	r = await tool.execute(
		{"file_path": str(work / "mod.py"), "symbol": "Store.apply", "pack": True},
		AbortController(),
	)
	assert not r.is_error
	assert r.metadata and r.metadata["read_kind"] == "symbol_pack"
	assert "Apply increment" in r.content
	assert "helper" in r.content
	assert "## body" in r.content or "pack" in r.content.lower()
	# 被调方签名存在
	assert "helper" in r.content
	# 近似被调方：其他调用同样适用
	assert "other" in r.content or "callers" in r.content


@pytest.mark.asyncio
async def test_read_pack_requires_symbol(work: Path) -> None:
	tool = FileReadTool(cwd=str(work))
	r = await tool.execute(
		{"file_path": str(work / "mod.py"), "pack": True},
		AbortController(),
	)
	assert r.is_error
	assert "pack requires symbol" in r.content
