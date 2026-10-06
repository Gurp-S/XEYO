"""恢复合同判定器（`_recovery_contract.py`）的契约测试。

钉的是**判据本身**：六种失败方式各有一条红测，两份合同各自成数、不许互相顶。
读的一侧默认用与生产同参数的模拟闸门（25,000 token / 2,000 行），最后一条再用**真
`FileReadTool`** 证明模拟与生产同判——否则"照抄入口即抛错"这个结论只是我桩在抛错。
"""

from __future__ import annotations

import pytest

pytest.importorskip("synaptic")

from tests.wsc._recovery_contract import (  # noqa: E402
	PAGE_LINES,
	STATE_ARCHIVED,
	STATE_FULL,
	STATE_PARTIAL,
	Entry,
	archive_blocks,
	check_recovery,
	classify,
	parse_read_refs,
)

_MAX_TOKENS = 25_000  # 与 tools/file_read_tool/file_read_tool.py 的 DEFAULT_MAX_TOKENS 同值
_MAX_LINES = 2_000    # 同 MAX_LINES_TO_READ；仅 limit=None 时的默认值，不是硬上限


def _node(idx: int, *, rows: int = 3, bulk: int = 0) -> str:
	"""造一个节点正文：首行点名来源文件（生产卡行的身份就靠它），后面是若干行。"""
	lines = [f"a{idx}.py output:"] + [f"l{idx}-{k}" for k in range(rows)]
	if bulk:
		lines.append("z" * bulk)
	return "\n".join(lines)


def _archive(nodes: dict[int, str]) -> list[str]:
	"""按 `write_text_view` 的行号约定造归档：``#node`` 头**不在**正文区间内。"""
	out: list[str] = []
	for idx in sorted(nodes):
		out.append(f"#node {idx}")
		out.extend(nodes[idx].split("\n"))
	return out


def _entries(nodes: dict[int, str], *idxs: int, name_source: bool = True) -> list[Entry]:
	"""给指定节点造"恰好覆盖其正文"的入口（等价于单节点句柄的渲染结果）。"""
	lines = _archive(nodes)
	blocks = archive_blocks(lines)
	out: list[Entry] = []
	for idx in idxs:
		first, last = blocks[idx]
		line = (f"[PRUNED] Read a{idx}.py 完成 → Read(file_path='archive.txt', "
		        f"offset={first}, limit={last - first + 1})" if name_source else
		        f"[PRUNED] 某条不点名来源的卡行 Read(file_path='archive.txt', "
		        f"offset={first}, limit={last - first + 1})")
		out.extend(parse_read_refs(line))
	return out


def _gated_read(lines: list[str]):
	"""模拟生产 Read：切片后按 `len//4` 估 token，超上限抛错（生产是 RuntimeError）。"""
	def read(offset: int, limit: int) -> str:
		if offset > len(lines):
			raise RuntimeError(f"offset {offset} out of range")
		slice_text = "\n".join(lines[offset - 1: offset - 1 + (_MAX_LINES if limit is None else limit)])
		if len(slice_text) // 4 > _MAX_TOKENS:
			raise RuntimeError(f"File content ({len(slice_text) // 4} tokens) exceeds maximum")
		return slice_text
	return read


_SMALL = {1: _node(1), 2: _node(2), 3: _node(3)}


# ---------------------------------------------------------------------------
# 分母：三态
# ---------------------------------------------------------------------------


def test_denominator_distinguishes_full_partial_and_archived() -> None:
	"""同一 ID 的正文被截成摘录时，不许仍算"完整保留"。"""
	lines = _archive(_SMALL)
	blocks = archive_blocks(lines)
	f1 = blocks[1][0]
	f3 = blocks[3][0]
	excerpt = "\n".join(_SMALL[1].split("\n")[:1])
	emitted = f"[MAIN] 片段起于第 {f1} 行\n{excerpt}\n另一段起于第 {f3} 行\n{_SMALL[3]}"
	buckets = classify(list(_SMALL.items()), emitted)
	assert buckets[STATE_FULL] == [3]
	assert buckets[STATE_PARTIAL] == [1]
	assert buckets[STATE_ARCHIVED] == [2]


def test_deannotation_prevents_false_archived() -> None:
	"""发射面带 ``cat -n`` 前缀与 ``<tool_output>`` 包裹 ⇒ 不剥壳会把已发出的判成仅归档。"""
	body = _SMALL[2]
	rows = body.split("\n")
	wrapped = ('<tool_output tool="Bash" untrusted="true">\n'
	           + "\n".join(f"   {i + 1}→{row}" for i, row in enumerate(rows))
	           + "\n</tool_output>")
	assert classify([(2, body)], wrapped)[STATE_FULL] == [2], "剥壳失败：投影注入把完整保留伪装成归档"


# ---------------------------------------------------------------------------
# (a) 声明合同
# ---------------------------------------------------------------------------


def test_declared_entry_that_executes_and_matches_is_clean() -> None:
	nodes = _SMALL
	lines = _archive(nodes)
	report = check_recovery(targets=[(2, nodes[2])], blocks=archive_blocks(lines),
	                        entries=_entries(nodes, 2), read=_gated_read(lines))
	axis = report.axis_correctness()
	assert axis["verdict:ok"] == 1
	assert axis["a_failed:False"] == 1 and axis["b_failed:False"] == 1


def test_removing_the_emitted_entry_must_fail_even_if_archive_is_intact() -> None:
	"""删掉发射入口 ⇒ 必须失败。现有 `recoverability()` 判不出这类：它比的是
	`cold.handles`（归档里的绑定），归档完好就报 1.000。"""
	nodes = _SMALL
	lines = _archive(nodes)
	assert archive_blocks(lines)[2]
	report = check_recovery(targets=[(2, nodes[2])], blocks=archive_blocks(lines),
	                        entries=[], read=_gated_read(lines))
	assert report.verdicts[0].verdict == "no_entry"
	assert report.axis_correctness()["b_failed:True"] == 1


def test_entry_returning_another_node_is_wrong_node() -> None:
	"""入口执行成功、正文却不是目标的 ⇒ wrong_node（顾问要求判"读到错误节点"）。"""
	nodes = _SMALL
	lines = _archive(nodes)
	blocks = archive_blocks(lines)
	f2, l2 = blocks[2]
	entries = list(parse_read_refs(f"[PRUNED] Read a2.py → Read(file_path='archive.txt', "
	                              f"offset={f2}, limit={l2 - f2 + 1})"))

	def lying_read(offset: int, limit: int) -> str:
		return "totally unrelated content a9.py"

	report = check_recovery(targets=[(2, nodes[2])], blocks=blocks, entries=entries, read=lying_read)
	assert report.verdicts[0].verdict == "wrong_node"
	assert report.verdicts[0].contract_b_failed is True


def test_body_absent_from_archive_is_body_missing() -> None:
	"""归档里根本没有这块正文（引用必然指向不存在的内容）⇒ 两份合同都失败。"""
	nodes = _SMALL
	lines = _archive(nodes)
	report = check_recovery(targets=[(77, _node(77))], blocks=archive_blocks(lines),
	                        entries=_entries(nodes, 2), read=_gated_read(lines))
	assert report.verdicts[0].verdict == "body_missing"
	assert report.verdicts[0].contract_a_failed is True
	assert report.verdicts[0].contract_b_failed is True


def test_identity_needs_label_or_naming_line() -> None:
	"""``#node`` 标签按设计落在区间**之外** ⇒ 卡行不点名来源时，正文对得上也算身份不成立。"""
	nodes = _SMALL
	lines = _archive(nodes)
	report = check_recovery(targets=[(2, nodes[2])], blocks=archive_blocks(lines),
	                        entries=_entries(nodes, 2, name_source=False), read=_gated_read(lines))
	assert report.verdicts[0].verdict == "identity_error"
	assert report.verdicts[0].contract_b_failed is True


# ---------------------------------------------------------------------------
# (b) 恢复合同：违反 (a) 不等于违反 (b)
# ---------------------------------------------------------------------------


def test_oversized_entry_breaks_a_but_pagination_can_still_satisfy_b() -> None:
	"""组入口一次读超 25k ⇒ (a) 红；从它给的起点分页仍能找到目标 ⇒ (b) 成立。

	这正是顾问要的分法：不能因为 (a) 红就把节点算成"恢复不了"。
	"""
	nodes = {1: _node(1, bulk=200_000), 2: _node(2)}
	lines = _archive(nodes)
	blocks = archive_blocks(lines)
	f1, _l1 = blocks[1]
	_f2, l2 = blocks[2]
	entries = list(parse_read_refs(f"[PRUNED] Read a2.py → Read(file_path='archive.txt', "
	                              f"offset={f1}, limit={l2 - f1 + 1})"))
	report = check_recovery(targets=[(2, nodes[2])], blocks=blocks, entries=entries,
	                        read=_gated_read(lines), max_pages=400)
	verdict = report.verdicts[0]
	assert verdict.contract_a_failed is True, "声明参数超上限，(a) 必须判失败"
	assert verdict.verdict == "ok_via_pagination", f"分页可恢复却判成不可恢复：{verdict.verdict}"
	assert verdict.contract_b_failed is False


def test_pagination_that_never_reaches_the_node_fails_b() -> None:
	"""入口起点在目标块之后 ⇒ 分页也找不到 ⇒ (b) 失败。"""
	nodes = {1: _node(1, bulk=200_000), 2: _node(2)}
	lines = _archive(nodes)
	blocks = archive_blocks(lines)
	_f2, l2 = blocks[2]
	entries = list(parse_read_refs(f"[PRUNED] Read a2.py → Read(file_path='archive.txt', "
	                              f"offset={l2 + 1}, limit=5)"))
	report = check_recovery(targets=[(2, nodes[2])], blocks=blocks, entries=entries,
	                        read=_gated_read(lines), max_pages=2)
	assert report.verdicts[0].contract_b_failed is True


# ---------------------------------------------------------------------------
# 追加后旧引用不得漂移
# ---------------------------------------------------------------------------


def test_appending_to_the_archive_does_not_move_existing_references() -> None:
	"""归档追加后，旧引用必须仍恢复到原来的节点（插入序契约）。"""
	base = {1: _node(1), 2: _node(2)}
	lines = _archive(base)
	blocks = archive_blocks(lines)
	f2, l2 = blocks[2]
	before = _gated_read(lines)(f2, l2 - f2 + 1)
	after_lines = lines + ["#node 3"] + _node(3).split("\n")  # 新块一律追加在末尾
	after = _gated_read(after_lines)(f2, l2 - f2 + 1)
	assert after == before, "追加把旧引用指到了别的内容 ⇒ ref_drift"


# ---------------------------------------------------------------------------
# 解析器与真生产 Read 的一致性
# ---------------------------------------------------------------------------


def test_parse_read_refs_only_trusts_emitted_text() -> None:
	text = ("[PRUNED] 已排除 Read(file_path='.xeyo_offload/wsc/s.txt', offset=47, limit=6237)\n"
	        "[MAIN] Read(file_path='a.txt', offset=1, limit=2)")
	entries = parse_read_refs(text)
	assert [(e.path, e.offset, e.limit) for e in entries] == [
		(".xeyo_offload/wsc/s.txt", 47, 6237), ("a.txt", 1, 2)]
	assert entries[0].line.startswith("[PRUNED]")


def test_production_read_gate_matches_the_simulated_one(tmp_path) -> None:
	"""模拟闸门必须与真 `FileReadTool` 同判：超 25k 的那次，真工具也得失败。"""
	import asyncio

	from engine.abort import AbortController
	from tools.file_read_tool.file_read_tool import FileReadTool

	nodes = {1: _node(1, bulk=200_000), 2: _node(2)}
	lines = _archive(nodes)
	view = tmp_path / "archive.txt"
	view.write_text("\n".join(lines) + "\n", encoding="utf-8")
	blocks = archive_blocks(lines)
	f1, l1 = blocks[1]
	tool = FileReadTool(cwd=str(tmp_path))

	def real_read(offset: int, limit: int) -> str:
		res = asyncio.run(tool.execute({"file_path": str(view), "offset": offset, "limit": limit},
		                               AbortController()))
		if getattr(res, "is_error", False):
			raise RuntimeError(str(getattr(res, "content", res)))
		return str(res.content)

	sim = _gated_read(lines)
	cases = [(f1, l1 - f1 + 1), (f1, PAGE_LINES), (blocks[2][0], 1)]
	assert cases, "探针为空：一条都没比就不许说闸门一致"
	for offset, limit in cases:
		sim_err = real_err = None
		try:
			sim(offset, limit)
		except Exception as exc:  # noqa: BLE001 - 只比"是否抛错"
			sim_err = type(exc).__name__
		try:
			real_read(offset, limit)
		except Exception as exc:  # noqa: BLE001
			real_err = type(exc).__name__
		assert bool(sim_err) == bool(real_err), f"闸门不一致 offset={offset} limit={limit}: {sim_err} vs {real_err}"
