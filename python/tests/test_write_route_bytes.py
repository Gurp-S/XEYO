"""Write 的 store 路径与直通路径必须落成同一份字节。

`file_write_tool.call()` 用 `normalized = normalize_newlines(content)` 去做快照、
行数统计、语法自检与工具结果，却把**原始** `content` 交给 `_persist`。
直通路径 `write_text_file` 自己会归一，所以主 agent 看不出问题；
store 路径（子 Agent / 有写域）里 `_persist` 的 LF 分支是 `content_out = content`
原样透传 ⇒ 同一枪 Write 在两种 agent 下落成不同字节：

- 模型的 Windows 脚本带 `\r\n` ⇒ 子 agent 写出**混合行尾**的文件，
  而 `detect_line_endings` 是"只要有一个 CRLF 就整文件算 CRLF"⇒ 下一次 Read 起，
  该文件的每一枪 Edit 都会把全文改写成 CRLF（用户看到的整片红 diff）。
- 孤立 `\r`（write_text_file 会折成 `\n`）在 store 路径原样留在盘上。

`_persist` 自己的注释声明"与直通路径 write_text_file 等价"——这条等价声明此前不成立。
"""

from __future__ import annotations

import pytest

from engine.write_store import WriteStore, _content_hash, _content_hash_text
from tools.file_write_tool.file_write_tool import FileWriteTool, WriteInput
from tools.fileio.read_state import ReadFileState


@pytest.fixture()
def ws(tmp_path, monkeypatch):
	import memory.journal as j

	monkeypatch.setattr(j, "_changes_path", lambda w: tmp_path / f"{w}.jsonl")
	return tmp_path


def _tool(root, *, store: WriteStore | None):
	tool = FileWriteTool(cwd=str(root), read_state=ReadFileState())
	if store is not None:
		tool.set_write_store(store)
		tool.set_agent_id("sub-1")
	return tool


def test_crlf_content_yields_identical_bytes_on_both_routes(ws):
	path_a = ws / "via_store.ps1"
	path_b = ws / "via_direct.ps1"
	body = "Write-Host 'a'\r\nWrite-Host 'b'\r\n"

	_tool(ws, store=WriteStore(ws)).call(WriteInput(file_path=str(path_a), content=body))
	_tool(ws, store=None).call(WriteInput(file_path=str(path_b), content=body))

	assert path_a.read_bytes() == path_b.read_bytes(), (
		"同一枪 Write 在主 agent（直通）与子 agent（store）下落成不同字节："
		f"store={path_a.read_bytes()!r} direct={path_b.read_bytes()!r}"
	)


def test_lone_cr_does_not_survive_on_store_route(ws):
	path = ws / "lone_cr.txt"
	_tool(ws, store=WriteStore(ws)).call(
		WriteInput(file_path=str(path), content="one\rtwo\n")
	)
	assert path.read_bytes() == b"one\ntwo\n", f"孤立 \\r 漏在盘上：{path.read_bytes()!r}"


def test_snapshot_hash_space_still_matches_disk(ws):
	"""归一之后仍要守住"快照哈希==磁盘哈希"，否则修完行尾又踩回 stale 那一坑。"""
	tool = _tool(ws, store=WriteStore(ws))
	path = ws / "hash_space.txt"
	tool.call(WriteInput(file_path=str(path), content="a\r\nb\n"))
	entry = tool._read_state.get(str(path))
	assert entry is not None
	assert "\r" not in entry.content
	assert _content_hash_text(entry.content) == _content_hash(path)


def test_pure_lf_content_unchanged_on_both_routes(ws):
	"""反向对照：本来就干净的 LF 正文，两条路径都不许多改什么东西。"""
	path_a = ws / "lf_store.txt"
	path_b = ws / "lf_direct.txt"
	body = "alpha\nbeta\ngamma\n"

	_tool(ws, store=WriteStore(ws)).call(WriteInput(file_path=str(path_a), content=body))
	_tool(ws, store=None).call(WriteInput(file_path=str(path_b), content=body))

	assert path_a.read_bytes() == body.encode("utf-8")
	assert path_b.read_bytes() == body.encode("utf-8")
