"""文件状态表（规则 5）：同文件不是只留最后一条 read。

维护每个路径的：最后有效 read、已读区间、观测 hash、read 之后的变更（stale）、
相关未解决错误。目标是杜绝「最后一次 read 只读了一半却当成完整文件」。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from common.read_target import single_file_target
from synaptic.graph import Graph, result_is_error
from synaptic.textutil import (
	classify_tool,
	content_hash,
	is_full_file_read,
	node_token_len,
	normalize_path,
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


def collect_reads_writes(graph: Graph, messages: list[dict]) -> tuple[list[_Read], list[_Write]]:
	"""Collect successful receipts per call, including batched result messages."""
	reads: list[_Read] = []
	writes: list[_Write] = []
	uses = {str(u.get("id")): u for msg in messages for u in tool_use_blocks(msg) if u.get("id")}
	for idx, msg in enumerate(messages):
		for block in tool_result_blocks(msg):
			uid = str(block.get("tool_use_id") or "")
			use = uses.get(uid, {})
			name = str(use.get("name") or msg.get("name") or "")
			inp = use.get("input") if isinstance(use.get("input"), dict) else {}
			command = str(inp.get("command") or inp.get("cmd") or "")
			if result_is_error(block, command=command, tool_name=name):
				continue
			is_write, read_only, replay = classify_tool(name, inp)
			paths = list(tool_input_paths(inp))
			if not paths and read_only and name in ("Bash", "exec_command", "exec"):
				# 读观测的身份 = 命令点名的**唯一**文件（判据与 bash 路由、卡面 target 同源，
				# 见 common.read_target）。旧实现 fallback 到结果正文的 refs（提及路径），
				# 把正文里提到的文件名记成了读观测（现场：一条 Get-Content 产出 5 条
				# read:未读 的裸名条目），命令真正的目标反而没进表。
				target = single_file_target(command)
				paths = [normalize_path(target)] if target else []
			elif not paths and use:
				paths = list(graph.node(idx).refs) if graph.node(idx) is not None else []
			if not paths:
				continue
			text = tool_result_text(block)
			from synaptic.read_receipt import is_unchanged_view
			if name in {"Read", "NotebookRead"} and is_unchanged_view(block):
				# A deduplication receipt contains no new file content or range.
				continue
			if is_write:
				for path in paths:
					writes.append(_Write(idx=idx, path=path, summary=_write_summary(name, inp)))
			elif read_only:
				precise = name in ("Read", "NotebookRead")
				if not precise and not is_full_file_read(replay):
					continue
				rng = read_range(inp, text) if precise else None
				for path in paths:
					reads.append(_Read(idx=idx, path=path, text=text, rng=rng))
	return reads, writes


def _merge_suffix_keys(
	reads: list[_Read], writes: list[_Write]
) -> tuple[list[_Read], list[_Write]]:
	"""相对短键并入唯一后缀匹配的完整键（纯字符串判据，确定性）。

	现场（sess_musrbw08_n9tly2）：``docs/wsc2-handoff-2026-09-23.md``（Bash 相对
	形态）与 ``/lea/XenYon code/docs/wsc2-handoff-2026-09-23.md``（Read 完整形态）
	是同一文件的两条记录，模型无法判断哪条是当前版本。两个完整键都以同一短键
	结尾（同名文件不同目录）时**不归并**——不许猜。
	"""
	full_keys = sorted(
		{p for p in (r.path for r in reads) if p.startswith("/")}
		| {w.path for w in writes if w.path.startswith("/")}
	)
	if not full_keys:
		return reads, writes

	def resolve(path: str) -> str:
		if not path or path.startswith("/"):
			return path
		matches = [key for key in full_keys if key.endswith("/" + path)]
		return matches[0] if len(matches) == 1 else path

	return (
		[replace(r, path=resolve(r.path)) for r in reads],
		[replace(w, path=resolve(w.path)) for w in writes],
	)


def build_file_states(graph: Graph, messages: list[dict]) -> dict[str, FileState]:
	"""构建文件状态表。"""
	reads, writes = collect_reads_writes(graph, messages)
	reads, writes = _merge_suffix_keys(reads, writes)

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
		# **只有区间已知的观测**（= Read 系）才配当 hash / 已读区间的源：`observed_hash` 进
		# `freeze.file_version`，若让 `cat` 的回执文本（含头部包装噪声）也参与，一次
		# Read→bash 切换会让 hash 凭空跳变 ⇒ 白付一次前缀 churn。所以：hash 与区间取
		# 最后一次**精确读**，而过期时钟 / 错误关联取最后一次**有效观测**（精确读或整文件读）。
		# 原生（Read 驱动）会话里两者恒等 ⇒ 行为逐字节不变。
		precise = [r for r in rs if r.rng is not None]
		last_precise = precise[-1] if precise else None
		ranges = [r.rng for r in precise]
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
			observed_hash=content_hash(last_precise.text) if last_precise else "",
			last_read_idx=last_precise.idx if last_precise else last.idx,
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
