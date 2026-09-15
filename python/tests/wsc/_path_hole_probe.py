"""只读探针：定位 ``path`` / ``path_recent`` 针的存活率缺口。

口径边界（先读再解释）：

* ``needle_survival`` 对 ``path`` 允许用 basename 命中，但对 ``path_recent``
  **没有**这个放宽；因此两个字段不能直接互相换算。
* 本探针对每条区域内路径同时报 ``exact``、``short`` 两种命中，并把漏失拆成
  ``state_not_selected`` / ``kept_skeleton_omits`` / ``pruned_card_files_omit`` /
  ``refs_only``。这样可区分「信息真的没有通道」与「已有通道但指标口径过严」。

用法：
    ./.venv/Scripts/python.exe tests/wsc/_path_hole_probe.py <session.jsonl> [turn]
    ./.venv/Scripts/python.exe tests/wsc/_path_hole_probe.py <sessions-dir> --sample 40
    ./.venv/Scripts/python.exe tests/wsc/_path_hole_probe.py <sessions-dir> --max-turns 80

零花费、只读，不写任何状态。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path


def _repo_root() -> Path:
	return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
if str(ROOT / "python") not in sys.path:
	sys.path.insert(0, str(ROOT / "python"))

from engine.compact import keep_tail_cut  # noqa: E402
from synaptic.assemble import render_main, render_pins  # noqa: E402
from synaptic.filestate import build_file_states, render_file_state  # noqa: E402
from synaptic.project import default_params, project  # noqa: E402
from synaptic.prune import render_card  # noqa: E402
from synaptic.replay import _as_api_message, load_jsonl, user_turn_starts  # noqa: E402
from synaptic.seeds import harvest_needles  # noqa: E402
from synaptic.textutil import normalize_path  # noqa: E402


def _norm_text(s: str) -> str:
	return " ".join(str(s or "").split())


def _path_short(p: str) -> str:
	return normalize_path(p).split("/")[-1]


def _session_paths(path: Path, max_turns: int) -> list[tuple[int, Path]]:
	if path.is_file():
		return [(max_turns, path)] if max_turns else [(0, path)]
	files = sorted(path.glob("*.jsonl"))
	if not files:
		return []
	if max_turns <= 0:
		return [(0, f) for f in files]
	# 均匀抽样，保留首尾附近的可解释性；0 表示该文件全部回合。
	step = max(1, len(files) / max_turns)
	return [(0, files[min(len(files) - 1, int(i * step))]) for i in range(max_turns)]


class Acc:
	def __init__(self) -> None:
		self.turns = 0
		self.total = 0
		self.exact = 0
		self.short = 0
		self.cats: Counter[str] = Counter()
		self.missing: Counter[str] = Counter()
		self.recent_total = 0
		self.recent_exact = 0
		self.recent_short = 0
		self.recent_cats: Counter[str] = Counter()
		self.recent_missing: Counter[str] = Counter()

	def add_turn(self, path: str, *, exact: bool, short: bool, cat: str, recent: bool) -> None:
		self.total += 1
		self.exact += int(exact)
		self.short += int(short)
		self.cats[cat if not (exact or short) else "survived"] += 1
		if not (exact or short):
			self.missing[path] += 1
		if recent:
			self.recent_total += 1
			self.recent_exact += int(exact)
			self.recent_short += int(short)
			self.recent_cats[cat if not (exact or short) else "survived"] += 1
			if not (exact or short):
				self.recent_missing[path] += 1


def _analyze_turn(
	*,
	session: str,
	turn: int,
	msgs: list[dict],
	params,
	acc: Acc,
) -> None:
	prefix = msgs[:]
	region_end = keep_tail_cut(prefix)
	if region_end <= 1:
		return
	proj = project(prefix, region_end=region_end, params=params, session=session)
	hot = _norm_text(proj.text)
	graph = proj.graph
	kept = set(proj.result.hot.kept_nodes)
	pruned = set(proj.result.hot.pruned_nodes)
	all_states = build_file_states(graph, msgs)
	ws_paths = {s.path for s in proj.result.hot.file_states}
	pin_paths = set(proj.seeds.pin_paths)
	card_files = {p for c in proj.result.hot.cards for p in c.files}
	main_blob = _norm_text(
		"\n".join(line for _, line in render_main(graph, tuple(sorted(kept)), params, pin_nodes=frozenset(proj.seeds.pin_nodes)))
	)
	pin_blob = _norm_text("\n".join(line for _, line in render_pins(proj.result.hot.pins)))
	card_blob = _norm_text("\n".join(render_card(c) for c in proj.result.hot.cards))
	ws_blob = _norm_text("\n".join(render_file_state(s) for s in proj.result.hot.file_states))

	# 只审计被压缩区域；尾部本来就是逐字携带，不应虚增存活率。
	nodes = [n for n in graph.nodes if n.idx < region_end]
	path_nodes: dict[str, list[int]] = {}
	for n in nodes:
		for p in n.refs:
			path_nodes.setdefault(p, []).append(n.idx)
	paths = list(dict.fromkeys(p for p in path_nodes if p))
	if not paths:
		return

	# 与 harvest_needles 的 path_recent 同口径：区域内后 25% 节点。
	cut = int(len(nodes) * 0.75)
	recent_paths = {p for n in nodes[cut:] for p in n.refs if p}

	for p in paths:
		exact = p in hot
		short = bool(_path_short(p)) and _path_short(p) in hot
		# 先判定“若渲染函数正常工作，本应存在哪条通道”，再判定漏失原因。
		in_state = p in all_states
		in_ws = p in ws_paths
		in_pin = p in pin_paths
		in_card = p in card_files
		in_main = p in main_blob
		in_pin_text = p in pin_blob
		in_ws_text = p in ws_blob
		in_card_text = p in card_blob
		has_kept = any(i in kept for i in path_nodes.get(p, ()))
		has_pruned = any(i in pruned for i in path_nodes.get(p, ()))
		if exact or short:
			cat = "survived"
		elif in_ws or in_ws_text:
			cat = "ws_row_not_found"
		elif in_main or in_pin_text:
			cat = "kept_skeleton_omits"
		elif in_card or in_card_text:
			cat = "card_row_not_found"
		elif has_kept:
			cat = "kept_skeleton_omits"
		elif in_state:
			cat = "state_not_selected"
		elif has_pruned:
			cat = "pruned_card_files_omit"
		else:
			cat = "refs_only"
		acc.add_turn(p, exact=exact, short=short, cat=cat, recent=p in recent_paths)


def _analyze_file(path: Path, max_turns: int, acc: Acc, params) -> int:
	api = [_as_api_message(r) for r in load_jsonl(path)]
	starts = user_turn_starts(api)
	if not starts:
		return 0
	turns = list(range(len(starts)))
	if max_turns and len(turns) > max_turns:
		step = len(turns) / float(max_turns)
		turns = [turns[min(len(turns) - 1, int(i * step))] for i in range(max_turns)]
	for t in turns:
		end = starts[t + 1] if t + 1 < len(starts) else len(api)
		acc.turns += 1
		try:
			_analyze_turn(session=path.stem, turn=t, msgs=api[:end], params=params, acc=acc)
		except Exception as exc:  # noqa: BLE001
			acc.cats[f"error:{type(exc).__name__}"] += 1
	return len(turns)


def main(argv: list[str]) -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("target", help="session.jsonl 或 sessions 目录")
	ap.add_argument("--turn", type=int, default=-1, help="单文件模式：指定回合，-1 为末回合")
	ap.add_argument("--sample", type=int, default=0, help="目录模式：抽样会话数；0=全部")
	ap.add_argument("--max-turns", type=int, default=0, help="每个会话最多分析回合数；0=全部")
	args = ap.parse_args(argv)

	target = Path(args.target)
	files = _session_paths(target, args.sample)
	if not files:
		print(f"no sessions: {target}")
		return 2
	params = default_params("Medium+", "closure")
	acc = Acc()
	processed = 0
	for _, f in files:
		processed += _analyze_file(f, args.max_turns, acc, params)

	def pct(a: int, b: int) -> str:
		return f"{(a / b if b else 1.0):.4f}"

	print(f"target={target}")
	print(f"files={len(files)} analyzed_turns={processed} path_occurrences={acc.total}")
	print(f"path      exact={acc.exact}/{acc.total} ({pct(acc.exact, acc.total)})  short={acc.short}/{acc.total} ({pct(acc.short, acc.total)})  alias_recovered={acc.short - acc.exact}")
	print(f"path_recent exact={acc.recent_exact}/{acc.recent_total} ({pct(acc.recent_exact, acc.recent_total)})  short={acc.recent_short}/{acc.recent_total} ({pct(acc.recent_short, acc.recent_total)})  alias_recovered={acc.recent_short - acc.recent_exact}")
	print("path categories:")
	for k, v in acc.cats.most_common():
		print(f"  {k}: {v}")
	print("path_recent categories:")
	for k, v in acc.recent_cats.most_common():
		print(f"  {k}: {v}")
	print("top missing paths (path):")
	for p, n in acc.missing.most_common(20):
		print(f"  {n:4}  {p}")
	print("top missing paths (path_recent):")
	for p, n in acc.recent_missing.most_common(12):
		print(f"  {n:4}  {p}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main(sys.argv[1:]))