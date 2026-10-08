"""真实会话上的「覆盖判据」体检（只读诊断，不进主链路）。

``python/synaptic/freshness.error_covered_by`` 判定「一条失败已被后续证据覆盖」，
据此把该失败从 ``[UNRESOLVED]`` 里摘掉。判据过宽 = 把仍在复发的失败判成已闭合
（模型看不到仍未解决的问题）；过窄 = 失败永久钉住、上下文只增不减。

本脚本不改引擎，只把真实 transcript 跑一遍，输出三个可核对的量：

1. covered / uncovered 的错误节点清单（工具、现场引用、错误签名）；
2. 覆盖者与失败的关系类型（同工具？现场引用是否相交）——判据失效的环节在此显形；
3. **闭合后复发**：同一错误签名在覆盖者之后再次出现 → 误闭的直接证据。

fail-open：任何异常打印 ``[skip]`` 后退出 0；不写任何文件。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import traceback

_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "python")):
	if _p not in sys.path:
		sys.path.insert(0, _p)

_WS = re.compile(r"\s+")


def _blocks(msg: dict) -> list[dict]:
	c = msg.get("content")
	return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def _census(messages: list[dict]) -> dict[str, int]:
	out: dict[str, int] = {}
	for m in messages:
		for b in _blocks(m):
			t = str(b.get("type") or "?")
			out[t] = out.get(t, 0) + 1
	return out


def _sessions_dir() -> pathlib.Path:
	"""会话根走产品自己的权威解析（认 ``XEYO_SESSIONS_DIR``）。

	不在这里拼死 ``~/.xeyo/sessions``：``tests/test_data_root_overrides.py`` 钉的就是
	这个家族——路径读错树时，报出来的"现状"其实是别的目录。
	"""
	from memory.working import _sessions_dir as _authoritative

	return pathlib.Path(str(_authoritative()))


def _load(sid: str) -> tuple[pathlib.Path, list[dict]]:
	p = _sessions_dir() / f"{sid}.jsonl"
	msgs: list[dict] = []
	if p.exists():
		for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
			line = line.strip()
			if not line:
				continue
			try:
				row = json.loads(line)
			except Exception:
				continue
			if isinstance(row, dict):
				msgs.append(row)
	return p, msgs


def _tool_of(node) -> str:
	for attr in ("tool", "name", "tool_name"):
		v = getattr(node, attr, None)
		if v:
			return str(v)
	return "?"


def _label(graph, idx: int) -> str:
	n = graph.node(idx)
	if n is None:
		return f"#{idx}"
	return f"#{idx}:{_tool_of(n)}"


def _edges(graph, idx: int, edge_names: dict[str, str]) -> dict[str, tuple[int, ...]]:
	out: dict[str, tuple[int, ...]] = {}
	for const, short in edge_names.items():
		kind = getattr(_graph_mod, const, None)
		if kind is None:
			continue
		try:
			dst = tuple(int(d) for d in graph.outgoing(idx, kind))
		except Exception:
			continue
		if dst:
			out[short] = dst
	return out


def _refs_of(graph, idx: int) -> frozenset[int]:
	"""现场引用：所有非 provenance（tool_use）边指向的节点。"""
	refs: set[int] = set()
	for const, kind in getattr(_graph_mod, "__dict__", {}).items():
		if not const.startswith("EDGE_") or const == "EDGE_USE":
			continue
		try:
			refs.update(int(d) for d in graph.outgoing(idx, kind))
		except Exception:
			continue
	return frozenset(refs)


def _sig_key(sig: str) -> str:
	return _WS.sub(" ", re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", " ", sig.lower())).strip()[:56]


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--sid", default="sess_mux0q86a_ea2kv9")
	ap.add_argument("--rows", type=int, default=40)
	args = ap.parse_args()

	print(f"session = {args.sid}")
	path, messages = _load(args.sid)
	print(f"transcript = {path} (exists={path.exists()}, messages={len(messages)})")
	if not messages:
		print("[skip] 无消息")
		return 0
	print(f"block census = {_census(messages)}")

	from synaptic.freshness import error_covered_by

	graph = _graph_mod.build_graph(messages)
	total = len(graph.nodes)
	print(f"graph nodes = {total}")

	errors = [
		n
		for n in graph.nodes
		if getattr(n, "is_error", False) and getattr(n, "error_sig", "")
	]
	print(f"error nodes = {len(errors)}")

	by_sig: dict[str, list[int]] = {}
	for n in errors:
		by_sig.setdefault(_sig_key(str(n.error_sig)), []).append(int(n.idx))

	covered = recur = 0
	same_tool = overlap = 0
	rows: list[str] = []
	for n in errors:
		idx = int(n.idx)
		hit = error_covered_by(graph, n, total)
		sig = _WS.sub(" ", str(n.error_sig))[:70]
		later_same = [
			int(d.idx)
			for d in graph.nodes
			if int(d.idx) > idx and not getattr(d, "is_error", False)
			and _tool_of(d) == _tool_of(n) and _refs_of(graph, int(d.idx))
			and _refs_of(graph, int(d.idx)) & _refs_of(graph, idx)
		]
		if hit is None:
			rows.append(
				f"#{idx:<4} {_tool_of(n):<14} covered=-  "
				f"later_same_refs_ok={n2str(later_same)}  sig={sig}"
			)
			continue
		covered += 1
		by = hit[0]
		by_idx = int(by) if isinstance(by, int) else -1
		t_same = bool(_tool_of(graph.node(by_idx)) == _tool_of(n)) if by_idx >= 0 else False
		ov = bool(_refs_of(graph, by_idx) & _refs_of(graph, idx)) if by_idx >= 0 else False
		same_tool += int(t_same)
		overlap += int(ov)
		recurring = [d for d in by_sig.get(_sig_key(str(n.error_sig)), []) if d > idx]
		recur += int(bool(recurring))
		rows.append(
			f"#{idx:<4} {_tool_of(n):<14} covered={_label(graph, by_idx):<18} "
			f"same_tool={t_same} refs_overlap={ov} "
			f"recur={n2str(recurring)}  sig={sig}"
		)

	print("--- 错误节点判定 ---")
	for r in rows[: max(0, args.rows)]:
		print(r)
	if len(rows) > args.rows:
		print(f"... ({len(rows) - args.rows} more)")

	def _verb(node) -> str:
		""""操作种类"：Bash 取首个非 cd 动词，文件工具退化为工具名。"""
		for seg in str(getattr(node, "command", "") or "").split(";"):
			toks = seg.strip().strip("\"'(").split()
			if not toks:
				continue
			if toks[0].lower() in ("cd", "pushd", "set-location"):
				continue
			return toks[0].lower()
		return _tool_of(node).lower()

	def _shadow(graph, n) -> tuple[int, str]:
		"""候选判据（影子，fail-closed）：证据非空 ∧ 同工具 ∧ 同动词 ∧ 范围不缩小 ∧ 现场相交 ∧ 成功 ∧ 在后。"""
		from synaptic.freshness import _has_failure_evidence, _marker_at

		verb = _verb(n)
		scope_n = {str(x) for x in getattr(n, "scope_paths", ()) or ()}
		refs_n = {str(x) for x in getattr(n, "refs", ()) or ()}
		if not (scope_n or refs_n):
			return -1, "无证据(scope/refs 皆空)"
		for m in graph.nodes:
			if int(m.idx) <= int(n.idx) or getattr(m, "is_error", False):
				continue
			if _tool_of(m) != _tool_of(n) or _verb(m) != verb:
				continue
			# 覆盖者自查（与引擎判据同口径）：整调用 is_error 只看最后一段退出码。
			if _has_failure_evidence(str(getattr(m, "text", "") or "")):
				continue
			if not _marker_at(graph, int(m.idx), None):
				continue
			scope_m = {str(x) for x in getattr(m, "scope_paths", ()) or ()}
			refs_m = {str(x) for x in getattr(m, "refs", ()) or ()}
			if scope_n and not (scope_m >= scope_n):
				continue
			if refs_n and not (refs_m & refs_n):
				continue
			return int(m.idx), (
				f"scope{n2str(sorted(scope_n))}->{n2str(sorted(scope_m))} "
				f"refs∩{n2str(sorted(refs_m & refs_n))}"
			)
		return -1, ""

	ev = sum(
		1
		for n in errors
		if getattr(n, "scope_paths", ()) or getattr(n, "refs", ())
	)
	print(f"evidence_available={ev}/{len(errors)}   (调用声明范围 ∪ 结果现场)")

	print("--- 影子判据（证据链：同工具/同动词/范围不缩小/现场相交/成功/在后）---")
	shadow_hits = 0
	for n in errors:
		h, why = _shadow(graph, n)
		shadow_hits += int(h >= 0)
		print(f"#{int(n.idx):<4} {_tool_of(n):<12} shadow={_label(graph, h) if h >= 0 else '-':<18} {why}")
		if h >= 0:
			m = graph.node(h)
			head = " ".join(str(getattr(m, "text", "") or "").split())[:200]
			print(f"      覆盖者 is_error={bool(getattr(m, 'is_error', False))} 正文: {head}")
	print(f"shadow_covered={shadow_hits}")

	print("--- 段级失败：未升格残留（判据已入主链路 synaptic/graph._looks_like_segment_failure）---")
	seg_fail = re.compile(r"(?m)^\s*FAILED\s+\S+::\S+")

	def _seg_evidence(text: str) -> bool:
		# 行首独立的跑测摘要（`10 failed, 20 passed in 2.39s`）……
		if re.search(r"(?m)^\s*[1-9]\d*\s+failed\b[^\n]*\b(?:passed|deselected)\b", text):
			return True
		# ……或 pytest 短摘要段头 + 至少一条 `FAILED <path>::<test>`。
		return "short test summary info" in text and bool(seg_fail.search(text))

	# 残留 = 主链路口径下仍判 is_error=False、却有段级证据 ⇒ 判据漏判（回归信号，正常为 0）。
	# 「只升格、不撤销」的可复现复核：仅把 graph._looks_like_segment_failure 变异成 return False，
	# 比对同一 transcript 两次 build_graph 的错误节点差集（实测 3 新增 / 0 撤销）。
	up = [
		n
		for n in graph.nodes
		if _tool_of(n) == "Bash"
		and getattr(n, "kind", "") == "tool_result"
		and not getattr(n, "is_error", False)
		and _seg_evidence(str(getattr(n, "text", "") or ""))
	]
	print(f"段级未升格残留={len(up)}   (仅 Bash；正常为 0 = 主链路无漏判)")
	for n in up[:10]:
		cmd = " ".join(str(getattr(n, "command", "") or "").split())[:80]
		head = " ".join(str(getattr(n, "text", "") or "").split())[:140]
		print(f"  #{int(n.idx)} cmd={cmd}")
		print(f"      正文: {head}")

	print("--- 汇总 ---")
	print(f"error_nodes={len(errors)} covered={covered} uncovered={len(errors) - covered}")
	print(f"covered_same_tool={same_tool} covered_refs_overlap={overlap}")
	print(f"covered_and_recurring={recur}   <- 误闭的直接证据（覆盖者之后同一签名再出现）")
	return 0


def n2str(idxs: list[int]) -> str:
	return ",".join(f"#{i}" for i in idxs[:6]) or "-"


_graph_mod = None

if __name__ == "__main__":
	try:
		from synaptic import graph as _g

		_graph_mod = _g
		sys.exit(main())
	except SystemExit:
		raise
	except Exception:
		print("[skip] 诊断自身失败（fail-open，不改引擎状态）")
		traceback.print_exc(file=sys.stdout)
		sys.exit(0)
