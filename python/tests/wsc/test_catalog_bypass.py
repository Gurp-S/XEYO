"""有界可分页目录（`memory/wsc_catalog.py`，旁路候选）的契约测试。

钉的是裁定原文那句判据：**每一步可执行、可继续定位**。
所以第 4、5 两条一律走**真 `FileReadTool`**，不用模拟闸门——本轮的结论正是
"照抄现网入口会抛错"，再拿自己写的闸门当裁判就等于没测（同一个坑踩过一次）。
"""

from __future__ import annotations

import asyncio
import math
import re

import pytest

pytest.importorskip("synaptic")

from memory.wsc_catalog import (  # noqa: E402
	CatalogError,
	Block,
	Entry,
	MAX_LINES,
	MAX_TOKENS,
	PAGE_ENTRIES,
	PAGE_MAX_CHARS,
	build_catalog,
	parse_catalog,
	plan_steps,
	render_entry,
)
from tests.wsc._recovery_contract import _deannotate  # noqa: E402

#: 页尾指针里**唯一**声明下一次读法的地方；测试照它的字面形态解析。
_NEXT_READ = re.compile(r"^#next Read\(file_path='(?P<path>[^']*)',\s*offset=(?P<off>\d+),\s*limit=(?P<lim>\d+)\)$")


def _node(idx: int, *, rows: int = 3, bulk: int = 0) -> str:
	lines = [f"a{idx}.py output:"] + [f"l{idx}-{k}" for k in range(rows)]
	if bulk:
		lines.append("z" * bulk)
	return "\n".join(lines)


def _archive_lines(nodes: dict[int, str]) -> list[str]:
	"""按 `write_text_view` 的行号约定造归档：``#node`` 头**不在**正文区间内。"""
	out: list[str] = []
	for idx, body in nodes.items():
		out.append(f"#node {idx}")
		out.extend(body.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
	return out


def _blocks(lines: list[str], nodes: dict[int, str]) -> tuple[list[Block], dict[str, tuple[int, int]]]:
	"""从归档逐行反推每个节点的正文跨度（``#node`` 头不在区间内）。"""
	blocks: list[Block] = []
	spans: dict[str, tuple[int, int]] = {}
	label_at = 0
	idx = ""
	for i, ln in enumerate(lines):
		if ln.startswith("#node "):
			if label_at:
				start = label_at + 1
				end = i                      # 下一个标签前的最后一行
				handle = f"node://{idx}"
				blocks.append(Block(handle=handle, start=start, end=end))
				spans[handle] = (start, end)
			idx = ln[len("#node "):].strip()
			label_at = i + 1
	if label_at:
		start = label_at + 1
		end = len(lines)
		handle = f"node://{idx}"
		blocks.append(Block(handle=handle, start=start, end=end))
		spans[handle] = (start, end)
	assert len(blocks) == len(nodes), "夹具坏了：块数与节点数不符"
	return blocks, spans


@pytest.fixture()
def real_tool():
	from engine.abort import AbortController
	from tools.file_read_tool.file_read_tool import FileReadTool

	def read(path: str, offset: int, limit: int, *, cwd: str) -> str:
		tool = FileReadTool(cwd=cwd)
		res = asyncio.run(tool.execute({"file_path": path, "offset": offset, "limit": limit},
		                               AbortController()))
		if getattr(res, "is_error", False):
			raise RuntimeError(str(getattr(res, "content", res)))
		return str(res.content)

	return read


def test_catalog_caps_are_the_production_read_caps() -> None:
	"""两道上限改值即红：目录的有界性完全建立在它们之上。"""
	from tools.file_read_tool.file_read_tool import DEFAULT_MAX_TOKENS
	from tools.file_read_tool.prompt import MAX_LINES_TO_READ

	assert MAX_TOKENS == DEFAULT_MAX_TOKENS
	assert MAX_LINES == MAX_LINES_TO_READ


def test_plan_steps_stays_inside_both_caps_and_reassembles_verbatim() -> None:
	nodes = {1: _node(1, rows=30_000)}
	lines = _archive_lines(nodes)
	blocks, spans = _blocks(lines, nodes)
	start, end = spans["node://1"]
	steps, unreadable = plan_steps(lines, start, end)
	assert steps and not unreadable, "探针为空：没算出步就不许说它在上限内"
	assert all(lim <= MAX_LINES for _off, lim in steps)
	assert all(max(1, len("\n".join(lines[off - 1:off - 1 + lim])) // 4) <= MAX_TOKENS for off, lim in steps)
	joined = "\n".join("\n".join(lines[off - 1:off - 1 + lim]) for off, lim in steps)
	assert joined == "\n".join(lines[start - 1:end])
	assert steps[0][0] == start and steps[-1][0] + steps[-1][1] - 1 == end


def test_single_line_over_cap_is_declared_unreadable_not_declared_readable() -> None:
	nodes = {1: _node(1, bulk=200_000), 2: _node(2)}
	lines = _archive_lines(nodes)
	blocks, spans = _blocks(lines, nodes)
	start, end = spans["node://1"]
	steps, unreadable = plan_steps(lines, end, end)      # end 那一行是 20 万字符的整行
	assert unreadable and not steps
	text = render_entry(Entry(handle="node://1", start=start, end=end, steps=(), unreadable=True))
	assert "unreadable=single-line-over-read-cap" in text
	assert "read(offset=" not in text          # 绝不声明一条执行不了的读


def test_every_declared_step_executes_in_the_real_tool(tmp_path, real_tool) -> None:
	"""合同 (a) 的目录版：**照抄声明即成功**。含一个必须分页的大块。"""
	nodes = {
		1: _node(1),
		2: _node(2, rows=9_000),          # 跨行数与 token 两道上限 ⇒ 必须拆成多步
		3: _node(3, rows=5),
		4: _node(4, bulk=200_000),        # 单行越上限 ⇒ 如实标不可取回
	}
	lines = _archive_lines(nodes)
	archive = tmp_path / "archive.txt"
	archive.write_text("\n".join(lines) + "\n", encoding="utf-8")
	blocks, spans = _blocks(lines, nodes)
	cat = build_catalog(str(archive), blocks, lines=lines, catalog_path=str(tmp_path / "catalog.txt"))
	parsed = parse_catalog((tmp_path / "catalog.txt").read_text(encoding="utf-8"))
	entries = parsed["entries"]
	assert entries, "探针为空：目录里一条都没有"
	assert len(entries) == len(blocks) == cat.entry_count

	unreadable_handles = set()
	for e in entries:
		if e["unreadable"]:
			unreadable_handles.add(e["handle"])
			continue
		start, end = e["span"]
		chunks = []
		for off, lim in e["steps"]:
			got = real_tool(str(archive), off, lim, cwd=str(tmp_path))   # 抛错即红
			chunks.append(_deannotate(got))
		body = "\n".join(chunks)
		assert body == "\n".join(lines[start - 1:end]), f"{e['handle']} 逐次读回拼不出原文"
		# 可继续定位：条目声明的跨度第一行就是 #node 标签的下一行，标签里点着节点号
		assert lines[start - 2] == f"#node {e['handle'].split('//')[1]}"
	assert unreadable_handles == {"node://4"}


def test_page_chain_walks_with_the_real_tool(tmp_path, real_tool) -> None:
	"""卡面只给第一页；沿页尾指针能走完整本目录，每一页都读得动。"""
	nodes = {i: _node(i, rows=4) for i in range(1, 301)}     # 300 条 ⇒ 多页
	lines = _archive_lines(nodes)
	archive = tmp_path / "archive.txt"
	archive.write_text("\n".join(lines) + "\n", encoding="utf-8")
	blocks, _spans = _blocks(lines, nodes)
	cat_path = str(tmp_path / "catalog.txt")
	cat = build_catalog(str(archive), blocks, lines=lines, catalog_path=cat_path)
	assert len(cat.pages) == math.ceil(len(blocks) / PAGE_ENTRIES)

	off, lim = cat.pages[0].offset, cat.pages[0].limit
	assert cat.head_ref == f"Read(file_path='{cat_path}', offset={off}, limit={lim})"
	seen: list[str] = []
	paths: set[str] = set()
	for _guard in range(len(cat.pages) + 2):
		page_text = _deannotate(real_tool(cat_path, off, lim, cwd=str(tmp_path)))
		seen.append(page_text)
		nxt = [ln for ln in page_text.split("\n") if ln.startswith("#next ")]
		if not nxt:
			break
		m = _NEXT_READ.search(nxt[0])
		assert m, f"页尾指针不可解析: {nxt[0][:60]}"
		paths.add(m["path"])
		off, lim = int(m["off"]), int(m["lim"])
	else:
		pytest.fail("页尾指针走不到头：目录不可分页")
	assert paths == {cat_path}                      # 翻页只需要指针自身，不靠记住目录在哪
	joined = "\n".join(seen)
	assert len([ln for ln in joined.split("\n") if ln.startswith("node://")]) == len(blocks)
	# 入口只有一个 ≠ 一次读全部档案：卡面那行的跨度只覆盖第一页
	assert lim <= PAGE_ENTRIES + 2


def test_archive_path_is_declared_once(tmp_path) -> None:
	nodes = {i: _node(i) for i in range(1, 6)}
	lines = _archive_lines(nodes)
	archive = tmp_path / "archive.txt"
	archive.write_text("\n".join(lines) + "\n", encoding="utf-8")
	blocks, _ = _blocks(lines, nodes)
	build_catalog(str(archive), blocks, lines=lines, catalog_path=str(tmp_path / "catalog.txt"))
	text = (tmp_path / "catalog.txt").read_text(encoding="utf-8")
	assert text.count("file_path=") == text.count("#archive file_path=") + text.count("#next Read(file_path='")
	for ln in text.split("\n"):
		if ln.startswith("node://"):
			assert "file_path=" not in ln


def test_appending_blocks_never_moves_earlier_addresses(tmp_path) -> None:
	"""冷层是追加式的：新块只能加在末尾，旧目录项与页地址必须逐字不动。

	这条是现网最坏的一类静默故障的回归门——旧引用指向别的内容（`ref_drift`）。
	"""
	nodes = {i: _node(i, rows=3) for i in range(1, 121)}
	lines = _archive_lines(nodes)
	archive = tmp_path / "archive.txt"
	archive.write_text("\n".join(lines) + "\n", encoding="utf-8")
	blocks, _ = _blocks(lines, nodes)
	cat_path = str(tmp_path / "catalog.txt")
	first = build_catalog(str(archive), blocks, lines=lines, catalog_path=cat_path)
	before = (tmp_path / "catalog.txt").read_text(encoding="utf-8").split("\n")[:-1]

	nodes.update({i: _node(i, rows=3) for i in range(121, 141)})
	lines2 = _archive_lines(nodes)
	assert lines2[:len(lines)] == lines, "夹具坏了：追加不该移动旧行"
	archive.write_text("\n".join(lines2) + "\n", encoding="utf-8")
	blocks2, _ = _blocks(lines2, nodes)
	second = build_catalog(str(archive), blocks2, lines=lines2, catalog_path=cat_path)
	after = (tmp_path / "catalog.txt").read_text(encoding="utf-8").split("\n")[:-1]

	assert second.head_ref == first.head_ref
	old_entries = [ln for ln in before if ln.startswith("node://")]
	new_entries = [ln for ln in after if ln.startswith("node://")]
	assert old_entries, "探针为空：旧目录里没有条目"
	assert new_entries[:len(old_entries)] == old_entries, "追加移动了旧条目的跨度或步长"
	old_pages = [ln for ln in before if ln.startswith("#page ")]
	new_pages = [ln for ln in after if ln.startswith("#page ")]
	assert new_pages[:len(old_pages)] == old_pages, "追加移动了旧页的地址"
	assert second.entry_count == len(blocks2) > first.entry_count


def test_pages_are_char_bounded_and_every_page_readables(tmp_path) -> None:
	nodes = {i: _node(i, rows=6) for i in range(1, 1001)}
	lines = _archive_lines(nodes)
	archive = tmp_path / "archive.txt"
	archive.write_text("\n".join(lines) + "\n", encoding="utf-8")
	blocks, _ = _blocks(lines, nodes)
	cat_path = str(tmp_path / "catalog.txt")
	cat = build_catalog(str(archive), blocks, lines=lines, catalog_path=cat_path)
	raw = (tmp_path / "catalog.txt").read_text(encoding="utf-8").split("\n")
	parsed = parse_catalog("\n".join(raw))
	assert len(parsed["pages"]) == cat.entry_count // PAGE_ENTRIES and cat.entry_count == 1000
	for p in cat.pages:
		body = "\n".join(raw[p.offset - 1:p.offset + p.limit - 1])
		assert len(body) <= PAGE_MAX_CHARS, f"页 {p.index} 越字符预算"
		assert max(1, len(body) // 4) <= MAX_TOKENS


def test_malformed_block_spans_are_refused(tmp_path) -> None:
	nodes = {1: _node(1)}
	lines = _archive_lines(nodes)
	for bad in (Block("node://1", start=0, end=3), Block("node://1", start=5, end=4)):
		with pytest.raises(CatalogError):
			build_catalog("archive.txt", [bad], lines=lines, catalog_path=str(tmp_path / "c.txt"))


def test_empty_index_is_refused_instead_of_writing_a_hollow_catalog(tmp_path) -> None:
	with pytest.raises(CatalogError):
		build_catalog("archive.txt", [], lines=["#node 1"], catalog_path=str(tmp_path / "c.txt"))
