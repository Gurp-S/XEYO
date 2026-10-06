"""有界、可分页的**冷层目录**（旁路候选，未接入生产）。

要解决的实测问题（``docs/synaptic-compression.md`` 十七.13）：热层里声明的取回入口
55.6% 按声明参数执行会抛错，剩下能执行的那部分中位要放大 783 倍才能拿回正文。
原因是 ``ColdStore.write_text_view`` 产出的取回视图是一份几万行的文件，
而句柄卡面只给 ``Read(offset=S, limit=E-S+1)``——整组句柄的跨度经常超过
`FileReadTool` 的两道硬上限（2000 行 / 25000 token），超限直接抛错而非截断。

本模块把「一个入口指向全部档案」换成「一个入口指向第一页目录」：

- **有界**：一页最多 ``PAGE_ENTRIES`` 条、``PAGE_MAX_CHARS`` 字符，写出前逐页校验，
  保证任何一页都能被一次 ``Read`` 读完而不抛错；
- **可分页**：页末一行给出下一页的完整 ``Read(...)``，逐字可执行；
- **每一步可定位**：每条目录项写明该块的完整跨度 ``span=S-E``，并**逐步枚举**
  ``read(offset=,limit=)`` 与 ``next(offset=,limit=)``，每一步都在两道上限之内
  ⇒ 取回正文不靠一次越界的大读，也不要求读者自己猜步长；
- **路径声明一次**：归档文件路径只在头部 ``#archive`` 行出现一次，条目只写
  ``offset=/limit=`` ⇒ 卡面不再为每行重复同一条长路径。

判据是「每一步可执行、可继续定位」，不是入口数量（顾问裁定原文）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: 与 `FileReadTool` 同值的两道上限。值复制一份是为了不让报表/测试为了两个常数
#: 把整个工具模块拖进导入链；`tests/wsc/test_catalog_bypass.py` 有一条门把这两个
#: 常数与真工具里的定义钉死相等，工具改值即红。
MAX_TOKENS = 25_000
MAX_LINES = 2000

#: 一页的有界预算：条数与字符数双上限。16k 字符 ≈ 4k token，离 25k 上限一个数量级。
PAGE_ENTRIES = 40
PAGE_MAX_CHARS = 16_000

#: `Read` 的粗估口径：`_rough_token_estimate = max(1, len(content) // 4)`（字符，非字节）。
TOKEN_DIVISOR = 4

_VERSION = 1

_HEADER_TOP = re.compile(r"^#catalog v(?P<v>\d+) entries=(?P<n>\d+) pages=(?P<p>\d+) unreadable=(?P<u>\d+)$")
_HEADER_ARCHIVE = re.compile(r"^#archive file_path=(?P<path>.+)$")
_PAGE_LABEL = re.compile(r"^#page (?P<idx>\d+) lines (?P<start>\d+)-(?P<end>\d+)$")
_PAGE_NEXT = re.compile(r"^#next Read\(file_path='(?P<path>[^']*)', offset=(?P<off>\d+), limit=(?P<lim>\d+)\)$")
_ENTRY = re.compile(
	r"^(?P<handle>\S+) span=(?P<start>\d+)-(?P<end>\d+)"
	r"(?: unreadable=single-line-over-read-cap"
	r"|(?P<rest>(?: read\(offset=\d+,limit=\d+\)| next\(offset=\d+,limit=\d+\))+))$"
)
_STEP = re.compile(r"(?P<kind>read|next)\(offset=(?P<off>\d+),limit=(?P<lim>\d+)\)")


class CatalogError(RuntimeError):
	"""构造出的目录不满足有界性（宁可不写，也不写一份声明了却执行不了的入口）。"""


@dataclass(frozen=True)
class Block:
	"""归档视图里一个可取回块：``start``/``end`` 是**正文行**跨度（1 起，含端点）。"""

	handle: str
	start: int
	end: int


@dataclass(frozen=True)
class Entry:
	handle: str
	start: int
	end: int
	steps: tuple[tuple[int, int], ...]   # (offset, limit)，每步都在两道上限内
	unreadable: bool                    # 单行就越 token 上限 ⇒ 该块不经 Read 取回


def _tokens(s: str) -> int:
	return max(1, len(s) // TOKEN_DIVISOR) if s else 0


def plan_steps(lines: list[str], start: int, end: int,
	           *, max_lines: int = MAX_LINES, max_tokens: int = MAX_TOKENS
	           ) -> tuple[tuple[tuple[int, int], ...], bool]:
	"""把 ``[start, end]`` 拆成若干次可执行读取。

	每步先被行数上限裁，再按真实行长度累加裁到 token 上限。若某一行单独就越 token
	上限，该步无法存在 ⇒ 返回 ``((), True)``：目录如实标出「此块经 ``Read`` 不可取回」，
	而不是声明一条会抛错的读。
	"""
	steps: list[tuple[int, int]] = []
	cur = start
	while cur <= end:
		room = min(max_lines, end - cur + 1)
		n = 0
		chars = 0
		while n < room:
			i = cur - 1 + n
			line = lines[i] if i < len(lines) else ""
			# 拼接后的长度 = 各行字符数之和 + (n-1) 个换行；用 +n 保守高估一个字符。
			if (chars + len(line) + 1) // TOKEN_DIVISOR > max_tokens:
				break
			chars += len(line) + 1
			n += 1
		if n == 0:
			return (), True
		steps.append((cur, n))
		cur += n
	return tuple(steps), False


def render_entry(e: Entry) -> str:
	if e.unreadable:
		return f"{e.handle} span={e.start}-{e.end} unreadable=single-line-over-read-cap"
	if not e.steps:
		raise CatalogError(f"entry without steps: {e.handle}")
	head = e.steps[0]
	out = f"{e.handle} span={e.start}-{e.end} read(offset={head[0]},limit={head[1]})"
	for off, lim in e.steps[1:]:
		out += f" next(offset={off},limit={lim})"
	if len(out) > PAGE_MAX_CHARS:
		raise CatalogError(f"entry over page budget: {e.handle} ({len(out)} chars)")
	return out


@dataclass(frozen=True)
class Page:
	index: int
	offset: int          # 目录文件里本页首行行号（1 起，即页标签那行）
	limit: int           # 本页行数（含页标签与页尾指针）
	next_read: str       # 下一页的完整可执行 Read(...)；末页为空串


@dataclass(frozen=True)
class Catalog:
	catalog_path: str
	archive_path: str
	pages: tuple[Page, ...]
	entry_count: int
	unreadable_count: int

	@property
	def page_reads(self) -> tuple[tuple[int, int], ...]:
		"""从第一页出发、按页尾指针能走完整本目录的读取链。"""
		return tuple((p.offset, p.limit) for p in self.pages)

	#: 进卡面的那一行：只声明「第一页怎么读」，不给全部档案。
	@property
	def head_ref(self) -> str:
		p = self.pages[0]
		return f"Read(file_path='{self.catalog_path}', offset={p.offset}, limit={p.limit})"


def _paginate(lines: list[str], *, page_entries: int, page_max_chars: int) -> list[list[str]]:
	pages: list[list[str]] = []
	cur: list[str] = []
	size = 0
	for line in lines:
		w = len(line) + 1
		if cur and (len(cur) >= page_entries or size + w > page_max_chars):
			pages.append(cur)
			cur, size = [], 0
		cur.append(line)
		size += w
		if len(line) > page_max_chars:
			raise CatalogError(f"single entry over page budget: {len(line)} chars")
	if cur:
		pages.append(cur)
	return pages


def build_catalog(archive_path: str, blocks: list[Block], *,
	              lines: list[str], catalog_path: str,
	              page_entries: int = PAGE_ENTRIES,
	              page_max_chars: int = PAGE_MAX_CHARS) -> Catalog:
	"""把 ``blocks`` 写成目录文件，返回页表。``lines`` 是归档文件的逐行内容。

	落盘只覆盖 ``catalog_path`` 一个文件；不读写冷层之外的状态。
	"""
	if not blocks:
		raise CatalogError("no blocks to index")
	rendered: list[str] = []
	unreadable = 0
	for b in blocks:
		if b.start < 1 or b.end < b.start:
			raise CatalogError(f"bad block span: {b.handle} {b.start}-{b.end}")
		steps, bad = plan_steps(lines, b.start, b.end)
		unreadable += int(bad)
		rendered.append(render_entry(Entry(handle=b.handle, start=b.start, end=b.end,
		                                  steps=steps, unreadable=bad)))
	chunks = _paginate(rendered, page_entries=page_entries, page_max_chars=page_max_chars)

	# 页标签与页尾指针会各占一行、也要进字符预算；先按结构定稿行号，再回填。
	out: list[str] = [
		f"#catalog v{_VERSION} entries={len(rendered)} pages={len(chunks)} unreadable={unreadable}",
		f"#archive file_path={archive_path}",
	]
	pages: list[Page] = []
	for idx, chunk in enumerate(chunks):
		label_at = len(out) + 1
		out.append(f"#page {idx + 1} lines {label_at}-{label_at + len(chunk) + 1}")
		out.extend(chunk)
		out.append("#next pending")
		pages.append(Page(index=idx + 1, offset=label_at, limit=len(chunk) + 2, next_read=""))
	for i, p in enumerate(pages):
		nxt = pages[i + 1] if i + 1 < len(pages) else None
		tail_at = p.offset + p.limit - 1          # 1 起的行号 ⇒ 写回时要 -1
		out[tail_at - 1] = ("#end" if nxt is None else
		                    f"#next Read(file_path='{catalog_path}', offset={nxt.offset}, limit={nxt.limit})")
		pages[i] = Page(index=p.index, offset=p.offset, limit=p.limit, next_read=out[tail_at - 1])

	text = "\n".join(out) + "\n"
	for p in pages:
		body = out[p.offset - 1:p.offset + p.limit - 1]
		if len("\n".join(body)) > page_max_chars:
			raise CatalogError(f"page {p.index} over char budget: {len(body[0])}")
	with open(catalog_path, "w", encoding="utf-8", newline="\n") as fh:
		fh.write(text)
	return Catalog(catalog_path=str(catalog_path), archive_path=str(archive_path),
	               pages=tuple(pages), entry_count=len(rendered), unreadable_count=unreadable)


def parse_catalog(text: str) -> dict[str, object]:
	"""把目录文本解析回结构（审计与测试用；不读盘，便于对字符串直接判）。"""
	lines = text.split("\n")
	top = _HEADER_TOP.match(lines[0] if lines else "")
	arch = _HEADER_ARCHIVE.match(lines[1] if len(lines) > 1 else "")
	if not top or not arch:
		raise CatalogError("catalog header missing or malformed")
	pages: list[dict[str, object]] = []
	entries: list[dict[str, object]] = []
	next_by_page: dict[int, str] = {}
	for ln in lines[2:]:
		if not ln or ln == "#end":
			continue
		m = _PAGE_LABEL.match(ln)
		if m:
			pages.append({"index": int(m["idx"]), "offset": int(m["start"]),
			              "limit": int(m["end"]) - int(m["start"]) + 1})
			continue
		m = _PAGE_NEXT.match(ln)
		if m:
			next_by_page[len(pages)] = ln[len("#next "):]
			continue
		m = _ENTRY.match(ln)
		if not m:
			raise CatalogError(f"unparsable catalog line: {ln[:60]}")
		entries.append({
			"handle": m["handle"],
			"span": (int(m["start"]), int(m["end"])),
			"steps": [(int(s["off"]), int(s["lim"])) for s in _STEP.finditer(m["rest"] or "")],
			"unreadable": m["rest"] is None,
			"page": pages[-1]["index"] if pages else 0,
		})
	return {
		"version": int(top["v"]), "archive_path": arch["path"],
		"entries_declared": int(top["n"]), "pages_declared": int(top["p"]),
		"unreadable_declared": int(top["u"]),
		"pages": pages, "next_by_page": next_by_page, "entries": entries,
	}
