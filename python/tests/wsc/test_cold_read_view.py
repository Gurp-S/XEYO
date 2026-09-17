"""冷层取回视图 ↔ `Read` 的往返契约（2026-09-16 用户裁定）。

## 契约（三份产物、三条契约，别混）

| 产物 | 契约 | 谁来测 |
|---|---|---|
| `ColdStore.write()` 的 gzip+JSON 权威副本 | **逐字节**等于历史原文 | `test_authoritative_copy_keeps_crlf_byte_exact` |
| `write_text_view()` 的纯文本视图 | **逐字节**等于原文的 LF 归一化形态 | `test_text_view_roundtrip_is_byte_exact` |
| 模型经 `Read` 取回 | **内容无损**，但每行带 ``cat -n`` 前缀 | `test_read_retrieval_is_content_exact_after_stripping_line_numbers` |

第三条为什么不能写成「逐字节」：`Read` 给模型的内容一律过
`tools/fileio/text.py::add_line_numbers`（`     1→` 形态），那是**工具的既有语义**。
行号是**寻址元数据**、不是内容丢失 ⇒ 机械地把前缀剥掉后必须逐字节相等（本文件就这么测）。

## 口径同源纪律

切片口径**不自己另写**：视图侧按 `Read` 的 `offset`(1 起) / `limit`(行数) 语义产出区间，
测试直接用**真的 `FileReadTool`** 取回。这样「测试里的切片」与「工具里的切片」不可能漂移。
"""

from __future__ import annotations

import asyncio
import re

import pytest

from synaptic.coldstore import ColdStore, node_handle
from tools.file_read_tool.file_read_tool import FileReadTool

#: 刻意挑边界：无尾换行 / 有尾换行 / 多行 / 空文本 / CRLF / 只有换行 / 超长单行。
_TRICKY = {
	1: "单行无尾换行",
	2: "两行\n第二行",
	3: "有尾换行\n",
	4: "",
	5: "CRLF 结尾\r\n第二行\r\n",
	6: "\n",
	7: "\n\n\n",
	8: "x" * 5000 + "\n尾部",
	9: "前后都有\n\n空行\n\n",
}

#: `add_line_numbers` 的前缀形态：右对齐 6 宽 + `→`（`tools/fileio/text.py:129-141`）。
_LINENO_PREFIX = re.compile(r"^\s*\d+→")


def _lf(text: str) -> str:
	"""视图契约口径：LF 归一化（`Path.read_text` 的通用换行归一化是工具既有语义）。"""
	return text.replace("\r\n", "\n").replace("\r", "\n")


def _strip_line_numbers(visible: str) -> str:
	"""剥掉 `cat -n` 前缀，还原内容行。"""
	return "\n".join(_LINENO_PREFIX.sub("", ln) for ln in visible.split("\n"))


def _store() -> ColdStore:
	cs = ColdStore(session="t")
	cs.put_nodes([(i, t, {"kind": "text"}) for i, t in _TRICKY.items()])
	for i in _TRICKY:
		cs.bind(node_handle(i), (i,))
	return cs


def _read(tool: FileReadTool, path, *, offset: int, limit: int) -> str:
	res = asyncio.run(
		tool.execute({"file_path": str(path), "offset": offset, "limit": limit}, _abort())
	)
	assert not res.is_error, res.content
	return res.content


def _abort():
	from engine.abort import AbortController

	return AbortController()


@pytest.fixture()
def view(tmp_path):
	"""视图落在 `tmp_path`（= 测试工作区，`Read` 的权限狱据此判定在区内）。"""
	cs = _store()
	path = tmp_path / ".xeyo_offload" / "cold.txt"
	ranges = cs.write_text_view(path)
	return cs, path, ranges


# ---------------------------------------------------------------------------
# 权威副本 / 视图：逐字节
# ---------------------------------------------------------------------------

def test_authoritative_copy_keeps_crlf_byte_exact(tmp_path):
	cs = _store()
	path = tmp_path / "cold.json.gz"
	cs.write(path)
	back = ColdStore.read(path)
	for idx, original in _TRICKY.items():
		assert back.expand(node_handle(idx)) == (original,), f"{idx} 权威副本丢字节"


def test_text_view_roundtrip_is_byte_exact(view):
	_cs, path, ranges = view
	raw = path.read_text(encoding="utf-8")
	for idx, original in _TRICKY.items():
		start, end = ranges[node_handle(idx)]
		got = "\n".join(raw.split("\n")[start - 1 : end])
		assert got == _lf(original), f"{node_handle(idx)} 视图往返不等：{got!r} != {_lf(original)!r}"


# ---------------------------------------------------------------------------
# 模型取回：经真实 FileReadTool（内容无损；行号是寻址前缀）
# ---------------------------------------------------------------------------

def test_read_retrieval_is_content_exact_after_stripping_line_numbers(view, tmp_path):
	tool = FileReadTool(cwd=str(tmp_path))
	_cs, path, ranges = view
	for idx, original in _TRICKY.items():
		if original == "":
			continue  # 空节点的已知限制见下一条测试（Read 的空切片语义）
		start, end = ranges[node_handle(idx)]
		visible = _read(tool, path, offset=start, limit=end - start + 1)
		assert _strip_line_numbers(visible) == _lf(original), (
			f"{node_handle(idx)} 内容不等：{_strip_line_numbers(visible)!r} != {_lf(original)!r}"
		)


def test_empty_node_retrieval_hits_reads_eof_semantics(view, tmp_path):
	"""**已知限制（锁成事实，不是静默跳过）**：原文为空的节点取不回过「空串」。

	`Read` 把「切片为空」与「offset 越过文件尾」当成同一情况
	（`map_tool_result_to_result` 先判 `if output.content:`，空则回落 EOF 提示）⇒
	取回得到的是 ``<system-reminder>Warning: the file exists but is shorter than …``。

	为什么不为了绕过它去改视图内容（例如给空节点塞一行哨兵）：那会让**内容失真**，
	而这里本来就没有内容可丢（信息量为零）。限制如实记录，不粉饰。
	"""
	tool = FileReadTool(cwd=str(tmp_path))
	_cs, path, ranges = view
	assert _TRICKY[4] == ""
	start, end = ranges[node_handle(4)]
	visible = _read(tool, path, offset=start, limit=end - start + 1)
	assert "shorter than the provided offset" in visible, (
		f"空切片语义变了（若 Read 已能返回真正的空串，这条限制可以删掉）：{visible!r}"
	)


def test_read_visible_text_does_carry_line_numbers(view, tmp_path):
	"""反向断言（防断言空洞）：`Read` 的可见输出**确实**带行号前缀。

	如果哪天 `Read` 改成不加行号，上一条测试会**照样通过**（剥前缀成了空操作），
	但本条的意图会崩塌——所以要正着断言一次。
	"""
	tool = FileReadTool(cwd=str(tmp_path))
	_cs, path, ranges = view
	start, end = ranges[node_handle(1)]
	visible = _read(tool, path, offset=start, limit=end - start + 1)
	assert _LINENO_PREFIX.match(visible.split("\n")[0]), f"未见行号前缀：{visible!r}"


def test_externalized_read_does_not_pollute_read_state(view, tmp_path):
	"""**替换 offload_read 的关键副作用点**：读外部化内容不得写 read-state。

	`ReadFileState` 是 LRU 限幅的（`tools/fileio/read_state.py`），记进去会：
	① 挤掉正在编辑的真文件快照（写前新鲜度校验的依据）；
	② 让同一区间重复读返回 `FILE_UNCHANGED_STUB` 顶掉正文（取回语义要求每次给正文）。
	"""
	tool = FileReadTool(cwd=str(tmp_path))
	_cs, path, ranges = view

	# 先读一个「真文件」，建立对照。
	real = tmp_path / "src" / "a.py"
	real.parent.mkdir(parents=True, exist_ok=True)
	real.write_text("hello_marker = 1\n", encoding="utf-8")
	_read(tool, real, offset=1, limit=10)
	assert tool._read_state.get(str(real.resolve())) or tool._read_state.get(str(real)), (
		"真文件读后应当登记 read-state（否则本条测试的对照不成立）"
	)

	start, end = ranges[node_handle(2)]
	first = _read(tool, path, offset=start, limit=end - start + 1)
	second = _read(tool, path, offset=start, limit=end - start + 1)
	assert tool._read_state.get(str(path.resolve())) is None, "外部化内容不该进 read-state"
	assert first == second, "同一区间重复读必须每次给正文（不得被 FILE_UNCHANGED_STUB 顶掉）"


# ---------------------------------------------------------------------------
# 引用渲染
# ---------------------------------------------------------------------------

def test_handle_renders_to_a_callable_read_reference(view):
	cs, path, ranges = view
	ref = cs.read_ref(node_handle(2), ranges, path)
	assert ref.startswith("Read(file_path=")
	assert "offset=" in ref and "limit=" in ref
	# 与生产 offload 引用同源（模型只该认识一种取回形态）
	import os

	from memory.offload import maybe_offload

	os.environ["XEYO_TOOL_OFFLOAD"] = "1"
	os.environ["XEYO_OFFLOAD_DIR"] = str(path.parent)
	try:
		sample, written = maybe_offload("y" * 400, msg_idx=1, uid="u1")
	finally:
		os.environ.pop("XEYO_TOOL_OFFLOAD", None)
		os.environ.pop("XEYO_OFFLOAD_DIR", None)
	assert "Read(file_path=" in sample, f"生产 offload 引用形态不是 Read 口径：{sample}"
	assert "需细节时用工具" not in sample, "引用正文不得写成编排文本（引擎铁律：只出现信息）"
	assert written and written.endswith(".tool.txt")


def test_unknown_handle_renders_empty(view):
	cs, path, _ranges = view
	assert cs.read_ref(node_handle(999), {}, path) == ""


def test_externalized_path_predicate(tmp_path, monkeypatch):
	"""判定按 offload 根前缀；根之外一律 False（方向安全）。"""
	from memory.offload import is_externalized_path

	root = tmp_path / ".xeyo_offload"
	root.mkdir(parents=True, exist_ok=True)
	monkeypatch.setenv("XEYO_OFFLOAD_DIR", str(root))
	assert is_externalized_path(root / "a.tool.txt") is True
	assert is_externalized_path(str(root / "sub" / "b.txt")) is True
	assert is_externalized_path(tmp_path / "src" / "a.py") is False
	assert is_externalized_path("") is False
