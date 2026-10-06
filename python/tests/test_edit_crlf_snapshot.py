"""Edit 的正文必须落在 LF 归一空间：快照/落盘/哈希三处同口径。

缺陷（2026-10-03 实测复现并修复）：`file_edit_tool.call()` 主分支把
`apply_edit_to_file` 的结果**原样**交给 `_persist` 与 `read_state.set_written`。
模型的 `new_string` 里带 `\r\n`（Windows 上整段粘贴代码很常见）时：

1. store 路径（子 agent / 有写域）不做归一，`\r\n` 原样写进 LF 文件 ⇒ **混合行尾**；
   直通路径 `write_text_file` 会归一 ⇒ 同一枪 Edit 在主 agent 与子 agent 下写出不同字节。
2. 快照带上 `\r\n`，而 `write_store._content_hash` 读盘算的是 `read_text_file` 的**归一**文本；
   `_persist` 又用 `entry.content` 算 `base_hashes` ⇒ `base != current` ⇒
   **没有任何人改过文件**也被判 `stale`（"File has been unexpectedly modified"），
   此后该文件每一枪 Edit 都被拒，并往 journal 记 `stale_reject`、给写冲突指标计数。
   只有重新 Read 才能自愈——模型看到的是"我改不了这个文件"。

同函数的新建分支与 `file_write_tool` 的两处快照本来就归一 ⇒ 四个写点里只有主分支漏了。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.write_store import WriteStore, _content_hash, _content_hash_text
from tools.file_edit_tool.file_edit_tool import EditInput, FileEditTool
from tools.fileio.read_state import ReadFileState
from tools.fileio.text import get_mtime_ms, read_text_file

ORIG = "alpha\nbeta\ngamma\n"


class _CountingStore(WriteStore):
	"""见证用：记录 submit_sync 被调了几次——门必须确认这一枪真走了 store 路径。"""

	def __init__(self, root) -> None:
		super().__init__(root)
		self.calls = 0

	def submit_sync(self, intent):  # type: ignore[override]
		self.calls += 1
		return super().submit_sync(intent)


@pytest.fixture()
def tmp(tmp_path, monkeypatch):
	import memory.journal as j

	monkeypatch.setattr(j, "_changes_path", lambda ws: tmp_path / f"{ws}.jsonl")
	return tmp_path


def _tool(ws: Path, *, store: WriteStore | None):
	rs = ReadFileState()
	tool = FileEditTool(cwd=str(ws), read_state=rs)
	if store is not None:
		tool.set_write_store(store)
		tool.set_agent_id("sub-1")
	return tool, rs


def _seed(rs: ReadFileState, path: Path, text: str) -> None:
	rs.set_written(str(path), text, get_mtime_ms(str(path)), "s1", offset=None, limit=None)


def _edit(tool: FileEditTool, path: Path, old: str, new: str):
	inp = EditInput(file_path=str(path), old_string=old, new_string=new)
	verdict = tool.validate_input(inp)
	assert verdict.get("result") is True, f"validate 意外拒绝：{verdict}"
	return tool.call(inp)


def test_crlf_new_string_does_not_poison_next_edit(tmp):
	"""复现本缺陷：store 路径一次 CRLF 粘贴后，第二枪必须仍然被接受。"""
	store = _CountingStore(tmp)
	tool, rs = _tool(tmp, store=store)
	path = tmp / "body.txt"
	path.write_bytes(ORIG.encode("utf-8"))
	_seed(rs, path, ORIG)

	_edit(tool, path, "alpha", "x\r\ny")
	assert store.calls == 1, "这一枪没走 store ⇒ 下面所有断言都测不到 store 的哈希口径"

	disk_bytes = path.read_bytes()
	assert b"\r" not in disk_bytes, f"LF 文件里被写入混合行尾：{disk_bytes!r}"

	entry = rs.get(str(path))
	assert entry is not None
	assert "\r\n" not in entry.content, f"快照未归一：{entry.content!r}"
	assert _content_hash_text(entry.content) == _content_hash(path), (
		"快照哈希与 write_store 的磁盘哈希不同口径 ⇒ 下一枪必被判 stale"
	)

	# 关键判据：与第一枪完全无关的位置、期间无人改动文件。
	out = _edit(tool, path, "beta", "z")
	assert store.calls == 2
	assert "z" in path.read_text(encoding="utf-8")
	assert out is not None


def test_store_route_and_direct_route_write_identical_bytes(tmp):
	"""同一枪 Edit 在子 agent（store）与主 agent（直通）下必须落成同一份字节。"""
	path_a = tmp / "a.txt"
	path_b = tmp / "b.txt"
	for p in (path_a, path_b):
		p.write_bytes(ORIG.encode("utf-8"))

	store = _CountingStore(tmp)
	tool_store, rs_store = _tool(tmp, store=store)
	tool_direct, rs_direct = _tool(tmp, store=None)
	_seed(rs_store, path_a, ORIG)
	_seed(rs_direct, path_b, ORIG)

	_edit(tool_store, path_a, "alpha", "x\r\ny")
	_edit(tool_direct, path_b, "alpha", "x\r\ny")

	assert path_a.read_bytes() == path_b.read_bytes(), (
		"store 路径与直通路径归一口径不一致：同一枪 Edit 产出两种字节"
	)
	assert rs_store.get(str(path_a)).content == rs_direct.get(str(path_b)).content


def test_crlf_file_stays_crlf_after_edit(tmp):
	"""反向对照：归一只作用于内存正文，真 CRLF 文件落盘必须仍是纯 CRLF。"""
	store = _CountingStore(tmp)
	tool, rs = _tool(tmp, store=store)
	path = tmp / "win.ps1"
	crlf = "alpha\r\nbeta\r\ngamma\r\n"
	path.write_bytes(crlf.encode("utf-8"))
	_seed(rs, path, "alpha\nbeta\ngamma\n")

	_edit(tool, path, "beta", "B\r\nETA")

	raw = path.read_bytes()
	assert b"\n" not in raw.replace(b"\r\n", b""), f"CRLF 文件被掺进裸 LF：{raw!r}"
	# 快照仍须与归一化磁盘文本同口径（新鲜度判定比的是 read_text_file）。
	text, endings, _enc = read_text_file(str(path))
	assert endings == "CRLF"
	assert rs.get(str(path)).content == text


def test_create_branch_snapshot_matches_disk_with_lone_cr(tmp):
	"""新建分支：孤立 \\r 也要和磁盘一致（write_text_file 会把孤立 \\r 折成 \\n）。"""
	store = _CountingStore(tmp)
	tool, rs = _tool(tmp, store=store)
	path = tmp / "fresh.txt"

	_edit(tool, path, "", "one\rtwo\n")

	assert store.calls == 1, "新建也须走 store，否则这条门只测到直通分支"
	assert path.read_bytes() == b"one\ntwo\n"
	assert rs.get(str(path)).content == "one\ntwo\n"
	assert _content_hash_text(rs.get(str(path)).content) == _content_hash(path)


def test_crlf_old_string_matches_lf_file(tmp):
	"""old_string 带 \\r\\n 对 LF 文件必须命中（2026-10-05 前报 not found）。

	旧实现等价于「原串 in 正文」或「弯引号归一后再 in」两步——两查都 miss。
	"""
	from tools.fileio.text import find_actual_string

	content = "alpha\nbeta\ngamma\n"
	assert find_actual_string(content, "alpha\r\nbeta") == "alpha\nbeta"
	# 弯引号 + CRLF 同批命中（归一必须在同一条链上）
	curly = "say \u2018hi\u2019\nnext\n"
	assert find_actual_string(curly, "say 'hi'\r\nnext") == "say \u2018hi\u2019\nnext"
	# 方向控制：真正不存在的串仍返回 None
	assert find_actual_string(content, "nope\r\nnope") is None


def test_crlf_old_string_edit_end_to_end(tmp):
	"""端到端：校验层的归一 actual 与替换同空间，文件被正确改写且快照同口径。"""
	store = _CountingStore(tmp)
	tool, rs = _tool(tmp, store=store)
	path = tmp / "e2e.txt"
	path.write_bytes(b"A\nB\nC\n")
	_seed(rs, path, "A\nB\nC\n")

	_edit(tool, path, "A\r\nB", "A\nZ")

	text = path.read_text(encoding="utf-8")
	assert text == "A\nZ\nC\n", text
	assert rs.get(str(path)).content == "A\nZ\nC\n"
