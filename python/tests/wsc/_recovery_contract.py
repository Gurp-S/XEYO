"""恢复合同判定实现（旁路、只读；两份合同**分开**判，不许混成一个通过率）。

为什么需要这个文件：现有绿测 `test_handle_style.py::test_read_refs_retrieve_the_node_text_they_stand_for`
只判**单节点句柄**，多节点（组）句柄直接 `continue`。而生产实发头里 109/162 条引用是组句柄
（`synaptic/handles.py` 的 `span()` 对整组取 `min(start)/max(end)`）⇒ 现网最大的一类入口
从来没被裁决过。

两份合同（顾问裁定，逐字照实现）：

- **(a) 声明合同**：热层里声明为可执行 `Read(...)` 的引用，**按声明参数执行必须成功**。
- **(b) 恢复合同**：未完整保留在发射面里的原文，应能**从实际发射入口出发、经合法读取
  （含可发现的分页）完整恢复正文与来源身份**。

违反 (a) 不一定违反 (b)：入口一次读超 25k 抛错，但从它给的起点分页仍可能找到目标。
所以 (a)/(b) 各自成数，并且 **完整性(正确性) / 读取代价 / 重复程度 三项分开报**——
后两项是效率，不得并进通过率。

来源身份怎么判（实现里最容易搞错的一点）：`synaptic/coldstore.py::write_text_view`
**故意**把 ``#node <idx>`` 索引头留在区间之外（"纯粹给人/审计看"）⇒ 单节点区间返回的是
正确正文却不含标签。生产里身份由**承载该引用的那一行**声明（`files=…` / `对 X 失败`）。
所以身份成立 = 「切片里出现 ``#node <idx>``」**或**「引用所在行点名了该节点的来源」。

失败判据穷举（不是"只写我测得出的两种"）：`no_entry` 无入口覆盖 / `entry_exec_failed`
声明参数执行失败 / `wrong_node` 读到错误节点 / `body_missing` 归档里没有这块正文 /
`identity_error` 正文对得上但来源身份无法确立 / `ref_drift` 分页读回的块与声明区间不符。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

#: 三态分母（顾问裁定：消息 ID 集合不足以定分母——同一 ID 的正文可能已被截断或改成摘录）。
STATE_FULL = "full"          # 完整保留在发射面里 ⇒ 不需要出口
STATE_PARTIAL = "partial"    # 只保留了一部分 ⇒ 需要出口补全
STATE_ARCHIVED = "archived"  # 完全不在发射面 ⇒ 需要出口取回

#: 分页步长：取生产 `MAX_LINES_TO_READ`(2000) 之下，且远小于 25k token 闸门能容的行数。
PAGE_LINES = 200

#: 摘录探针粒度：与本仓库"关键信息针按前 80 字符判定"同源。
_PROBE = 80

_NODE_LABEL = re.compile(r"^#node (\d+)$")
_READ_REF = re.compile(r"Read\(file_path='(?P<path>[^']*)',\s*offset=(?P<off>\d+),\s*limit=(?P<lim>\d+)\)")


@dataclass(frozen=True)
class Entry:
	"""一条**从发射文本解析出来的**读取入口（带它所在那一行，用于判来源身份）。"""

	path: str
	offset: int
	limit: int
	line: str

	@property
	def end(self) -> int:
		return self.offset + self.limit - 1


def parse_read_refs(text: str) -> tuple[Entry, ...]:
	"""从发射文本解析声明出来的读取参数。

	只认发射文本：不读 `cold.handles`、不读进程内对象、不读投影器返回值——那三者都比
	"模型实际看见的东西"大，拿它们判等于自证。
	"""
	out: list[Entry] = []
	for line in text.splitlines():
		for m in _READ_REF.finditer(line):
			out.append(Entry(m.group("path"), int(m.group("off")), int(m.group("lim")), line))
	return tuple(out)


def archive_blocks(lines: Sequence[str]) -> dict[int, tuple[int, int]]:
	"""归档文件 → ``{节点号: (正文首行, 正文末行)}``，与 `write_text_view` 的行号约定同源。"""
	headers = [(i, int(m.group(1))) for i, line in enumerate(lines, 1) if (m := _NODE_LABEL.match(line))]
	out: dict[int, tuple[int, int]] = {}
	for pos, (row, idx) in enumerate(headers):
		end = (headers[pos + 1][0] - 1) if pos + 1 < len(headers) else len(lines)
		out[idx] = (row + 1, max(row + 1, end))
	return out


def _deannotate(text: str) -> str:
	"""剥掉投影注入：``<tool_output …>`` 包裹与 ``cat -n`` 行号前缀。

	不剥的话裸子串匹配会被转义与行号打断，把"其实已发出"误判成"仅归档"——本轮就踩过
	一次（分母虚高到 1,114）。
	"""
	text = re.sub(r"</?tool_output[^>]*>", "", text)
	return re.sub(r"(?m)^\s*\d+[→\-\t] ?", "", text)


def classify(nodes: Iterable[tuple[int, str]], emitted_text: str) -> dict[str, list[int]]:
	"""按三态给分母分类。``nodes`` = ``[(节点号, 归一化原文), ...]``。"""
	needle = _deannotate(emitted_text)
	buckets: dict[str, list[int]] = {STATE_FULL: [], STATE_PARTIAL: [], STATE_ARCHIVED: []}
	for idx, text in nodes:
		body = text.strip()
		if not body:
			continue
		if body in needle:
			buckets[STATE_FULL].append(idx)
			continue
		# 探针必须是**严格前缀**：取 `len//2` 与 80 的较小值。取整段的话，短节点只要
		# 没整段在场就永远判不成 partial（摘录本来就是"留一半"的形状）。
		probe = min(_PROBE, max(1, len(body) // 2))
		head = body[:probe]
		tail = body[-probe:] if len(body) > probe * 2 else ""
		buckets[STATE_PARTIAL if (head in needle or (tail and tail in needle)) else STATE_ARCHIVED].append(idx)
	return buckets


@dataclass
class NodeVerdict:
	idx: int
	#: ok / ok_via_pagination / no_entry / entry_exec_failed / wrong_node / body_missing / identity_error / ref_drift
	verdict: str
	contract_a_failed: bool
	contract_b_failed: bool
	pages_read: int
	tokens_read: int
	target_tokens: int


@dataclass
class ContractReport:
	verdicts: list[NodeVerdict] = field(default_factory=list)

	def axis_correctness(self) -> dict[str, int]:
		"""完整性（正确性）：两份合同各自成数，不合并成一个通过率。"""
		out: dict[str, int] = {"denominator": len(self.verdicts)}
		for v in self.verdicts:
			for key in (f"a_failed:{v.contract_a_failed}", f"b_failed:{v.contract_b_failed}",
			            f"verdict:{v.verdict}"):
				out[key] = out.get(key, 0) + 1
		return out

	def axis_read_cost(self) -> dict[str, float]:
		"""读取代价（效率）：为恢复目标实际读回多少。"""
		done = [v for v in self.verdicts if not v.contract_b_failed]
		if not done:
			return {"n": 0}
		ratios = sorted(v.tokens_read / max(1, v.target_tokens) for v in done)
		return {
			"n": len(done),
			"pages_median": _median([v.pages_read for v in done]),
			"tokens_read_median": _median([v.tokens_read for v in done]),
			"target_tokens_median": _median([v.target_tokens for v in done]),
			"amplification_median": _median(ratios),
			"amplification_p90": ratios[min(len(ratios) - 1, int(len(ratios) * 0.9))],
			"total_tokens_read": sum(v.tokens_read for v in done),
			"total_target_tokens": sum(v.target_tokens for v in done),
		}

	def axis_repetition(self, entries: Sequence[Entry]) -> dict[str, int]:
		"""重复程度（效率）：入口参数是否彼此重复（正文级重复由调用方按 read 结果算）。"""
		return {"entries": len(entries), "distinct_ranges": len({(e.offset, e.limit) for e in entries})}


def _source_basenames(text: str) -> set[str]:
	out: set[str] = set()
	for token in re.findall(r"[\w./\\-]+\.[A-Za-z]{1,10}", text):
		out.add(token.replace("\\", "/").rsplit("/", 1)[-1])
	return out


def _identity_ok(entry: Entry, idx: int, slice_text: str) -> bool:
	"""来源身份：切片里带 ``#node <idx>``，或引用所在那一行点名了该节点的来源文件。"""
	if f"#node {idx}" in slice_text:
		return True
	return bool(_source_basenames(entry.line) & _source_basenames(slice_text))


def check_recovery(
	*,
	targets: Sequence[tuple[int, str]],
	blocks: dict[int, tuple[int, int]],
	entries: Sequence[Entry],
	read: Callable[[int, int], str],
	max_pages: int = 200,
) -> ContractReport:
	"""对每个"未完整保留"的节点分别判 (a)/(b)。

	``read(offset, limit)`` 必须是**生产读取**（25k token 闸门；2000 行是默认值），
	失败时抛异常——不许自己切片，否则量到的是文件的物理包含，不是模型能拿到的东西。
	"""
	report = ContractReport()
	for idx, body in targets:
		block = blocks.get(idx)
		target_tokens = max(1, len(body) // 4)
		if block is None:
			report.verdicts.append(NodeVerdict(idx, "body_missing", True, True, 0, 0, target_tokens))
			continue
		first, last = block
		covering = sorted((e for e in entries if e.offset <= first and e.end >= last), key=lambda e: e.limit)
		if not covering:
			report.verdicts.append(NodeVerdict(idx, "no_entry", False, True, 0, 0, target_tokens))
			continue
		a_failed = False
		resolved = False
		# (a) 声明合同：照抄入口参数执行一次。
		for entry in covering:
			try:
				got = read(entry.offset, entry.limit)
			except Exception:
				a_failed = True
				continue
			resolved = True
			if body.strip() not in _deannotate(got):
				report.verdicts.append(NodeVerdict(idx, "wrong_node", True, True, 1, len(got) // 4, target_tokens))
				break
			if not _identity_ok(entry, idx, got):
				report.verdicts.append(NodeVerdict(idx, "identity_error", False, True, 1, len(got) // 4, target_tokens))
				break
			report.verdicts.append(NodeVerdict(idx, "ok", False, False, 1, len(got) // 4, target_tokens))
			break
		if not resolved:
			# 所有覆盖入口执行都失败 ⇒ (a) 红；给 (b) 一次分页机会。
			report.verdicts.append(_try_pagination(read, idx, body, first, last, covering[0].offset,
			                                       max_pages, a_failed=True, target_tokens=target_tokens))
	return report


def _try_pagination(read: Callable[[int, int], str], idx: int, body: str, first: int, last: int,
                    start: int, max_pages: int, *, a_failed: bool, target_tokens: int) -> NodeVerdict:
	"""(b)：从入口给出的起点按可发现的分页继续读，找 ``#node <idx>`` 标签并精确读回。

	页大小必须会**缩**：模型撞上 "exceeds maximum allowed tokens" 时的自然反应是减小
	``limit``，不是只往后挪 ``offset``。只挪 offset 的判定器会在长单行节点上把可恢复的
	节点误判成不可恢复（归档里一个节点常是一整行几万字符，200 行的页必然超限）。
	"""
	pages, tokens = 0, 0
	# 标签行在正文**之前**（`write_text_view` 的约定），所以扫描要从块首的上一行起，
	# 否则会永远看不见自己的目标标签。
	cursor = max(1, min(start, first - 1))
	while cursor <= last and pages < max_pages:
		pages += 1
		chunk = _read_backoff(read, cursor, PAGE_LINES)
		if chunk is None:
			cursor += 1  # 连一行都读不下 ⇒ 这一行本身超限，跳过它继续找
			continue
		tokens += len(chunk) // 4
		label_row = _label_row(chunk, cursor, idx)
		if label_row is None:
			cursor += max(1, _line_count(chunk) - 1)
			continue
		body_start = label_row + 1
		full = _read_exact(read, body_start, last - body_start + 1)
		if full is None:
			return NodeVerdict(idx, "ref_drift", a_failed, True, pages, tokens, target_tokens)
		if _deannotate(full).strip() == body.strip():
			return NodeVerdict(idx, "ok_via_pagination", a_failed, False, pages + 1,
			                   tokens + len(full) // 4, target_tokens)
		return NodeVerdict(idx, "identity_error", a_failed, True, pages + 1,
		                   tokens + len(full) // 4, target_tokens)
	return NodeVerdict(idx, "entry_exec_failed" if a_failed else "no_entry",
	                   a_failed, True, pages, tokens, target_tokens)


def _read_backoff(read: Callable[[int, int], str], offset: int, limit: int) -> str | None:
	"""从 ``offset`` 起尽量读一页；超限就**折半缩 limit**，直到 1 行。"""
	take = limit
	while take >= 1:
		try:
			return read(offset, take)
		except Exception:
			if take == 1:
				return None
			take = max(1, take // 4)
	return None


def _line_count(text: str) -> int:
	return text.count("\n") + 1


def _label_row(chunk: str, chunk_start: int, idx: int) -> int | None:
	"""返回 ``#node <idx>`` 在文件里的绝对行号。"""
	for offset_in_chunk, line in enumerate(chunk.split("\n")):
		if line.strip() == f"#node {idx}":
			return chunk_start + offset_in_chunk
	return None


def _read_exact(read: Callable[[int, int], str], offset: int, limit: int) -> str | None:
	"""精确读回一段（分页拼接）；任何一页失败都返回 None（宁可判失败，不假装成功）。"""
	if limit <= 0:
		return ""
	chunks: list[str] = []
	cursor, left = offset, limit
	while left > 0:
		take = min(PAGE_LINES, left)
		try:
			got = read(cursor, take)
		except Exception:
			return None
		if not got:
			return None
		chunks.append(got)
		cursor += take
		left -= take
	return "\n".join(chunks)


def _median(values: Sequence[int]) -> float:
	if not values:
		return 0.0
	values = sorted(values)
	mid = len(values) // 2
	return float(values[mid]) if len(values) % 2 else (values[mid - 1] + values[mid]) / 2.0
