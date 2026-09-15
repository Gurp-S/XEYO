"""文件状态表（规则 5）：同文件不是只留最后一条 read。

维护每个路径的：最后有效 read、已读区间、观测 hash、read 之后的变更（stale）、
相关未解决错误。目标是杜绝「最后一次 read 只读了一半却当成完整文件」。
"""

from __future__ import annotations

from dataclasses import dataclass

from synaptic.graph import Graph
from synaptic.textutil import (
	classify_tool,
	content_hash,
	node_token_len,
	read_range,
	tool_input_paths,
	tool_result_blocks,
	tool_result_text,
	tool_use_blocks,
)
from synaptic.types import (
	KIND_TOOL_RESULT,
	KIND_TOOL_USE,
	FileState,
)


@dataclass(frozen=True)
class _Read:
	idx: int
	path: str
	text: str
	rng: tuple[int, int] | None


@dataclass(frozen=True)
class _Write:
	idx: int
	path: str
	summary: str
	abs_path: str = ""


def _write_summary(name: str, inp: dict) -> str:
	"""写工具的变更摘要（只留可判读的最小信息）。"""
	if name == "Write":
		body = str(inp.get("content") or "")
		return f"Write 全文覆盖（{body.count(chr(10)) + 1} 行 / {len(body)} 字符）"
	if name in ("Edit", "MultiEdit", "str_replace_editor"):
		old = str(inp.get("old_string") or inp.get("old_str") or "")
		new = str(inp.get("new_string") or inp.get("new_str") or "")
		edits = inp.get("edits")
		if isinstance(edits, list) and edits:
			return f"MultiEdit {len(edits)} 处替换"
		if old or new:
			o = _first_line(old)
			n = _first_line(new)
			return f"-{o} +{n}"
		return "Edit（无 old/new 字段）"
	return f"{name} 变更"


def _first_line(text: str, limit: int = 80) -> str:
	for line in str(text or "").splitlines():
		s = line.strip()
		if s:
			return s[:limit]
	return ""


def collect_reads_writes(
	graph: Graph, messages: list[dict]
) -> tuple[list[_Read], list[_Write]]:
	"""按时间顺序收集所有 read / write 事件。"""
	reads: list[_Read] = []
	writes: list[_Write] = []
	name_by_uid: dict[str, str] = {}
	inp_by_uid: dict[str, dict] = {}
	for msg in messages:
		for u in tool_use_blocks(msg):
			uid = str(u.get("id") or "")
			name = str(u.get("name") or "")
			inp = u.get("input") if isinstance(u.get("input"), dict) else {}
			if uid:
				name_by_uid[uid] = name
				inp_by_uid[uid] = inp

	for idx, node in enumerate(graph.nodes):
		if node.kind != KIND_TOOL_RESULT:
			continue
		uid = node.tool_use_id
		name = name_by_uid.get(uid, node.tool_name)
		inp = inp_by_uid.get(uid, {})
		is_write, read_only, _ = classify_tool(name, inp)
		paths = list(tool_input_paths(inp))
		if not paths:
			paths = [p for p in node.refs]
		if not paths:
			continue
		text = ""
		for b in tool_result_blocks(messages[idx]) if idx < len(messages) else []:
			text = tool_result_text(b)
			break
		if is_write:
			for p in paths:
				writes.append(_Write(idx=idx, path=p, summary=_write_summary(name, inp)))
		elif read_only and name in ("Read", "NotebookRead"):
			rng = read_range(inp, text)
			for p in paths:
				reads.append(_Read(idx=idx, path=p, text=text, rng=rng))
	return reads, writes


def build_file_states(graph: Graph, messages: list[dict]) -> dict[str, FileState]:
	"""构建文件状态表。"""
	reads, writes = collect_reads_writes(graph, messages)

	# 路径 -> 相关错误签名（按节点序）
	errs_by_path: dict[str, list[str]] = {}
	for n in graph.nodes:
		if n.is_error and n.error_sig:
			for p in n.refs:
				errs_by_path.setdefault(p, []).append(n.error_sig)

	states: dict[str, FileState] = {}
	# 先处理「有 read 的路径」
	by_path: dict[str, list[_Read]] = {}
	for r in reads:
		by_path.setdefault(r.path, []).append(r)
	for path, rs in by_path.items():
		last = rs[-1]
		ranges = [r.rng for r in rs if r.rng is not None]
		# 合并连续区间（去重后按起点排序）
		merged: list[tuple[int, int]] = []
		for s, e in sorted(set(ranges)):
			if merged and s <= merged[-1][1] + 1:
				merged[-1] = (merged[-1][0], max(merged[-1][1], e))
			else:
				merged.append((s, e))
		ws = [w for w in writes if w.path == path and w.idx > last.idx]
		stale = bool(ws)
		related = tuple(
			dict.fromkeys(
				sig
				for e_idx, sig in _err_pairs(graph, path)
				if e_idx >= last.idx
			)
		)
		states[path] = FileState(
			path=path,
			observed_hash=content_hash(last.text),
			last_read_idx=last.idx,
			read_ranges=tuple(merged),
			stale=stale,
			stale_at=ws[0].idx if ws else -1,
			diff_summary="；".join(w.summary for w in ws[:3]),
			related_errors=related,
		)

	# 再处理「只写未读」的路径（仍要出现在状态表里，否则会出现盲区）
	for w in writes:
		if w.path in states:
			continue
		related = tuple(
			dict.fromkeys(sig for e_idx, sig in _err_pairs(graph, w.path) if e_idx >= w.idx)
		)
		states[w.path] = FileState(
			path=w.path,
			observed_hash="",
			last_read_idx=-1,
			read_ranges=(),
			stale=False,
			stale_at=-1,
			diff_summary=w.summary,
			related_errors=related,
		)
	return states


def _err_pairs(graph: Graph, path: str) -> list[tuple[int, str]]:
	out: list[tuple[int, str]] = []
	for idx in graph.file_index.get(path, ()):
		n = graph.node(idx)
		if n is not None and n.is_error and n.error_sig:
			out.append((idx, n.error_sig))
	return out


def working_set(
	states: dict[str, FileState],
	*,
	limit: int = 12,
	pin_paths: tuple[str, ...] = (),
	recent_paths: tuple[str, ...] = (),
) -> tuple[FileState, ...]:
	"""工作集：PIN 路径 > 近期触碰路径 > 其余按最近触碰排序。

	时间不是唯一价值——PIN 路径（目标/未解决错误直接涉及的）优先保留。近期路径
	与 ``harvest_needles(path_recent)`` 共用同一集合，避免「还在用」的路径在
	存活率审计里算近期、在工作集排序里却先被丢掉。
	"""
	pin_set = set(pin_paths)
	recent_set = set(recent_paths) - pin_set
	pinned = [states[p] for p in pin_paths if p in states]
	recent: list[FileState] = []
	seen_recent: set[str] = set()
	for path in recent_paths:
		if path in pin_set or path in seen_recent or path not in states:
			continue
		seen_recent.add(path)
		recent.append(states[path])
	rest = [
		s
		for p, s in states.items()
		if p not in pin_set and p not in recent_set
	]
	rest.sort(key=lambda s: (max(s.last_read_idx, s.stale_at), s.path), reverse=True)
	out = list(pinned)
	for s in (*recent, *rest):
		if len(out) >= limit:
			break
		out.append(s)
	return tuple(out[:limit])


def render_file_state(s: FileState) -> str:
	"""把一条文件状态渲染成热层文本行（Medium+ 的 WORKING SET 段）。"""
	rng = ",".join(f"{a}-{b}" for a, b in s.read_ranges) if s.read_ranges else "未读"
	bits = [f"{s.path}"]
	if s.observed_hash:
		bits.append(f"hash={s.observed_hash}")
	if s.stale:
		tail = f" (改于 #{s.stale_at})" if s.stale_at >= 0 else ""
		bits.append(f"STALE{tail}")
		if s.diff_summary:
			bits.append(f"diff: {_clip(s.diff_summary, 120)}")
	elif s.diff_summary:
		bits.append(f"写入: {_clip(s.diff_summary, 120)}")
	bits.append(f"read: {rng}")
	if s.related_errors:
		bits.append(f"错误: {_clip('; '.join(s.related_errors), 100)}")
	return " | ".join(bits)


def file_state_tokens(states: tuple[FileState, ...]) -> int:
	return sum(node_token_len(render_file_state(s)) for s in states)


def _clip(text: str, limit: int) -> str:
	s = " ".join(str(text or "").split())
	return s if len(s) <= limit else s[: limit - 1] + "…"
